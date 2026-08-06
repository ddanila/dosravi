"""Reference agent used for native integration and protocol fault tests.

It models DOS workspace and replay behavior.  It is not a replacement for the
DOS build; all wire-level behavior is shared with DOSRAVI.COM.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections import OrderedDict
from pathlib import Path

from .protocol import (
    Command,
    Flag,
    Frame,
    FrameDecoder,
    FrameType,
    ProtocolError,
    Status,
    Tag,
    as_u32,
    file_crc32,
    first,
    parse_request,
    response_payload,
    tlv,
    tlv_text,
    tlv_u32,
)


class Agent:
    def __init__(self, root: str | Path, replay_entries: int = 32):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.decoder = FrameDecoder()
        self.replay_entries = replay_entries
        self.replays: OrderedDict[int, tuple[bytes, bytes]] = OrderedDict()
        self.executions: dict[int, tuple[bytes, bytes]] = {}
        self.quit_requested = False

    def receive(self, data: bytes) -> bytes:
        output = bytearray()
        for frame in self.decoder.feed(data):
            if frame.frame_type != FrameType.REQUEST:
                continue
            if frame.transaction in self.replays:
                original, encoded_response = self.replays[frame.transaction]
                if original != frame.payload:
                    command = (
                        Command(frame.payload[0]) if frame.payload else Command.PING
                    )
                    response = Frame(
                        FrameType.RESPONSE,
                        frame.transaction,
                        payload=response_payload(
                            command,
                            Status.BAD_REQUEST,
                            tlv_text(
                                Tag.MESSAGE,
                                "transaction ID reused for different request",
                            ),
                        ),
                    ).encode()
                    output.extend(response)
                    continue
                cached = Frame.decode(encoded_response)
                output.extend(
                    Frame(
                        cached.frame_type,
                        cached.transaction,
                        cached.sequence,
                        cached.flags | Flag.REPLAY,
                        cached.payload,
                    ).encode()
                )
                continue
            try:
                command, fields = parse_request(frame.payload)
                status, response_fields = self._dispatch(command, fields)
            except (ProtocolError, UnicodeError, ValueError) as exc:
                command = Command.PING
                status, response_fields = (
                    Status.BAD_REQUEST,
                    [tlv_text(Tag.MESSAGE, str(exc))],
                )
            response = Frame(
                FrameType.RESPONSE,
                frame.transaction,
                payload=response_payload(command, status, *response_fields),
            ).encode()
            self.replays[frame.transaction] = (frame.payload, response)
            while len(self.replays) > self.replay_entries:
                self.replays.popitem(last=False)
            output.extend(response)
        return bytes(output)

    def _path(self, fields: dict[int, list[bytes]]) -> Path:
        name = first(fields, Tag.PATH).decode("ascii")
        if (
            not name
            or name in (".", "..")
            or "/" in name
            or "\\" in name
            or ":" in name
            or "*" in name
            or "?" in name
        ):
            raise PermissionError("path must be one workspace filename")
        if len(name) > 12 or name.startswith("."):
            raise PermissionError("path is not a DOS 8.3 filename")
        stem, dot, extension = name.partition(".")
        allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$~!#%&-{}()@'`"
        if not (1 <= len(stem) <= 8 and len(extension) <= 3 and (not dot or extension)):
            raise PermissionError("path is not a DOS 8.3 filename")
        upper = name.upper()
        if any(character not in allowed + "." for character in upper):
            raise PermissionError("unsupported filename character")
        reserved = {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
        reserved.update(f"COM{number}" for number in range(1, 10))
        reserved.update(f"LPT{number}" for number in range(1, 10))
        if stem.upper() in reserved:
            raise PermissionError("DOS device names are not workspace files")
        return self.root / upper

    def _dispatch(
        self, command: Command, fields: dict[int, list[bytes]]
    ) -> tuple[Status, list[bytes]]:
        try:
            if command == Command.PING:
                return Status.OK, [tlv_text(Tag.MESSAGE, "PONG")]
            if command == Command.INFO:
                info = {
                    "agent": "reference",
                    "version": "0.1.0",
                    "protocol": 1,
                    "workspace": str(self.root),
                    "free_disk": shutil.disk_usage(self.root).free,
                    "capabilities": ["replay", "resume", "exec-capture"],
                    "chunk_size": 512,
                }
                return Status.OK, [
                    tlv_text(
                        Tag.JSON,
                        json.dumps(info, sort_keys=True, separators=(",", ":")),
                    )
                ]
            if command == Command.LIST:
                listing = [
                    {"name": item.name, "size": item.stat().st_size}
                    for item in sorted(self.root.iterdir())
                    if item.is_file()
                    and not item.name.endswith((".PART", ".META"))
                    and item.name != "UPDATE.PND"
                ]
                return Status.OK, [
                    tlv_text(Tag.JSON, json.dumps(listing, separators=(",", ":")))
                ]
            if command == Command.PUT_BEGIN:
                path = self._path(fields)
                size = as_u32(first(fields, Tag.SIZE))
                expected = as_u32(first(fields, Tag.CRC32))
                part = path.with_name(path.name + ".PART")
                meta = path.with_name(path.name + ".META")
                identity = f"{size}:{expected:08x}"
                if meta.exists() and meta.read_text("ascii") != identity:
                    part.unlink(missing_ok=True)
                meta.write_text(identity, "ascii")
                offset = part.stat().st_size if part.exists() else 0
                if offset > size:
                    part.unlink()
                    offset = 0
                return Status.OK, [tlv_u32(Tag.OFFSET, offset)]
            if command == Command.PUT_DATA:
                path = self._path(fields)
                offset = as_u32(first(fields, Tag.OFFSET))
                data = first(fields, Tag.DATA)
                part = path.with_name(path.name + ".PART")
                actual = part.stat().st_size if part.exists() else 0
                if actual != offset:
                    return Status.OFFSET_MISMATCH, [tlv_u32(Tag.OFFSET, actual)]
                with part.open("ab") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                return Status.OK, [tlv_u32(Tag.OFFSET, offset + len(data))]
            if command == Command.PUT_COMMIT:
                path = self._path(fields)
                size = as_u32(first(fields, Tag.SIZE))
                expected = as_u32(first(fields, Tag.CRC32))
                part = path.with_name(path.name + ".PART")
                if not part.exists():
                    return Status.NOT_FOUND, []
                data = part.read_bytes()
                actual = file_crc32(data)
                if len(data) != size or actual != expected:
                    return Status.CRC_MISMATCH, [
                        tlv_u32(Tag.SIZE, len(data)),
                        tlv_u32(Tag.CRC32, actual),
                    ]
                part.replace(path)
                path.with_name(path.name + ".META").unlink(missing_ok=True)
                return Status.OK, [tlv_u32(Tag.SIZE, size), tlv_u32(Tag.CRC32, actual)]
            if command in (Command.GET, Command.CRC):
                path = self._path(fields)
                if not path.is_file():
                    return Status.NOT_FOUND, []
                data = path.read_bytes()
                common = [
                    tlv_u32(Tag.SIZE, len(data)),
                    tlv_u32(Tag.CRC32, file_crc32(data)),
                ]
                if command == Command.CRC:
                    return Status.OK, common
                offset = as_u32(first(fields, Tag.OFFSET))
                chunk_size = min(as_u32(first(fields, Tag.CHUNK_SIZE)), 1024)
                if offset > len(data):
                    return Status.OFFSET_MISMATCH, [tlv_u32(Tag.OFFSET, len(data))]
                return Status.OK, common + [
                    tlv_u32(Tag.OFFSET, offset),
                    tlv(Tag.DATA, data[offset : offset + chunk_size]),
                ]
            if command == Command.REMOVE:
                path = self._path(fields)
                if not path.is_file():
                    return Status.NOT_FOUND, []
                path.unlink()
                return Status.OK, []
            if command == Command.EXEC:
                exec_id = as_u32(first(fields, Tag.EXEC_ID))
                if exec_id in self.executions:
                    original, payload = self.executions[exec_id]
                    if original != self._execution_identity(fields):
                        return Status.BAD_REQUEST, [
                            tlv_text(
                                Tag.MESSAGE, "execution ID reused for different command"
                            )
                        ]
                    _, status, values = self._unpack_cached(command, payload)
                    return status, values
                program = self._path(fields)
                if not program.is_file():
                    return Status.NOT_FOUND, []
                args = first(fields, Tag.ARGS, b"").decode("ascii")
                stdout_name = f"O{exec_id & 0xFFFFFF:06X}.OUT"
                stderr_name = f"E{exec_id & 0xFFFFFF:06X}.ERR"
                started = time.monotonic()
                result = subprocess.run(
                    [str(program), *args.split()],
                    cwd=self.root,
                    capture_output=True,
                    check=False,
                    timeout=60,
                )
                elapsed = round((time.monotonic() - started) * 1000)
                (self.root / stdout_name).write_bytes(result.stdout)
                (self.root / stderr_name).write_bytes(result.stderr)
                response_fields = [
                    tlv_u32(Tag.EXEC_ID, exec_id),
                    tlv_u32(Tag.EXIT_CODE, result.returncode & 0xFFFF),
                    tlv_text(Tag.STDOUT, stdout_name),
                    tlv_text(Tag.STDERR, stderr_name),
                    tlv_u32(Tag.ELAPSED_MS, elapsed),
                ]
                self.executions[exec_id] = (
                    self._execution_identity(fields),
                    response_payload(command, Status.OK, *response_fields),
                )
                return Status.OK, response_fields
            if command == Command.UPDATE:
                path = self._path(fields)
                if path.name != "DOSRAVI.NEW" or not path.is_file():
                    return Status.DENIED, [
                        tlv_text(Tag.MESSAGE, "fixed DOSRAVI.NEW staging file required")
                    ]
                data = path.read_bytes()
                if len(data) != as_u32(first(fields, Tag.SIZE)) or file_crc32(
                    data
                ) != as_u32(first(fields, Tag.CRC32)):
                    return Status.CRC_MISMATCH, []
                current = self.root / "DOSRAVI.COM"
                fallback = self.root / "DOSRAVI.OLD"
                fallback.unlink(missing_ok=True)
                if current.exists():
                    current.replace(fallback)
                path.replace(current)
                (self.root / "UPDATE.PND").write_text("pending\n", encoding="ascii")
                return Status.OK, []
            if command == Command.UPDATE_CONFIRM:
                (self.root / "UPDATE.PND").unlink(missing_ok=True)
                return Status.OK, []
            if command == Command.UPDATE_ROLLBACK:
                current = self.root / "DOSRAVI.COM"
                fallback = self.root / "DOSRAVI.OLD"
                if not fallback.exists():
                    return Status.NOT_FOUND, []
                (self.root / "DOSRAVI.BAD").unlink(missing_ok=True)
                if current.exists():
                    current.replace(self.root / "DOSRAVI.BAD")
                fallback.replace(current)
                (self.root / "UPDATE.PND").unlink(missing_ok=True)
                return Status.OK, []
            if command == Command.QUIT:
                self.quit_requested = True
                return Status.OK, []
            return Status.UNSUPPORTED, []
        except PermissionError as exc:
            return Status.DENIED, [tlv_text(Tag.MESSAGE, str(exc))]
        except OSError as exc:
            return Status.IO_ERROR, [tlv_text(Tag.MESSAGE, str(exc))]
        except subprocess.TimeoutExpired:
            return Status.BUSY, [
                tlv_text(Tag.MESSAGE, "child timed out in reference agent")
            ]

    @staticmethod
    def _unpack_cached(
        command: Command, payload: bytes
    ) -> tuple[Command, Status, dict[int, list[bytes]]]:
        from .protocol import parse_response

        return parse_response(payload)

    @staticmethod
    def _execution_identity(fields: dict[int, list[bytes]]) -> bytes:
        return first(fields, Tag.PATH) + b"\0" + first(fields, Tag.ARGS, b"")

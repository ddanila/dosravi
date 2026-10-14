"""High-level replay-safe DOSRAVI client."""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .protocol import (
    Command,
    Frame,
    FrameDecoder,
    FrameType,
    Status,
    Tag,
    as_u32,
    file_crc32,
    first,
    parse_response,
    request_payload,
    tlv,
    tlv_text,
    tlv_u32,
)
from .transport import Transport, TransportError


class RemoteError(RuntimeError):
    def __init__(
        self,
        command: Command,
        status: Status,
        message: str = "",
        values: dict[int, list[bytes]] | None = None,
    ):
        self.command = command
        self.status = status
        self.values = values or {}
        super().__init__(
            f"{command.name}: {status.name}{': ' + message if message else ''}"
        )


@dataclass(frozen=True)
class TransferStats:
    bytes: int
    elapsed: float
    crc32: int

    @property
    def bytes_per_second(self) -> float:
        return self.bytes / self.elapsed if self.elapsed else float("inf")


@dataclass(frozen=True)
class ExecResult:
    execution_id: int
    exit_code: int
    stdout_path: str
    stderr_path: str
    elapsed_ms: int


class Client:
    def __init__(
        self,
        transport: Transport,
        timeout: float = 1.0,
        retries: int = 5,
        event: Callable[[dict[str, object]], None] | None = None,
        exec_timeout: float = 300.0,
    ):
        self.transport = transport
        self.timeout = timeout
        self.retries = retries
        self.decoder = FrameDecoder()
        self.next_transaction = secrets.randbits(32) or 1
        self.event = event or (lambda _: None)
        self.exec_timeout = exec_timeout

    def close(self) -> None:
        self.transport.close()

    def _transaction(self) -> int:
        result = self.next_transaction
        self.next_transaction = (result + 1) & 0xFFFFFFFF or 1
        return result

    def request(
        self, command: Command, *fields: bytes, transaction: int | None = None
    ) -> dict[int, list[bytes]]:
        txid = transaction if transaction is not None else self._transaction()
        frame = Frame(
            FrameType.REQUEST, txid, payload=request_payload(command, *fields)
        )
        encoded = frame.encode()
        started = False
        for attempt in range(self.retries + 1):
            self.event(
                {
                    "direction": "tx",
                    "transaction": txid,
                    "command": command.name,
                    "attempt": attempt,
                }
            )
            self.transport.write(encoded)
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                data = self.transport.read(1024, deadline - time.monotonic())
                if not data:
                    continue
                for received in self.decoder.feed(data):
                    if (
                        received.frame_type == FrameType.EVENT
                        and received.transaction == txid
                    ):
                        event_command, event_status, event_values = parse_response(
                            received.payload
                        )
                        message = first(event_values, Tag.MESSAGE, b"").decode(
                            "utf-8", "replace"
                        )
                        self.event(
                            {
                                "direction": "event",
                                "transaction": txid,
                                "command": event_command.name,
                                "status": event_status.name,
                                "message": message,
                            }
                        )
                        if (
                            command == Command.EXEC
                            and event_command == Command.EXEC
                            and event_status == Status.OK
                            and message == "STARTED"
                            and not started
                        ):
                            started = True
                            deadline = time.monotonic() + self.exec_timeout
                        continue
                    if (
                        received.frame_type != FrameType.RESPONSE
                        or received.transaction != txid
                    ):
                        continue
                    response_command, status, values = parse_response(received.payload)
                    if response_command != command:
                        continue
                    self.event(
                        {
                            "direction": "rx",
                            "transaction": txid,
                            "command": command.name,
                            "status": status.name,
                            "replay": bool(received.flags & 2),
                        }
                    )
                    if status != Status.OK:
                        message = first(values, Tag.MESSAGE, b"").decode(
                            "utf-8", "replace"
                        )
                        raise RemoteError(command, status, message, values)
                    return values
            if started:
                raise TransportError(
                    "EXEC completion timed out after STARTED; outcome unknown; "
                    "request was not retransmitted"
                )
        raise TransportError(
            f"{command.name} timed out after {self.retries + 1} attempts"
        )

    def ping(self) -> str:
        values = self.request(Command.PING)
        return first(values, Tag.MESSAGE, b"PONG").decode("ascii", "replace")

    def info(self) -> dict[str, object]:
        values = self.request(Command.INFO)
        return json.loads(first(values, Tag.JSON))

    def list(self) -> list[dict[str, object]]:
        listing: list[dict[str, object]] = []
        offset = 0
        while True:
            values = self.request(Command.LIST, tlv_u32(Tag.OFFSET, offset))
            page = json.loads(first(values, Tag.JSON))
            if not isinstance(page, list):
                raise RemoteError(Command.LIST, Status.INTERNAL, "LIST is not an array")
            listing.extend(page)
            next_values = values.get(int(Tag.OFFSET))
            if not next_values:
                return listing
            next_offset = as_u32(next_values[0])
            if next_offset <= offset:
                raise RemoteError(
                    Command.LIST, Status.OFFSET_MISMATCH, "LIST did not advance"
                )
            offset = next_offset

    def crc(self, remote: str) -> tuple[int, int]:
        values = self.request(Command.CRC, tlv_text(Tag.PATH, remote))
        return as_u32(first(values, Tag.SIZE)), as_u32(first(values, Tag.CRC32))

    def remove(self, remote: str) -> None:
        self.request(Command.REMOVE, tlv_text(Tag.PATH, remote))

    def put(
        self, local: str | Path, remote: str, chunk_size: int = 512
    ) -> TransferStats:
        data = Path(local).read_bytes()
        expected = file_crc32(data)
        begin = self.request(
            Command.PUT_BEGIN,
            tlv_text(Tag.PATH, remote),
            tlv_u32(Tag.SIZE, len(data)),
            tlv_u32(Tag.CRC32, expected),
        )
        offset = as_u32(first(begin, Tag.OFFSET, b"\x00\x00\x00\x00"))
        if offset > len(data):
            raise RemoteError(
                Command.PUT_BEGIN, Status.OFFSET_MISMATCH, "remote offset exceeds input"
            )
        started = time.monotonic()
        while offset < len(data):
            chunk = data[offset : offset + chunk_size]
            try:
                values = self.request(
                    Command.PUT_DATA,
                    tlv_text(Tag.PATH, remote),
                    tlv_u32(Tag.OFFSET, offset),
                    tlv(Tag.DATA, chunk),
                )
            except RemoteError as exc:
                if exc.status != Status.OFFSET_MISMATCH:
                    raise
                remote_offset = as_u32(first(exc.values, Tag.OFFSET))
                if remote_offset > len(data):
                    raise RemoteError(
                        Command.PUT_DATA,
                        Status.OFFSET_MISMATCH,
                        "remote offset exceeds input",
                    ) from exc
                if remote_offset <= offset:
                    raise RemoteError(
                        Command.PUT_DATA,
                        Status.IO_ERROR,
                        "remote upload made no progress",
                    ) from exc
                offset = remote_offset
                continue
            new_offset = as_u32(first(values, Tag.OFFSET))
            if new_offset != offset + len(chunk):
                raise RemoteError(
                    Command.PUT_DATA,
                    Status.OFFSET_MISMATCH,
                    "unexpected acknowledgement",
                )
            offset = new_offset
        values = self.request(
            Command.PUT_COMMIT,
            tlv_text(Tag.PATH, remote),
            tlv_u32(Tag.SIZE, len(data)),
            tlv_u32(Tag.CRC32, expected),
        )
        actual = as_u32(first(values, Tag.CRC32))
        if actual != expected:
            raise RemoteError(Command.PUT_COMMIT, Status.CRC_MISMATCH)
        return TransferStats(len(data), time.monotonic() - started, actual)

    def get(
        self, remote: str, local: str | Path, chunk_size: int = 512
    ) -> TransferStats:
        destination = Path(local)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".part")
        started = time.monotonic()
        for restart in range(2):
            offset = temporary.stat().st_size if temporary.exists() else 0
            crc = 0
            if offset:
                with temporary.open("rb") as stream:
                    while chunk := stream.read(65536):
                        crc = file_crc32(chunk, crc)
            size: int | None = None
            expected: int | None = None
            try:
                with temporary.open("ab") as stream:
                    while size is None or offset < size:
                        values = self.request(
                            Command.GET,
                            tlv_text(Tag.PATH, remote),
                            tlv_u32(Tag.OFFSET, offset),
                            tlv_u32(Tag.CHUNK_SIZE, chunk_size),
                        )
                        size = as_u32(first(values, Tag.SIZE))
                        expected = as_u32(first(values, Tag.CRC32))
                        response_offset = as_u32(first(values, Tag.OFFSET))
                        chunk = first(values, Tag.DATA, b"")
                        if response_offset != offset or offset + len(chunk) > size:
                            raise RemoteError(Command.GET, Status.OFFSET_MISMATCH)
                        if not chunk and offset < size:
                            raise RemoteError(
                                Command.GET, Status.IO_ERROR, "empty non-final chunk"
                            )
                        stream.write(chunk)
                        stream.flush()
                        crc = file_crc32(chunk, crc)
                        offset += len(chunk)
            except RemoteError as exc:
                if exc.status != Status.OFFSET_MISMATCH or restart:
                    raise
            else:
                if (
                    expected is not None
                    and size is not None
                    and offset == size
                    and crc == expected
                    and self.crc(remote) == (size, expected)
                ):
                    temporary.replace(destination)
                    return TransferStats(size, time.monotonic() - started, crc)
            if restart == 0:
                temporary.unlink(missing_ok=True)
                continue
            raise RemoteError(
                Command.GET,
                Status.CRC_MISMATCH,
                "download did not match a stable remote file",
            )

    def execute(
        self,
        program: str,
        args: str = "",
        execution_id: int | None = None,
        stdin_path: str | None = None,
    ) -> ExecResult:
        if "." not in program and 1 <= len(program) <= 8:
            program += ".COM"
        exec_id = execution_id if execution_id is not None else secrets.randbits(32)
        fields = [
            tlv_text(Tag.PATH, program),
            tlv_text(Tag.ARGS, args),
            tlv_u32(Tag.EXEC_ID, exec_id),
        ]
        if stdin_path is not None:
            fields.append(tlv_text(Tag.STDIN, stdin_path))
        values = self.request(Command.EXEC, *fields)
        return ExecResult(
            execution_id=exec_id,
            exit_code=as_u32(first(values, Tag.EXIT_CODE)),
            stdout_path=first(values, Tag.STDOUT).decode("ascii"),
            stderr_path=first(values, Tag.STDERR).decode("ascii"),
            elapsed_ms=as_u32(first(values, Tag.ELAPSED_MS)),
        )

    def quit(self) -> None:
        self.request(Command.QUIT)

    def stage_update(self, remote: str, size: int, crc32: int) -> None:
        self.request(
            Command.UPDATE,
            tlv_text(Tag.PATH, remote),
            tlv_u32(Tag.SIZE, size),
            tlv_u32(Tag.CRC32, crc32),
        )

    def confirm_update(self) -> None:
        self.request(Command.UPDATE_CONFIRM)

    def rollback_update(self) -> None:
        self.request(Command.UPDATE_ROLLBACK)

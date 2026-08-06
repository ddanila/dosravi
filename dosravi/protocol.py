"""DOSRAVI v0.1 framing and command encoding.

This module deliberately has no serial or POSIX dependencies.  Integer fields
are little-endian, as documented in docs/protocol.md.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum

VERSION = 1
MAX_PAYLOAD = 4096
MAX_ENCODED_FRAME = 4608
HEADER = struct.Struct("<BBBBIIH")


class ProtocolError(ValueError):
    pass


class FrameType(IntEnum):
    REQUEST = 1
    RESPONSE = 2
    EVENT = 3


class Flag(IntEnum):
    MORE = 1
    REPLAY = 2


class Command(IntEnum):
    PING = 1
    INFO = 2
    LIST = 3
    PUT_BEGIN = 4
    PUT_DATA = 5
    PUT_COMMIT = 6
    GET = 7
    CRC = 8
    REMOVE = 9
    EXEC = 10
    EXEC_RESULT = 11
    QUIT = 12
    UPDATE = 13
    UPDATE_CONFIRM = 14
    UPDATE_ROLLBACK = 15


class Status(IntEnum):
    OK = 0
    BAD_REQUEST = 1
    NOT_FOUND = 2
    DENIED = 3
    IO_ERROR = 4
    CRC_MISMATCH = 5
    OFFSET_MISMATCH = 6
    BUSY = 7
    UNSUPPORTED = 8
    INTERNAL = 9


class Tag(IntEnum):
    PATH = 1
    OFFSET = 2
    SIZE = 3
    CRC32 = 4
    DATA = 5
    ARGS = 6
    EXEC_ID = 7
    EXIT_CODE = 8
    STDOUT = 9
    STDERR = 10
    JSON = 11
    MESSAGE = 12
    CHUNK_SIZE = 13
    ELAPSED_MS = 14
    ARTIFACT = 15


def crc16_ccitt(data: bytes, initial: int = 0xFFFF) -> int:
    crc = initial
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = (
                ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
            )
    return crc


def file_crc32(data: bytes, initial: int = 0) -> int:
    return zlib.crc32(data, initial) & 0xFFFFFFFF


def cobs_encode(data: bytes) -> bytes:
    out = bytearray(b"\x00")
    code_at = 0
    code = 1
    for byte in data:
        if byte == 0:
            out[code_at] = code
            code_at = len(out)
            out.append(0)
            code = 1
        else:
            out.append(byte)
            code += 1
            if code == 0xFF:
                out[code_at] = code
                code_at = len(out)
                out.append(0)
                code = 1
    out[code_at] = code
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    if not data:
        raise ProtocolError("empty COBS frame")
    out = bytearray()
    index = 0
    while index < len(data):
        code = data[index]
        if code == 0:
            raise ProtocolError("zero byte inside COBS frame")
        index += 1
        end = index + code - 1
        if end > len(data):
            raise ProtocolError("truncated COBS block")
        out.extend(data[index:end])
        index = end
        if code != 0xFF and index < len(data):
            out.append(0)
    return bytes(out)


@dataclass(frozen=True)
class Frame:
    frame_type: FrameType
    transaction: int
    sequence: int = 0
    flags: int = 0
    payload: bytes = b""
    version: int = VERSION

    def encode(self) -> bytes:
        if len(self.payload) > MAX_PAYLOAD:
            raise ProtocolError("payload too large")
        header = HEADER.pack(
            self.version,
            int(self.frame_type),
            self.flags,
            0,
            self.transaction & 0xFFFFFFFF,
            self.sequence & 0xFFFFFFFF,
            len(self.payload),
        )
        raw = header + self.payload
        raw += struct.pack("<H", crc16_ccitt(raw))
        return cobs_encode(raw) + b"\x00"

    @classmethod
    def decode(cls, encoded: bytes) -> Frame:
        if encoded.endswith(b"\x00"):
            encoded = encoded[:-1]
        raw = cobs_decode(encoded)
        if len(raw) < HEADER.size + 2:
            raise ProtocolError("frame shorter than header")
        body, crc_bytes = raw[:-2], raw[-2:]
        expected = struct.unpack("<H", crc_bytes)[0]
        if crc16_ccitt(body) != expected:
            raise ProtocolError("frame CRC mismatch")
        version, type_value, flags, reserved, transaction, sequence, length = (
            HEADER.unpack_from(body)
        )
        if version != VERSION:
            raise ProtocolError(f"unsupported protocol version {version}")
        if reserved != 0:
            raise ProtocolError("reserved header byte is nonzero")
        payload = body[HEADER.size :]
        if length != len(payload) or length > MAX_PAYLOAD:
            raise ProtocolError("invalid payload length")
        try:
            frame_type = FrameType(type_value)
        except ValueError as exc:
            raise ProtocolError(f"unknown frame type {type_value}") from exc
        return cls(frame_type, transaction, sequence, flags, payload, version)


class FrameDecoder:
    """Bounded streaming decoder which resynchronizes at the next delimiter."""

    def __init__(self, max_encoded: int = MAX_ENCODED_FRAME):
        self.max_encoded = max_encoded
        self.buffer = bytearray()
        self.discarding = False

    def feed(self, data: bytes) -> list[Frame]:
        frames: list[Frame] = []
        for byte in data:
            if byte == 0:
                if self.discarding:
                    self.discarding = False
                    self.buffer.clear()
                    continue
                if self.buffer:
                    candidate = bytes(self.buffer)
                    self.buffer.clear()
                    try:
                        frames.append(Frame.decode(candidate))
                    except ProtocolError:
                        pass
                continue
            if self.discarding:
                continue
            self.buffer.append(byte)
            if len(self.buffer) > self.max_encoded:
                self.buffer.clear()
                self.discarding = True
        return frames


def tlv(tag: Tag | int, value: bytes) -> bytes:
    if len(value) > 0xFFFF:
        raise ProtocolError("TLV value too large")
    return struct.pack("<BH", int(tag), len(value)) + value


def tlv_u32(tag: Tag | int, value: int) -> bytes:
    return tlv(tag, struct.pack("<I", value & 0xFFFFFFFF))


def tlv_text(tag: Tag | int, value: str) -> bytes:
    return tlv(tag, value.encode("utf-8"))


def parse_tlvs(data: bytes) -> dict[int, list[bytes]]:
    values: dict[int, list[bytes]] = {}
    offset = 0
    while offset < len(data):
        if len(data) - offset < 3:
            raise ProtocolError("truncated TLV header")
        tag, length = struct.unpack_from("<BH", data, offset)
        offset += 3
        end = offset + length
        if end > len(data):
            raise ProtocolError("truncated TLV value")
        values.setdefault(tag, []).append(data[offset:end])
        offset = end
    return values


def first(
    values: dict[int, list[bytes]], tag: Tag, default: bytes | None = None
) -> bytes:
    found = values.get(int(tag))
    if found:
        return found[0]
    if default is not None:
        return default
    raise ProtocolError(f"missing required TLV {tag.name}")


def as_u32(value: bytes) -> int:
    if len(value) != 4:
        raise ProtocolError("integer TLV is not four bytes")
    return struct.unpack("<I", value)[0]


def request_payload(command: Command, *fields: bytes) -> bytes:
    return bytes((int(command),)) + b"".join(fields)


def response_payload(command: Command, status: Status, *fields: bytes) -> bytes:
    return bytes((int(command), int(status))) + b"".join(fields)


def parse_request(payload: bytes) -> tuple[Command, dict[int, list[bytes]]]:
    if not payload:
        raise ProtocolError("empty request")
    try:
        command = Command(payload[0])
    except ValueError as exc:
        raise ProtocolError("unknown command") from exc
    return command, parse_tlvs(payload[1:])


def parse_response(payload: bytes) -> tuple[Command, Status, dict[int, list[bytes]]]:
    if len(payload) < 2:
        raise ProtocolError("short response")
    try:
        command = Command(payload[0])
        status = Status(payload[1])
    except ValueError as exc:
        raise ProtocolError("unknown response code") from exc
    return command, status, parse_tlvs(payload[2:])

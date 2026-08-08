from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

from dosravi.client import Client, RemoteError
from dosravi.protocol import (
    Command,
    Status,
    Tag,
    file_crc32,
    tlv,
    tlv_text,
    tlv_u32,
)
from dosravi.transport import Transport


class ConnectedSocketTransport(Transport):
    def __init__(self, connection: socket.socket):
        self.connection = connection

    def write(self, data: bytes) -> None:
        self.connection.sendall(data)

    def read(self, size: int, timeout: float) -> bytes:
        self.connection.settimeout(max(timeout, 0.0))
        try:
            return self.connection.recv(size)
        except TimeoutError:
            return b""

    def close(self) -> None:
        self.connection.close()


class WrappedTransport(Transport):
    def __init__(self, transport: Transport):
        self.transport = transport

    def write(self, data: bytes) -> None:
        self.transport.write(data)

    def read(self, size: int, timeout: float) -> bytes:
        return self.transport.read(size, timeout)

    def close(self) -> None:
        self.transport.close()


class CorruptFirstWriteTransport(WrappedTransport):
    def __init__(self, transport: Transport):
        super().__init__(transport)
        self.pending = True

    def write(self, data: bytes) -> None:
        if self.pending:
            self.pending = False
            damaged = bytearray(data)
            index = next(
                index
                for index, value in enumerate(damaged[:-1])
                if value not in (0, 0x80)
            )
            damaged[index] ^= 0x80
            data = bytes(damaged)
        super().write(data)


class DuplicateFirstWriteTransport(WrappedTransport):
    def __init__(self, transport: Transport):
        super().__init__(transport)
        self.pending = True

    def write(self, data: bytes) -> None:
        super().write(data)
        if self.pending:
            self.pending = False
            super().write(data)


class DropFirstResponseTransport(WrappedTransport):
    def __init__(self, transport: Transport):
        super().__init__(transport)
        self.dropping = True

    def read(self, size: int, timeout: float) -> bytes:
        while self.dropping:
            data = super().read(size, timeout)
            if not data:
                return b""
            delimiter = data.find(b"\0")
            if delimiter >= 0:
                self.dropping = False
                return data[delimiter + 1 :]
        return super().read(size, timeout)


class DelayFirstReadTransport(WrappedTransport):
    def __init__(self, transport: Transport):
        super().__init__(transport)
        self.pending = True

    def read(self, size: int, timeout: float) -> bytes:
        if self.pending:
            self.pending = False
            time.sleep(min(0.1, timeout / 2))
        return super().read(size, timeout)


class CountingTransport(WrappedTransport):
    def __init__(self, transport: Transport):
        super().__init__(transport)
        self.writes = 0

    def write(self, data: bytes) -> None:
        self.writes += 1
        super().write(data)


class HostServer:
    def __init__(self, port: int):
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", port))
        self.listener.listen(1)

    def connect(self, timeout: float = 20.0) -> Client:
        self.listener.settimeout(timeout)
        connection, _ = self.listener.accept()
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return Client(ConnectedSocketTransport(connection), timeout=2.0, retries=5)

    def close(self) -> None:
        self.listener.close()


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: dosbox_integration.py PORT WORK")
    port = int(sys.argv[1])
    work = Path(sys.argv[2])
    server = HostServer(port)
    (work / "LISTEN.FLG").write_text("ready\n", encoding="ascii")
    source = work / "HOST.BIN"
    source.write_bytes(bytes(range(256)) * 13)
    large_source = work / "HOST64.BIN"
    large_source.write_bytes(bytes(range(256)) * 256)
    stdin_source = work / "HOST.TXT"
    stdin_source.write_bytes(b"remote input\r\n")

    # DOSBox opens its TCP listener before AUTOEXEC reaches the agent.  An
    # eager connection sees DTR low and consumes that listener.  The emulator
    # harness writes a marker immediately before invoking DOSRAVI.
    ready_deadline = time.monotonic() + 20.0
    while not (work / "READY.FLG").exists() and time.monotonic() < ready_deadline:
        time.sleep(0.05)
    if not (work / "READY.FLG").exists():
        raise RuntimeError("DOSBox-X did not reach the agent launch point")
    time.sleep(1.5)
    client = server.connect()
    assert client.ping() == "PONG"
    info = client.info()
    assert info["protocol"] == 1
    assert info["agent"] == "DOSRAVI.COM"
    assert info["conventional_kb"] >= 128
    assert isinstance(info["bios_equipment_word"], int)
    # Reuse the same transaction to exercise encoded response replay.
    assert client.request(Command.PING, transaction=0x12345678)
    assert client.request(Command.PING, transaction=0x12345678)
    try:
        client.request(Command.INFO, transaction=0x12345678)
    except RemoteError as exc:
        assert exc.status == Status.BAD_REQUEST
    else:
        raise AssertionError("transaction ID accepted different request bytes")

    # Promote a distinctly versioned build through the real two-phase DOS
    # path. The INFO assertion proves the replacement, rather than the old
    # process, answered before confirmation.
    original_agent = (work / "DOSRAVI.COM").read_bytes()
    replacement_agent = (work / "DOSNEXT.COM").read_bytes()
    assert original_agent != replacement_agent
    update_stats = client.put(work / "DOSNEXT.COM", "DOSRAVI.NEW")
    client.stage_update("DOSRAVI.NEW", update_stats.bytes, update_stats.crc32)
    assert client.ping() == "PONG"
    replacement_info = client.info()
    assert replacement_info["agent"] == "DOSRAVI.COM"
    assert replacement_info["version"] == "0.1.2-test"
    assert (work / "DOSRAVI.OLD").exists()
    assert (work / "UPDATE.PND").exists()
    assert (work / "DOSRAVI.OLD").read_bytes() == original_agent
    assert (work / "DOSRAVI.COM").read_bytes() == replacement_agent

    # A connected host can roll back immediately; status 85 must make the
    # launcher invoke the restored old agent in the same DOS session.
    client.rollback_update()
    assert client.ping() == "PONG"
    assert client.info()["version"] == "0.1.1"
    assert not (work / "UPDATE.PND").exists()
    assert (work / "DOSRAVI.COM").read_bytes() == original_agent
    assert (work / "DOSRAVI.BAD").read_bytes() == replacement_agent

    # Stage once more and confirm only after the distinct replacement answers.
    update_stats = client.put(work / "DOSNEXT.COM", "DOSRAVI.NEW")
    client.stage_update("DOSRAVI.NEW", update_stats.bytes, update_stats.crc32)
    assert client.ping() == "PONG"
    assert client.info()["version"] == "0.1.2-test"
    client.confirm_update()
    assert not (work / "UPDATE.PND").exists()
    assert (work / "DOSRAVI.OLD").read_bytes() == original_agent

    # Exercise retry/resynchronization against the actual 8086 decoder and
    # transaction cache, not only the Python reference agent.
    client = Client(
        CorruptFirstWriteTransport(client.transport), timeout=0.15, retries=3
    )
    assert client.ping() == "PONG"
    client = Client(
        DropFirstResponseTransport(client.transport), timeout=0.15, retries=3
    )
    assert client.ping() == "PONG"
    client = Client(
        DuplicateFirstWriteTransport(client.transport), timeout=0.5, retries=3
    )
    assert client.ping() == "PONG"
    client = Client(DelayFirstReadTransport(client.transport), timeout=0.5, retries=3)
    assert client.ping() == "PONG"

    source_data = source.read_bytes()
    client.request(
        Command.PUT_BEGIN,
        tlv_text(Tag.PATH, "INPUT.BIN"),
        tlv_u32(Tag.SIZE, len(source_data)),
        tlv_u32(Tag.CRC32, file_crc32(source_data)),
    )
    client.request(
        Command.PUT_DATA,
        tlv_text(Tag.PATH, "INPUT.BIN"),
        tlv_u32(Tag.OFFSET, 0),
        tlv(Tag.DATA, source_data[:512]),
    )
    # Lose all host transaction state between chunks; PUT_BEGIN must discover
    # and resume the committed temporary offset.
    client = Client(client.transport, timeout=2.0, retries=5)
    client.put(source, "INPUT.BIN")
    client.put(work / "HELLO.COM", "HELLO.COM")
    client.put(work / "SLOW.COM", "SLOW.COM")
    client.put(work / "STDIN.COM", "STDIN.COM")
    client.put(stdin_source, "CHILD.IN")
    size, _ = client.crc("INPUT.BIN")
    assert size == source.stat().st_size

    # GET/CRC may retain one verified identity so the 8086 does not rescan a
    # complete file before every download chunk. Any mutation must invalidate
    # that identity before a later request can observe it.
    client.put(source, "CACHE.BIN")
    assert client.crc("CACHE.BIN") == (
        len(source_data),
        file_crc32(source_data),
    )
    replacement_data = stdin_source.read_bytes()
    client.put(stdin_source, "CACHE.BIN")
    assert client.crc("CACHE.BIN") == (
        len(replacement_data),
        file_crc32(replacement_data),
    )
    client.remove("CACHE.BIN")
    try:
        client.crc("CACHE.BIN")
    except RemoteError as exc:
        assert exc.status == Status.NOT_FOUND
    else:
        raise AssertionError("removed file retained a cached identity")

    # Cross the 32 KiB boundary where the DOS C runtime's ftell is signed.
    # The agent uses DOS's 32-bit seek position for resumable transfers.
    large_data = large_source.read_bytes()
    client.put(large_source, "LARGE.BIN")
    assert client.crc("LARGE.BIN") == (
        len(large_data),
        file_crc32(large_data),
    )
    large_result = work / "LARGE.OUT"
    client.get("LARGE.BIN", large_result)
    assert large_result.read_bytes() == large_data
    client.remove("LARGE.BIN")
    listing = {entry["name"] for entry in client.list()}
    assert {"INPUT.BIN", "HELLO.COM", "DOSRAVI.COM", "DOSRAVI.OLD"} <= listing

    for operation in (
        lambda: client.put(source, "DOSRAVI.COM"),
        lambda: client.remove("DOSRAVI.OLD"),
    ):
        try:
            operation()
        except RemoteError as exc:
            assert exc.status == Status.DENIED
        else:
            raise AssertionError("agent control file mutation was accepted")

    # STARTED extends only the EXEC completion wait. The slow child exceeds
    # the ordinary frame timeout, yet its request must be transmitted once.
    counting = CountingTransport(client.transport)
    client = Client(counting, timeout=0.2, retries=2, exec_timeout=2.0)
    assert client.execute("SLOW.COM").exit_code == 0
    assert counting.writes == 1

    stdin_result = client.execute(
        "STDIN.COM", execution_id=0x00112233, stdin_path="CHILD.IN"
    )
    assert stdin_result.exit_code == 0
    stdin_output = work / "STDIN.RET"
    client.get("STDIN.OUT", stdin_output)
    assert stdin_output.read_bytes() == stdin_source.read_bytes()

    execution_id = 0x00ABCDEF
    result = client.execute("HELLO.COM", "one two", execution_id)
    assert result.exit_code == 7
    stdout = work / "STDOUT.TXT"
    stderr = work / "STDERR.TXT"
    artifact = work / "CHILD.OUT"
    client.get(result.stdout_path, stdout)
    client.get(result.stderr_path, stderr)
    client.get("FILE.OUT", artifact)
    assert stdout.read_bytes() == b"captured stdout\r\n"
    assert stderr.read_bytes() == b"captured stderr\r\n"
    assert artifact.read_bytes() == b"child artifact\r\n"

    # Recreate all host protocol state like a restarted serial host.  The
    # DOSBox null-modem client does not redial a dropped TCP socket, so the
    # emulator harness retains that byte-stream connection; a physical serial
    # process restart likewise reopens the same electrical byte stream.
    transport = client.transport
    client = Client(transport, timeout=2.0, retries=5)
    assert client.ping() == "PONG"
    replayed = client.execute("HELLO.COM", "one two", execution_id)
    assert replayed.exit_code == 7
    runs = work / "RUNS.OUT"
    client.get("RUNS.BIN", runs)
    assert runs.read_bytes() == b"X"

    resumed = work / "RESUMED.BIN"
    resumed.with_name(resumed.name + ".part").write_bytes(source.read_bytes()[:777])
    client.get("INPUT.BIN", resumed)
    assert resumed.read_bytes() == source.read_bytes()
    stale = work / "STALE.BIN"
    stale.with_name(stale.name + ".part").write_bytes(b"stale" * 800)
    client.get("INPUT.BIN", stale)
    assert stale.read_bytes() == source.read_bytes()
    try:
        client.crc("../ESCAPE")
    except RemoteError as exc:
        assert exc.status == Status.DENIED
    else:
        raise AssertionError("unsafe path accepted")
    client.remove("INPUT.BIN")
    client.quit()
    client.close()
    server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

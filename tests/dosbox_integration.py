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
    # Reuse the same transaction to exercise encoded response replay.
    assert client.request(Command.PING, transaction=0x12345678)
    assert client.request(Command.PING, transaction=0x12345678)

    # Promote a byte-identical build through the real two-phase DOS path.  The
    # DOSBox command queue acts as the tiny launcher for this integration run.
    update_stats = client.put(work / "DOSRAVI.COM", "DOSRAVI.NEW")
    client.stage_update("DOSRAVI.NEW", update_stats.bytes, update_stats.crc32)
    assert client.info()["agent"] == "DOSRAVI.COM"
    assert (work / "DOSRAVI.OLD").exists()
    assert (work / "UPDATE.PND").exists()
    client.confirm_update()
    assert not (work / "UPDATE.PND").exists()
    assert (work / "DOSRAVI.OLD").read_bytes() == (work / "DOSRAVI.COM").read_bytes()

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
    size, _ = client.crc("INPUT.BIN")
    assert size == source.stat().st_size
    listing = {entry["name"] for entry in client.list()}
    assert {"INPUT.BIN", "HELLO.COM", "DOSRAVI.COM", "DOSRAVI.OLD"} <= listing

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

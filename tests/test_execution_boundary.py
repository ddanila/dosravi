"""Execution uncertainty must not become an automatic second invocation."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dosravi.agent import Agent
from dosravi.client import Client
from dosravi.protocol import (
    Command,
    Frame,
    FrameType,
    Status,
    Tag,
    response_payload,
    tlv_text,
)
from dosravi.transport import LoopbackTransport, Transport, TransportError


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class StartedTransport(Transport):
    def __init__(
        self, clock, *, duplicate=False, disconnect=False, command=Command.EXEC
    ):
        self.clock = clock
        self.duplicate = duplicate
        self.disconnect = disconnect
        self.command = command
        self.writes = []
        self.reads = 0

    def write(self, data):
        self.writes.append(data)
        self.transaction = Frame.decode(data[:-1]).transaction

    def read(self, size, timeout):
        self.reads += 1
        self.clock.now += min(1.0, timeout)
        if self.reads == 1 or (self.duplicate and self.reads <= 10):
            return Frame(
                FrameType.EVENT,
                self.transaction,
                payload=response_payload(
                    self.command, Status.OK, tlv_text(Tag.MESSAGE, "STARTED")
                ),
            ).encode()
        if self.disconnect:
            raise TransportError("disconnected")
        self.clock.now += max(0.0, timeout - 1.0)
        return b""

    def close(self):
        pass


class ExecutionBoundaryTests(unittest.TestCase):
    def test_started_timeout_and_disconnect_never_resend_exec(self):
        for duplicate, disconnect in [(False, False), (True, False), (False, True)]:
            with self.subTest(duplicate=duplicate, disconnect=disconnect):
                clock = Clock()
                transport = StartedTransport(
                    clock, duplicate=duplicate, disconnect=disconnect
                )
                client = Client(transport, timeout=2, exec_timeout=3, retries=4)
                with (
                    patch("dosravi.client.time.monotonic", clock),
                    self.assertRaises(TransportError),
                ):
                    client.execute("TASK.COM", execution_id=123)
                self.assertEqual(len(transport.writes), 1)
                self.assertLessEqual(clock.now, 4)

    def test_unrelated_started_does_not_extend_exec_wait(self):
        clock = Clock()
        transport = StartedTransport(clock, command=Command.PING)
        client = Client(transport, timeout=2, exec_timeout=300, retries=0)
        with (
            patch("dosravi.client.time.monotonic", clock),
            self.assertRaises(TransportError),
        ):
            client.execute("TASK.COM", execution_id=123)
        self.assertLessEqual(clock.now, 3)

    def test_host_reconnect_replays_but_target_restart_loses_cache(self):
        # Characterize the existing protocol's limit, not a promise of durable dedup.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = root / "TASK.COM"
            program.write_text("#!/bin/sh\nprintf X >> RUNS.BIN\n")
            program.chmod(0o700)
            agent = Agent(root)
            first = Client(LoopbackTransport(agent.receive))
            first.execute("TASK.COM", execution_id=123)
            reconnected = Client(LoopbackTransport(agent.receive))
            reconnected.execute("TASK.COM", execution_id=123)
            self.assertEqual((root / "RUNS.BIN").read_bytes(), b"X")
            restarted = Client(LoopbackTransport(Agent(root).receive))
            restarted.execute("TASK.COM", execution_id=123)
            self.assertEqual((root / "RUNS.BIN").read_bytes(), b"XX")


if __name__ == "__main__":
    unittest.main()

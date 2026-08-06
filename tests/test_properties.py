from __future__ import annotations

import tempfile
import unittest
from collections import deque
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from dosravi.agent import Agent
from dosravi.client import Client, RemoteError
from dosravi.protocol import (
    MAX_PAYLOAD,
    Command,
    Frame,
    FrameDecoder,
    FrameType,
    cobs_decode,
    cobs_encode,
)
from dosravi.transport import Transport


class PropertyTests(unittest.TestCase):
    @settings(max_examples=250, deadline=None)
    @given(st.binary(max_size=MAX_PAYLOAD), st.integers(1, 0xFFFFFFFF))
    def test_frame_round_trip(self, payload: bytes, transaction: int) -> None:
        original = Frame(FrameType.REQUEST, transaction, payload=payload)
        self.assertEqual(Frame.decode(original.encode()), original)

    @settings(max_examples=250, deadline=None)
    @given(st.binary(max_size=8192))
    def test_cobs_round_trip(self, payload: bytes) -> None:
        encoded = cobs_encode(payload)
        self.assertNotIn(0, encoded)
        self.assertEqual(cobs_decode(encoded), payload)

    @settings(max_examples=300, deadline=None)
    @given(st.binary(max_size=20000))
    def test_arbitrary_corruption_keeps_decoder_bounded(self, data: bytes) -> None:
        decoder = FrameDecoder(max_encoded=128)
        decoder.feed(data)
        self.assertLessEqual(len(decoder.buffer), 128)


class FaultTransport(Transport):
    def __init__(self, agent: Agent, fault: str):
        self.agent = agent
        self.fault = fault
        self.writes = 0
        self.empty_reads = 0
        self.pending: deque[bytes] = deque()

    def write(self, data: bytes) -> None:
        self.writes += 1
        response = self.agent.receive(data)
        if self.writes == 1 and self.fault == "loss":
            return
        if self.writes == 1 and self.fault == "corruption":
            damaged = bytearray(response)
            damaged[len(damaged) // 2] ^= 0x40
            response = bytes(damaged)
        if self.writes == 1 and self.fault == "duplicate":
            response += response
        if self.writes == 1 and self.fault == "delay":
            self.empty_reads = 3
        self.pending.append(response)

    def read(self, size: int, timeout: float) -> bytes:
        if self.empty_reads:
            self.empty_reads -= 1
            return b""
        if not self.pending:
            return b""
        data = self.pending.popleft()
        if len(data) > size:
            self.pending.appendleft(data[size:])
            return data[:size]
        return data

    def close(self) -> None:
        pass


class FaultRecoveryTests(unittest.TestCase):
    def test_loss_corruption_duplicate_and_delay(self) -> None:
        for fault in ("loss", "corruption", "duplicate", "delay"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                agent = Agent(Path(directory))
                transport = FaultTransport(agent, fault)
                client = Client(transport, timeout=0.001, retries=4)
                self.assertEqual(client.ping(), "PONG")
                self.assertGreaterEqual(transport.writes, 1)

    def test_transaction_identifier_cannot_change_meaning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = Agent(Path(directory))
            transport = FaultTransport(agent, "none")
            client = Client(transport, timeout=0.001)
            self.assertEqual(client.ping(), "PONG")
            transaction = 0x22446688
            client.request(Command.PING, transaction=transaction)
            with self.assertRaises(RemoteError):
                client.request(Command.INFO, transaction=transaction)


if __name__ == "__main__":
    unittest.main()

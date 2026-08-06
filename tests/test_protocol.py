from __future__ import annotations

import os
import random
import tempfile
import unittest
from pathlib import Path

from dosravi.agent import Agent
from dosravi.client import Client, RemoteError
from dosravi.protocol import (
    Command,
    Frame,
    FrameDecoder,
    FrameType,
    ProtocolError,
    Status,
    cobs_decode,
    cobs_encode,
    crc16_ccitt,
    file_crc32,
    request_payload,
)
from dosravi.session import (
    parse_willem_log,
    parse_willem_write_log,
    timing_summary,
    validate_read_images,
)
from dosravi.transport import LoopbackTransport


class ProtocolTests(unittest.TestCase):
    def test_check_vectors(self) -> None:
        self.assertEqual(crc16_ccitt(b"123456789"), 0x29B1)
        self.assertEqual(file_crc32(b"123456789"), 0xCBF43926)
        self.assertEqual(file_crc32(b"56789", file_crc32(b"1234")), 0xCBF43926)

    def test_cobs_all_byte_values(self) -> None:
        original = bytes(range(256)) * 3
        encoded = cobs_encode(original)
        self.assertNotIn(0, encoded)
        self.assertEqual(cobs_decode(encoded), original)

    def test_frame_corruption_and_truncation(self) -> None:
        encoded = Frame(FrameType.REQUEST, 42, payload=b"hello").encode()
        self.assertEqual(Frame.decode(encoded).payload, b"hello")
        damaged = bytearray(encoded)
        damaged[5] ^= 0x40
        with self.assertRaises(ProtocolError):
            Frame.decode(bytes(damaged))
        with self.assertRaises(ProtocolError):
            Frame.decode(encoded[:5])

    def test_decoder_bounded_resynchronization(self) -> None:
        decoder = FrameDecoder(max_encoded=32)
        valid = Frame(FrameType.REQUEST, 7, payload=b"ok").encode()
        frames = decoder.feed(b"x" * 100 + b"\0" + valid)
        self.assertEqual([frame.transaction for frame in frames], [7])

    def test_fuzz_decoder_recovers(self) -> None:
        random.seed(1)
        for transaction in range(100):
            decoder = FrameDecoder(max_encoded=128)
            noise = os.urandom(random.randrange(0, 400)) + b"\0"
            valid = Frame(
                FrameType.REQUEST, transaction + 1, payload=os.urandom(20)
            ).encode()
            frames = []
            combined = noise + valid
            while combined:
                take = random.randrange(1, min(19, len(combined)) + 1)
                frames.extend(decoder.feed(combined[:take]))
                combined = combined[take:]
            self.assertEqual(frames[-1].transaction, transaction + 1)


class IntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.agent = Agent(self.root / "remote")
        self.client = Client(
            LoopbackTransport(self.agent.receive), timeout=0.01, retries=2
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temporary.cleanup()

    def test_all_file_operations_and_resume(self) -> None:
        local = self.root / "source.bin"
        local.write_bytes(bytes(range(256)) * 9)
        # Seed an interrupted upload and matching metadata.
        part = self.root / "remote" / "DATA.BIN.PART"
        part.write_bytes(local.read_bytes()[:700])
        expected = file_crc32(local.read_bytes())
        (self.root / "remote" / "DATA.BIN.META").write_text(
            f"{local.stat().st_size}:{expected:08x}", "ascii"
        )
        stats = self.client.put(local, "DATA.BIN")
        self.assertEqual(stats.bytes, local.stat().st_size)
        self.assertEqual(self.client.crc("DATA.BIN"), (local.stat().st_size, expected))
        output = self.root / "output.bin"
        self.client.get("DATA.BIN", output)
        self.assertEqual(output.read_bytes(), local.read_bytes())
        self.assertEqual(
            self.client.list(), [{"name": "DATA.BIN", "size": local.stat().st_size}]
        )
        self.client.remove("DATA.BIN")
        with self.assertRaises(RemoteError) as caught:
            self.client.crc("DATA.BIN")
        self.assertEqual(caught.exception.status, Status.NOT_FOUND)

    def test_transaction_duplicate_replays_without_effect(self) -> None:
        request = Frame(
            FrameType.REQUEST, 99, payload=request_payload(Command.PING)
        ).encode()
        first = Frame.decode(self.agent.receive(request))
        second = Frame.decode(self.agent.receive(request))
        self.assertEqual(first.payload, second.payload)
        self.assertEqual(second.flags & 2, 2)

    def test_path_rejection(self) -> None:
        for path in ("../X", "C:X", "A/B", "*.COM", "TOO-LONG9.COM", ".", "CON"):
            with self.subTest(path=path), self.assertRaises(RemoteError) as caught:
                self.client.crc(path)
            self.assertIn(caught.exception.status, (Status.DENIED, Status.NOT_FOUND))

    def test_partial_download_resume(self) -> None:
        data = os.urandom(2000)
        (self.root / "remote" / "ROM.BIN").write_bytes(data)
        destination = self.root / "rom.bin"
        destination.with_name("rom.bin.part").write_bytes(data[:777])
        self.client.get("ROM.BIN", destination)
        self.assertEqual(destination.read_bytes(), data)


class AcceptanceTests(unittest.TestCase):
    def test_image_gate_and_timings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            data = bytes(range(1, 129))
            for index in range(10):
                path = root / f"{index}.bin"
                path.write_bytes(data)
                paths.append(path)
            result = validate_read_images(paths)
            self.assertEqual(result["count"], 10)
            self.assertEqual(
                timing_summary([10, 12, 11, 15, 9, 14, 13, 8, 16, 10]),
                {
                    "count": 10,
                    "minimum_ms": 8,
                    "median_ms": 11.5,
                    "maximum_ms": 16,
                    "spread_ms": 8,
                },
            )
            paths[-1].write_bytes(b"different")
            with self.assertRaises(ValueError):
                validate_read_images(paths)
            for path in paths:
                path.write_bytes(b"\xff" * 8)
            with self.assertRaises(ValueError):
                validate_read_images(paths)

    def test_structured_willem_timing_requires_safe_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "WILLEM.LOG"
            log.write_text(
                "DOSRAVI_METRIC read_ms=1234 profile=conservative\n"
                "Safe shutdown complete: VCC off, VPP off\n",
                encoding="ascii",
            )
            self.assertEqual(
                parse_willem_log(log),
                {
                    "read_ms": 1234,
                    "profile": "conservative",
                    "safe_shutdown": True,
                },
            )
            log.write_text(
                "DOSRAVI_METRIC read_ms=1234 profile=fast\n",
                encoding="ascii",
            )
            with self.assertRaises(ValueError):
                parse_willem_log(log)

    def test_structured_willem_write_metric_requires_safe_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "WILLEM.LOG"
            log.write_text(
                "DOSRAVI_WRITE_METRIC program_ms=1200 verify_ms=800 "
                "changed=4096 unchanged=4096 retry_bytes=2 retries=3 late=1\n"
                "Safe shutdown complete: VCC off, VPP off\n",
                encoding="ascii",
            )
            self.assertEqual(
                parse_willem_write_log(log),
                {
                    "program_ms": 1200,
                    "verify_ms": 800,
                    "changed": 4096,
                    "unchanged": 4096,
                    "retry_bytes": 2,
                    "retries": 3,
                    "late": 1,
                    "safe_shutdown": True,
                },
            )
            log.write_text(
                "DOSRAVI_WRITE_METRIC program_ms=1 verify_ms=1 "
                "changed=1 unchanged=0 retry_bytes=0 retries=0 late=0\n",
                encoding="ascii",
            )
            with self.assertRaises(ValueError):
                parse_willem_write_log(log)


if __name__ == "__main__":
    unittest.main()

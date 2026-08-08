from __future__ import annotations

import tempfile
import unittest
from itertools import pairwise
from pathlib import Path

from dosravi.cli import (
    _parse_willem_write_evidence,
    _parser,
    _persistent_execution_ids,
    _validate_profile_step,
)


class WillemWriteArgumentTests(unittest.TestCase):
    def test_post_write_read_defaults_to_one(self) -> None:
        args = _parser().parse_args(
            [
                "willem-write",
                "--program",
                "WILLEM.COM",
                "--device",
                "28C64",
                "--image",
                "TARGET.BIN",
                "--gate",
                "WRITE.OK",
                "--read-profile",
                "legacy",
                "--output",
                "session",
            ]
        )
        self.assertEqual(args.post_write_count, 1)

    def test_post_write_read_count_is_bounded(self) -> None:
        base = [
            "willem-write",
            "--program",
            "WILLEM.COM",
            "--device",
            "28C64",
            "--image",
            "TARGET.BIN",
            "--gate",
            "WRITE.OK",
            "--read-profile",
            "legacy",
            "--output",
            "session",
            "--post-write-count",
        ]
        self.assertEqual(_parser().parse_args([*base, "10"]).post_write_count, 10)
        with self.assertRaises(SystemExit):
            _parser().parse_args([*base, "0"])

    def test_current_stdout_precedes_stale_append_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdout = root / "STDOUT.TXT"
            log = root / "WILLEM.LOG"
            log.write_text("old log without the current metric\n", encoding="ascii")
            stdout.write_text(
                "DOSRAVI_WRITE_METRIC program_ms=10 verify_ms=20 "
                "changed=1 unchanged=8191 retry_bytes=0 retries=0 late=0 "
                "image_crc32=9dcc5558 build_id=physical\n"
                "Safe shutdown complete: VCC off, VPP off\n",
                encoding="ascii",
            )
            metrics, evidence = _parse_willem_write_evidence((stdout, log), "9dcc5558")
            self.assertEqual(evidence, stdout)
            self.assertEqual(metrics["changed"], 1)


class ExecutionManifestTests(unittest.TestCase):
    def test_ids_persist_and_identity_changes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, manifest = _persistent_execution_ids(
                root, "physical-operation-v1", ["one", "two"]
            )
            second, same_manifest = _persistent_execution_ids(
                root, "physical-operation-v1", ["one", "two"]
            )
            self.assertEqual(first, second)
            self.assertEqual(manifest, same_manifest)
            self.assertEqual(len(set(first)), 2)
            with self.assertRaises(RuntimeError):
                _persistent_execution_ids(
                    root, "physical-operation-v1", ["one", "changed"]
                )


class ProfileSweepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conservative = {
            "address_setup_us": 4,
            "oe_settle_us": 4,
            "input_latch_us": 4,
            "input_clock_us": 4,
            "power_on_ms": 5,
            "build_id": "git-deadbeef",
        }

    def test_exactly_one_timing_dimension_must_decrease(self) -> None:
        next_profile = {**self.conservative, "address_setup_us": 2}
        _validate_profile_step(self.conservative, next_profile)
        with self.assertRaises(ValueError):
            _validate_profile_step(
                self.conservative,
                {**next_profile, "oe_settle_us": 2},
            )
        with self.assertRaises(ValueError):
            _validate_profile_step(
                self.conservative,
                {**self.conservative, "address_setup_us": 8},
            )

    def test_power_is_a_dimension_and_build_must_remain_fixed(self) -> None:
        _validate_profile_step(
            self.conservative, {**self.conservative, "power_on_ms": 4}
        )
        for changed in (
            {"address_setup_us": 2, "power_on_ms": 4},
            {"address_setup_us": 2, "build_id": "git-changed"},
        ):
            with self.assertRaises(ValueError):
                _validate_profile_step(
                    self.conservative, {**self.conservative, **changed}
                )

    def test_willem_v2_profile_sequence_is_one_variable_at_a_time(self) -> None:
        values = (
            (4, 4, 4, 4, 5),
            (2, 4, 4, 4, 5),
            (2, 2, 4, 4, 5),
            (2, 2, 2, 4, 5),
            (2, 2, 2, 2, 5),
            (1, 2, 2, 2, 5),
            (1, 1, 2, 2, 5),
            (1, 1, 1, 2, 5),
            (1, 1, 1, 1, 5),
            (1, 1, 1, 1, 4),
        )
        names = (
            "address_setup_us",
            "oe_settle_us",
            "input_latch_us",
            "input_clock_us",
            "power_on_ms",
        )
        profiles = [
            {**dict(zip(names, profile)), "build_id": "dosravi-profiles-v2"}
            for profile in values
        ]
        for previous, current in pairwise(profiles):
            _validate_profile_step(previous, current)


if __name__ == "__main__":
    unittest.main()

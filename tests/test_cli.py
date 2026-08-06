from __future__ import annotations

import tempfile
import unittest
from itertools import pairwise
from pathlib import Path

from dosravi.cli import _persistent_execution_ids, _validate_profile_step


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

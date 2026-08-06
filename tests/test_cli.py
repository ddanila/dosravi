from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dosravi.cli import _persistent_execution_ids


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


if __name__ == "__main__":
    unittest.main()

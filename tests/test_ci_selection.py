import subprocess
import unittest
from unittest.mock import patch

from tools.select_ci import ALL, changed_paths, select


class SelectionTests(unittest.TestCase):
    def test_prose_only_needs_no_toolchain(self):
        self.assertFalse(any(select(["README.md", "docs/protocol.md"]).values()))

    def test_host_changes_run_actual_dos_but_not_decoder_fuzz(self):
        for path in [
            "dosravi/transport.py",
            "dosravi/client.py",
            "tests/test_transport.py",
            "tools/test_dosbox.sh",
            "dos/RAVI.BAT",
        ]:
            with self.subTest(path=path):
                self.assertEqual(
                    select([path]), {"native": True, "dos": True, "fuzz": False}
                )

    def test_decoder_and_control_changes_run_everything(self):
        for path in [
            "src/protocol.c",
            "include/dosravi.h",
            ".github/workflows/ci.yml",
            "Makefile",
            "AGENTS.md",
            "new-target/agent.asm",
        ]:
            with self.subTest(path=path):
                self.assertEqual(select([path]), ALL)
        self.assertEqual(select([]), ALL)

    def test_docs_do_not_hide_a_code_change_or_deleted_file(self):
        self.assertEqual(select(["README.md", "src/protocol.c"]), ALL)

    def test_pull_request_uses_merge_base_push_uses_previous_tip(self):
        with patch(
            "tools.select_ci.subprocess.check_output", return_value="src/protocol.c\n"
        ) as diff:
            self.assertEqual(
                changed_paths(
                    {"pull_request": {"base": {"sha": "abc"}, "head": {"sha": "def"}}},
                    "pull_request",
                ),
                ["src/protocol.c"],
            )
            self.assertIn("abc...def", diff.call_args.args[0])
            changed_paths({"before": "abc", "after": "def"}, "push")
            self.assertEqual(diff.call_args.args[0][-3:], ["abc", "def", "--"])
        with patch(
            "tools.select_ci.subprocess.check_output",
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            self.assertEqual(
                select(changed_paths({"before": "missing", "after": "def"}, "push")),
                ALL,
            )

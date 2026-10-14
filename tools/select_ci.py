#!/usr/bin/env python3
"""Conservative CI selection: unknown paths/diffs run everything; prose runs none."""

import json
import os
import subprocess
from pathlib import Path

ALL = {"native": True, "dos": True, "fuzz": True}


def select(paths):
    if not paths:
        return dict(ALL)
    result = dict.fromkeys(ALL, False)
    for path in paths:
        # Explicit policy files are code, even when written in Markdown.
        if (
            path == "AGENTS.md"
            or path.startswith(".github/")
            or path
            in {
                "Makefile",
                "pyproject.toml",
                "tools/select_ci.py",
                "tests/test_ci_selection.py",
                "tools/verify.sh",
            }
        ):
            return dict(ALL)
        if path.endswith(".md") or path in {"LICENSE", ".gitignore"}:
            continue
        if path.startswith(
            ("dosravi/", "src/", "include/", "tests/", "tools/", "dos/")
        ):
            result["native"] = True
            result["dos"] = True
            if path in {
                "src/protocol.c",
                "include/dosravi.h",
                "tests/fuzz_decoder.c",
                "tools/fuzz_decoder.sh",
            }:
                result["fuzz"] = True
        else:
            return dict(ALL)
    return result


def changed_paths(event, name):
    if name == "workflow_dispatch":
        return []
    if name == "pull_request":
        base, head = (
            event["pull_request"]["base"]["sha"],
            event["pull_request"]["head"]["sha"],
        )
        revisions = [f"{base}...{head}"]
    elif name == "push":
        revisions = [event["before"], event["after"]]
    else:
        return []
    try:
        return subprocess.check_output(
            ["git", "diff", "--name-only", "--no-renames", *revisions, "--"],
            text=True,
        ).splitlines()
    except subprocess.CalledProcessError:
        return []


def main():
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        selection = select(changed_paths(event, os.environ["GITHUB_EVENT_NAME"]))
    except (KeyError, ValueError, OSError):
        selection = dict(ALL)
    print(json.dumps(selection, sort_keys=True))
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.writelines(
            f"{name}={str(enabled).lower()}\n" for name, enabled in selection.items()
        )


if __name__ == "__main__":
    main()

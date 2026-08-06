"""Reproducible session records and artifact verification."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(65536):
            digest.update(block)
    return digest.hexdigest()


def crc32_file(path: Path) -> int:
    crc = 0
    with path.open("rb") as stream:
        while block := stream.read(65536):
            crc = zlib.crc32(block, crc)
    return crc & 0xFFFFFFFF


def source_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


@dataclass
class Artifact:
    name: str
    size: int
    crc32: str
    sha256: str


@dataclass
class SessionRecord:
    session_id: str
    started_utc: str
    host_version: str
    source_commit: str | None
    transport: dict[str, Any]
    negotiated: dict[str, Any] = field(default_factory=dict)
    command_line: list[str] = field(default_factory=list)
    hardware_notes: dict[str, str] = field(default_factory=dict)
    transactions: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    serial_stats: dict[str, Any] = field(default_factory=dict)
    programmer_stats: dict[str, Any] = field(default_factory=dict)
    exit_status: int | None = None
    completed_utc: str | None = None

    @classmethod
    def create(
        cls, session_id: str, host_version: str, transport: dict[str, Any]
    ) -> SessionRecord:
        return cls(
            session_id=session_id,
            started_utc=datetime.now(timezone.utc).isoformat(),
            host_version=host_version,
            source_commit=source_commit(),
            transport=transport,
        )

    def add_artifact(self, path: Path, name: str | None = None) -> Artifact:
        artifact = Artifact(
            name=name or path.name,
            size=path.stat().st_size,
            crc32=f"{crc32_file(path):08x}",
            sha256=sha256_file(path),
        )
        self.artifacts.append(artifact)
        return artifact

    def finish(self) -> None:
        self.completed_utc = datetime.now(timezone.utc).isoformat()

    def write(self, path: Path) -> None:
        path.write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def timing_summary(milliseconds: list[int]) -> dict[str, float | int]:
    if not milliseconds:
        raise ValueError("no timing samples")
    ordered = sorted(milliseconds)
    count = len(ordered)
    if count % 2:
        median: float = float(ordered[count // 2])
    else:
        median = (ordered[count // 2 - 1] + ordered[count // 2]) / 2
    return {
        "count": count,
        "minimum_ms": ordered[0],
        "median_ms": median,
        "maximum_ms": ordered[-1],
        "spread_ms": ordered[-1] - ordered[0],
    }


def validate_read_images(
    paths: list[Path], trusted: Path | None = None
) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one image is required")
    first_data = paths[0].read_bytes()
    if not first_data:
        raise ValueError("empty image")
    if all(byte == 0x00 for byte in first_data) or all(
        byte == 0xFF for byte in first_data
    ):
        raise ValueError("uniform stuck-bus image")
    first_hash = hashlib.sha256(first_data).hexdigest()
    for path in paths[1:]:
        if path.read_bytes() != first_data:
            raise ValueError(f"image mismatch: {path}")
    if trusted is not None and trusted.read_bytes() != first_data:
        raise ValueError("images do not match trusted reference")
    return {
        "size": len(first_data),
        "sha256": first_hash,
        "count": len(paths),
        "trusted": trusted is not None,
    }


def parse_willem_log(path: Path) -> dict[str, Any]:
    """Read the last structured local-timing record from WILLEM.LOG."""

    text = path.read_text(encoding="ascii", errors="replace")
    matches = list(
        re.finditer(
            r"DOSRAVI_METRIC\s+read_ms=(\d+)"
            r"(?:\s+profile=([A-Za-z0-9_-]+))?",
            text,
        )
    )
    if not matches:
        raise ValueError("WILLEM.LOG has no local PIT read timing record")
    match = matches[-1]
    if "Safe shutdown complete: VCC off, VPP off" not in text[match.start() :]:
        raise ValueError("WILLEM.LOG does not prove safe shutdown after the timed read")
    return {
        "read_ms": int(match.group(1)),
        "profile": match.group(2),
        "safe_shutdown": True,
    }


def parse_willem_write_log(path: Path) -> dict[str, int | bool]:
    text = path.read_text(encoding="ascii", errors="replace")
    matches = list(
        re.finditer(
            r"DOSRAVI_WRITE_METRIC\s+program_ms=(\d+)\s+verify_ms=(\d+)"
            r"\s+changed=(\d+)\s+unchanged=(\d+)\s+retry_bytes=(\d+)"
            r"\s+retries=(\d+)\s+late=(\d+)",
            text,
        )
    )
    if not matches:
        raise ValueError("WILLEM.LOG has no structured programming metric")
    match = matches[-1]
    if "Safe shutdown complete: VCC off, VPP off" not in text[match.start() :]:
        raise ValueError("WILLEM.LOG does not prove safe shutdown after programming")
    names = (
        "program_ms",
        "verify_ms",
        "changed",
        "unchanged",
        "retry_bytes",
        "retries",
        "late",
    )
    result: dict[str, int | bool] = {
        name: int(value) for name, value in zip(names, match.groups())
    }
    result["safe_shutdown"] = True
    return result

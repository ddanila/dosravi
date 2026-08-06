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


def source_dirty() -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        return bool(result.stdout)
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
    source_dirty: bool | None
    transport: dict[str, Any]
    negotiated: dict[str, Any] = field(default_factory=dict)
    command_line: list[str] = field(default_factory=list)
    hardware_notes: dict[str, str] = field(default_factory=dict)
    transactions: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    serial_stats: dict[str, Any] = field(default_factory=dict)
    programmer_stats: dict[str, Any] = field(default_factory=dict)
    exit_status: int | None = None
    error: str | None = None
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
            source_dirty=source_dirty(),
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


def parse_willem_log(
    path: Path,
    expected_profile: str | None = None,
) -> dict[str, Any]:
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
    result: dict[str, Any] = {
        "read_ms": int(match.group(1)),
        "profile": match.group(2),
        "safe_shutdown": True,
    }
    if expected_profile is not None:
        if match.group(2) != expected_profile:
            raise ValueError(
                f"WILLEM.LOG profile {match.group(2)!r} does not match "
                f"requested {expected_profile!r}"
            )
        profile_matches = list(
            re.finditer(
                r"DOSRAVI_PROFILE\s+name=([A-Za-z0-9_-]+)"
                r"\s+address_setup_us=(\d+)\s+oe_settle_us=(\d+)"
                r"\s+input_latch_us=(\d+)\s+input_clock_us=(\d+)"
                r"\s+power_on_ms=(\d+)\s+build_id=([A-Za-z0-9_.-]+)",
                text[: match.start()],
            )
        )
        if not profile_matches or profile_matches[-1].group(1) != expected_profile:
            raise ValueError("WILLEM.LOG lacks exact parameters for requested profile")
        profile_match = profile_matches[-1]
        result["parameters"] = {
            "address_setup_us": int(profile_match.group(2)),
            "oe_settle_us": int(profile_match.group(3)),
            "input_latch_us": int(profile_match.group(4)),
            "input_clock_us": int(profile_match.group(5)),
            "power_on_ms": int(profile_match.group(6)),
            "build_id": profile_match.group(7),
        }
    return result


def parse_legacy_willem_log(path: Path, expected_device: str) -> dict[str, Any]:
    """Parse the last unmodified Willem 0.0.5 run for an M4 baseline."""

    text = path.read_text(encoding="ascii", errors="replace")
    begin = text.rfind("================ BEGIN RUN ================")
    if begin < 0:
        raise ValueError("WILLEM.LOG has no legacy BEGIN RUN marker")
    run = text[begin:]
    if "================= END RUN =================" not in run:
        raise ValueError("last legacy Willem run is incomplete")
    operation = re.search(
        r"Operation=READ\s+device=([A-Za-z0-9_-]+).*\s+trace=(on|off)", run
    )
    logged_device = operation.group(1).upper() if operation else ""
    expected = expected_device.upper()
    device_matches = logged_device == expected or (
        expected == "28C64" and logged_device == "AT28C64"
    )
    if not operation or not device_matches:
        raise ValueError("last legacy Willem run is not the requested read")
    if operation.group(2) != "off":
        raise ValueError("legacy speed baseline cannot use full tracing")
    if not re.search(r"Read complete: bytes=8192 CRC16-CCITT=[0-9A-Fa-f]{4}", run):
        raise ValueError("legacy Willem run lacks a complete 8192-byte read")
    timestamp_pattern = r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{2})\]"
    powered = re.search(
        timestamp_pattern + r" Power transition: enabling VCC, VPP off", run
    )
    shutdown = re.search(
        timestamp_pattern + r" Safe shutdown complete: VCC off, VPP off", run
    )
    if not powered or not shutdown or shutdown.start() <= powered.start():
        raise ValueError("legacy Willem run lacks ordered power/safe-shutdown evidence")
    timestamp_format = "%Y-%m-%d %H:%M:%S.%f"
    started = datetime.strptime(powered.group(1), timestamp_format).replace(
        tzinfo=timezone.utc
    )
    finished = datetime.strptime(shutdown.group(1), timestamp_format).replace(
        tzinfo=timezone.utc
    )
    elapsed_ms = round((finished - started).total_seconds() * 1000)
    if elapsed_ms <= 0:
        raise ValueError("legacy Willem read window is not positive")
    version = re.search(r"Willem V30 version ([^;\s]+)", run)
    return {
        "read_ms": elapsed_ms,
        "profile": "legacy-current",
        "safe_shutdown": True,
        "timing_source": "DOS timestamped power-on-to-safe-shutdown window",
        "willem_version": version.group(1) if version else None,
    }


def parse_willem_write_log(
    path: Path,
    expected_image_crc32: str | None = None,
) -> dict[str, int | bool | str]:
    text = path.read_text(encoding="ascii", errors="replace")
    matches = list(
        re.finditer(
            r"DOSRAVI_WRITE_METRIC\s+program_ms=(\d+)\s+verify_ms=(\d+)"
            r"\s+changed=(\d+)\s+unchanged=(\d+)\s+retry_bytes=(\d+)"
            r"\s+retries=(\d+)\s+late=(\d+)"
            r"\s+image_crc32=([0-9a-fA-F]{8})"
            r"\s+build_id=([A-Za-z0-9_.-]+)",
            text,
        )
    )
    if not matches:
        raise ValueError("WILLEM.LOG has no structured programming metric")
    match = matches[-1]
    if "Safe shutdown complete: VCC off, VPP off" not in text[match.start() :]:
        raise ValueError("WILLEM.LOG does not prove safe shutdown after programming")
    integer_names = (
        "program_ms",
        "verify_ms",
        "changed",
        "unchanged",
        "retry_bytes",
        "retries",
        "late",
    )
    result: dict[str, int | bool | str] = {
        name: int(value) for name, value in zip(integer_names, match.groups()[:7])
    }
    image_crc32 = match.group(8).lower()
    build_id = match.group(9)
    if expected_image_crc32 is not None and image_crc32 != expected_image_crc32.lower():
        raise ValueError("WILLEM.LOG write image identity does not match request")
    result["image_crc32"] = image_crc32
    result["build_id"] = build_id
    result["safe_shutdown"] = True
    return result

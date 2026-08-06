#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$project_root"

python3 - <<'PY'
from pathlib import Path

for path in Path("dos").glob("*.BAT"):
    data = path.read_bytes()
    if b"\n" in data.replace(b"\r\n", b"") or b"\n" not in data:
        raise SystemExit(f"DOS batch source is not CRLF: {path}")
print("DOS batch source CRLF validation passed")
PY

make check
make dos-test
make fuzz
make dist
git diff --check

python3 - <<'PY'
from pathlib import Path

required = {
    "AUTOEXEC.BAT",
    "COMPROBE.COM",
    "DOSRAVI.COM",
    "HWSETUP.TXT",
    "RAVILOAD.BAT",
    "README.TXT",
}
root = Path("build/dist")
actual = {path.name for path in root.iterdir() if path.is_file()}
if actual != required:
    raise SystemExit(f"distribution mismatch: expected {sorted(required)}, got {sorted(actual)}")
for path in root.iterdir():
    if path.suffix in (".TXT", ".BAT"):
        data = path.read_bytes()
        if b"\n" in data.replace(b"\r\n", b""):
            raise SystemExit(f"bare LF in {path}")
print("full local verification passed")
PY

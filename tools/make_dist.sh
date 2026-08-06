#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
    echo "usage: make_dist.sh DOSRAVI.COM COMPROBE.COM DOS_DIR OUTPUT_DIR" >&2
    exit 2
fi
agent=$1
probe=$2
dos_dir=$3
output=$4

[[ -f "$agent" && -f "$probe" && -d "$dos_dir" ]]
rm -rf "$output"
mkdir -p "$output"
cp "$agent" "$output/DOSRAVI.COM"
cp "$probe" "$output/COMPROBE.COM"
for source in "$dos_dir"/*; do
    name=$(basename "$source")
    [[ ${#name} -le 12 && "$name" == "${name^^}" ]] || {
        echo "distribution filename is not uppercase DOS 8.3: $name" >&2
        exit 1
    }
    # Normalize either LF or CRLF sources to exactly one DOS CRLF terminator.
    sed 's/\r$//; s/$/\r/' "$source" >"$output/$name"
done
python3 - "$output" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
for path in root.iterdir():
    stem, dot, suffix = path.name.partition(".")
    if len(stem) > 8 or len(suffix) > 3 or (dot and not suffix):
        raise SystemExit(f"not DOS 8.3: {path.name}")
    if path.suffix in (".TXT", ".BAT"):
        data = path.read_bytes()
        if b"\n" in data.replace(b"\r\n", b""):
            raise SystemExit(f"bare LF in {path.name}")
print("validated DOS distribution:", ", ".join(sorted(p.name for p in root.iterdir())))
PY

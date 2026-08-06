#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$project_root/build/fuzz/in"
printf '\0' >"$project_root/build/fuzz/in/empty-delimiter"
printf '\003\001\001\001\006\022\064\126\170\003\001\001\002\006\002A\002B\005CD\355\303\0' \
    >"$project_root/build/fuzz/in/valid-frame"

afl-clang-fast -O1 -g -fsanitize=address,undefined \
    -I"$project_root/include" \
    "$project_root/src/protocol.c" "$project_root/tests/fuzz_decoder.c" \
    -o "$project_root/build/fuzz/fuzz_decoder"

AFL_SKIP_CPUFREQ=1 AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES=1 \
    AFL_NO_UI=1 \
    timeout --preserve-status 8s afl-fuzz -V 5 \
    -i "$project_root/build/fuzz/in" -o "$(mktemp -d "$project_root/build/fuzz/out.XXXXXX")" -- \
    "$project_root/build/fuzz/fuzz_decoder" >/dev/null

[[ $(find "$project_root/build/fuzz" -path '*/crashes/*' -type f ! -name README.txt | wc -l) -eq 0 ]]
echo "AFL++ decoder smoke campaign passed"

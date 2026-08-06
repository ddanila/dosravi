#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd "$(dirname "$0")/.." && pwd)
agent="$project_root/build/dos/DOSRAVI.COM"
probe="$project_root/build/dos/COMPROBE.COM"

[[ -f "$agent" && -f "$probe" ]] || {
    echo "DOS programs are missing; run make dos" >&2
    exit 1
}
command -v dosbox-x >/dev/null
command -v nasm >/dev/null

test_root=$(mktemp -d /tmp/dosravi-dos-test.XXXXXX)
trap 'rm -rf "$test_root"' EXIT

test_boot_rollback() {
    local drive="$test_root/rollback"
    mkdir -p "$drive/RAVI"
    cp "$project_root/dos/RAVILOAD.BAT" "$drive/RAVI/RAVILOAD.BAT"
    nasm -f bin "$project_root/tests/BAD.ASM" -o "$drive/RAVI/DOSRAVI.COM"
    nasm -f bin "$project_root/tests/GOOD.ASM" -o "$drive/RAVI/DOSRAVI.OLD"
    printf 'pending\r\n' >"$drive/RAVI/UPDATE.PND"
    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy dosbox-x -silent -fastlaunch \
        -set "dosbox quit warning=false" \
        -set "sdl output=surface" \
        -set "midi mididevice=none" \
        -c "mount c $drive" \
        -c "c:" \
        -c "CALL C:\\RAVI\\RAVILOAD.BAT" \
        -c "exit" >"$drive/DOSBOX.OUT" 2>&1
    [[ -f "$drive/RAVI/ROLLED.OK" ]]
    [[ -f "$drive/RAVI/DOSRAVI.BAD" ]]
    [[ ! -f "$drive/RAVI/UPDATE.PND" ]]
    echo "DOSBox-X unconfirmed-update boot rollback passed"
}

run_cpu() {
    local cpu=$1
    local drive="$test_root/$cpu"
    mkdir -p "$drive"
    cp "$agent" "$drive/DOSRAVI.COM"
    cp "$probe" "$drive/COMPROBE.COM"
    nasm -f bin "$project_root/tests/HELLO.ASM" -o "$drive/HELLO.COM"
    local port
    port=$(python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)
    PYTHONPATH="$project_root" python3 "$project_root/tests/dosbox_integration.py" "$port" "$drive" &
    local host_pid=$!
    local listen_tries=0
    while [[ ! -f "$drive/LISTEN.FLG" && $listen_tries -lt 100 ]]; do
        sleep 0.05
        listen_tries=$((listen_tries + 1))
    done
    [[ -f "$drive/LISTEN.FLG" ]] || {
        kill "$host_pid" 2>/dev/null || true
        echo "host integration listener did not start" >&2
        return 1
    }
    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy dosbox-x -silent -fastlaunch \
        -set "dosbox quit warning=false" \
        -set "sdl output=surface" \
        -set "cpu cputype=$cpu" \
        -set "cpu cycles=max" \
        -set "midi mididevice=none" \
        -set "serial serial1=nullmodem server:127.0.0.1 port:$port transparent:1 telnet:0 usedtr:0 rxdelay:0 txdelay:0" \
        -c "mount c $drive" \
        -c "c:" \
        -c "COMPROBE > PROBE.TXT" \
        -c "ECHO READY>READY.FLG" \
        -c "DOSRAVI /COM1 /BAUD:38400 /ROOT:. > AGENT.TXT" \
        -c "DOSRAVI /COM1 /BAUD:38400 /ROOT:. >> AGENT.TXT" \
        -c "exit" >"$drive/DOSBOX.OUT" 2>&1 &
    local dosbox_pid=$!
    set +e
    timeout 60s tail --pid="$host_pid" -f /dev/null
    local host_status=$?
    wait "$host_pid"
    if [[ $? -ne 0 ]]; then host_status=1; fi
    if [[ $host_status -ne 0 ]]; then
        kill "$dosbox_pid" 2>/dev/null || true
    fi
    wait "$dosbox_pid"
    local dosbox_status=$?
    set -e
    if [[ $host_status -ne 0 || $dosbox_status -ne 0 ]]; then
        find "$drive" -maxdepth 1 -type f -printf '%f %s bytes\n' >&2
        if [[ -f "$drive/AGENT.TXT" ]]; then
            sed -n '1,120p' "$drive/AGENT.TXT" >&2
        fi
        sed -n '1,240p' "$drive/DOSBOX.OUT" >&2
        return 1
    fi
    grep -q 'COM1: base' "$drive/PROBE.TXT"
    grep -q 'internal loopback' "$drive/PROBE.TXT"
    echo "DOSBox-X $cpu serial integration passed"
}

test_boot_rollback
run_cpu 8086
run_cpu 80186

#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd "$(dirname "$0")/.." && pwd)
agent="$project_root/build/dos/DOSRAVI.COM"
probe="$project_root/build/dos/COMPROBE.COM"
next_agent="$project_root/build/dos/DOSNEXT.COM"
file_test="$project_root/build/dos/FILETEST.COM"

[[ -f "$agent" && -f "$probe" && -f "$next_agent" && -f "$file_test" ]] || {
    echo "DOS programs are missing; run make dos" >&2
    exit 1
}
command -v dosbox-x >/dev/null
command -v nasm >/dev/null

test_root=$(mktemp -d /tmp/dosravi-dos-test.XXXXXX)
trap 'rm -rf "$test_root"' EXIT

test_dos_file_shim() {
    local drive="$test_root/file-shim"
    mkdir -p "$drive"
    cp "$file_test" "$drive/FILETEST.COM"
    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy dosbox-x -silent -fastlaunch \
        -set "dosbox quit warning=false" \
        -set "sdl output=surface" \
        -set "cpu cputype=8086" \
        -set "cpu cycles=max" \
        -set "midi mididevice=none" \
        -c "mount c $drive" \
        -c "c:" \
        -c "FILETEST > FILETEST.OUT" \
        -c "exit" >"$drive/DOSBOX.OUT" 2>&1
    if [[ ! -f "$drive/FILE.OK" || $(stat -c %s "$drive/FILE.BIN") -ne 65536 ]]; then
        cat "$drive/FILETEST.OUT" >&2
        stat -c 'FILE.BIN host size: %s' "$drive/FILE.BIN" >&2
        return 1
    fi
    echo "DOS 32-bit file shim passed"
}

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

test_local_quit() {
    local drive="$test_root/local-quit"
    mkdir -p "$drive/RAVI"
    cp "$agent" "$drive/RAVI/DOSRAVI.COM"
    nasm -f bin "$project_root/tests/KEYQUIT.ASM" -o "$drive/RAVI/KEYQUIT.COM"
    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy dosbox-x -silent -fastlaunch \
        -set "dosbox quit warning=false" \
        -set "sdl output=surface" \
        -set "cpu cputype=8086" \
        -set "cpu cycles=max" \
        -set "midi mididevice=none" \
        -c "mount c $drive" \
        -c "c:" \
        -c "CD \\RAVI" \
        -c "KEYQUIT" \
        -c "DOSRAVI /COM1 /BAUD:38400 /ROOT:C:\\RAVI /BASE:3F8 > STARTUP.TXT" \
        -c "ECHO RETURNED>RETURN.OK" \
        -c "exit" >"$drive/DOSBOX.OUT" 2>&1
    grep -q 'DOSRAVI 0.1.1' "$drive/RAVI/STARTUP.TXT"
    grep -q 'BUILD uart-txdiag-v1 FIFO' "$drive/RAVI/STARTUP.TXT"
    grep -q 'COM1 38400 BAUD 8N1 BASE 03f8' "$drive/RAVI/STARTUP.TXT"
    grep -q 'ROOT C:\\RAVI' "$drive/RAVI/STARTUP.TXT"
    grep -q 'LOCAL QUIT' "$drive/RAVI/STARTUP.TXT"
    [[ -f "$drive/RAVI/RETURN.OK" ]]
    echo "DOSBox-X startup banner and local Ctrl+C quit passed"
}

run_cpu() {
    local cpu=$1
    local mount="$test_root/$cpu"
    local drive="$mount/RAVI"
    mkdir -p "$drive"
    cp "$agent" "$drive/DOSRAVI.COM"
    cp "$next_agent" "$drive/DOSNEXT.COM"
    cp "$probe" "$drive/COMPROBE.COM"
    cp "$project_root/dos/RAVI.BAT" "$drive/RAVI.BAT"
    cp "$project_root/dos/RAVILOAD.BAT" "$drive/RAVILOAD.BAT"
    nasm -f bin "$project_root/tests/HELLO.ASM" -o "$drive/HELLO.COM"
    nasm -f bin "$project_root/tests/SLOW.ASM" -o "$drive/SLOW.COM"
    nasm -f bin "$project_root/tests/STDIN.ASM" -o "$drive/STDIN.COM"
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
        -c "mount c $mount" \
        -c "c:" \
        -c "CD \\RAVI" \
        -c "COMPROBE > PROBE.TXT" \
        -c "ECHO READY>READY.FLG" \
        -c "CALL RAVI.BAT" \
        -c "ECHO RETURNED>RETURN.OK" \
        -c "exit" >"$mount/DOSBOX.OUT" 2>&1 &
    local dosbox_pid=$!
    set +e
    timeout 180s tail --pid="$host_pid" -f /dev/null
    local host_status=$?
    if [[ $host_status -ne 0 ]]; then
        kill "$host_pid" "$dosbox_pid" 2>/dev/null || true
    fi
    wait "$host_pid"
    if [[ $? -ne 0 ]]; then host_status=1; fi
    if [[ $host_status -eq 0 ]]; then
        local return_tries=0
        while [[ ! -f "$drive/RETURN.OK" && $return_tries -lt 100 ]]; do
            sleep 0.05
            return_tries=$((return_tries + 1))
        done
        [[ -f "$drive/RETURN.OK" ]] || host_status=1
    fi
    local forced_stop=0
    if kill -0 "$dosbox_pid" 2>/dev/null; then
        forced_stop=1
        kill "$dosbox_pid" 2>/dev/null || true
    fi
    if [[ $host_status -ne 0 ]]; then
        echo "DOS agent did not complete or return cleanly" >&2
    fi
    wait "$dosbox_pid"
    local dosbox_status=$?
    if [[ $forced_stop -eq 1 && $host_status -eq 0 ]]; then dosbox_status=0; fi
    set -e
    if [[ $host_status -ne 0 || $dosbox_status -ne 0 ]]; then
        find "$drive" -maxdepth 1 -type f -printf '%f %s bytes\n' >&2
        sed -n '1,240p' "$mount/DOSBOX.OUT" >&2
        return 1
    fi
    grep -q 'COM1: base' "$drive/PROBE.TXT"
    grep -q 'internal loopback' "$drive/PROBE.TXT"
    echo "DOSBox-X $cpu serial integration passed"
}

test_dos_file_shim
test_boot_rollback
test_local_quit
run_cpu 8086
run_cpu 80186

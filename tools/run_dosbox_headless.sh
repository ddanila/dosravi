#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd "$(dirname "$0")/.." && pwd)
port=${1:-5000}
runtime="$project_root/build/headless"
drive="$runtime/drive"
pid_file="$runtime/dosbox.pid"
log="$runtime/dosbox.log"

case "$port" in
    ''|*[!0-9]*) echo "port must be an integer" >&2; exit 2 ;;
esac
if ((port < 1 || port > 65535)); then
    echo "port must be between 1 and 65535" >&2
    exit 2
fi
if [[ -f "$pid_file" ]]; then
    old_pid=$(<"$pid_file")
    if [[ "$old_pid" =~ ^[0-9]+$ ]] && kill -0 "$old_pid" 2>/dev/null; then
        echo "headless DOSBox-X is already running (PID $old_pid)" >&2
        exit 1
    fi
fi

mkdir -p "$drive/RAVI"
cp "$project_root/build/dos/DOSRAVI.COM" "$drive/RAVI/DOSRAVI.COM"
cp "$project_root/build/dos/COMPROBE.COM" "$drive/RAVI/COMPROBE.COM"
cp "$project_root/dos/RAVILOAD.BAT" "$drive/RAVI/RAVILOAD.BAT"

printf '%s\n' "$BASHPID" >"$pid_file"
echo "starting headless DOSBox-X: PID $BASHPID, TCP 127.0.0.1:$port"
echo "log: $log"
exec env SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy dosbox-x \
    -silent -fastlaunch \
    -set "dosbox quit warning=false" \
    -set "sdl output=surface" \
    -set "cpu cputype=8086" \
    -set "cpu cycles=max" \
    -set "midi mididevice=none" \
    -set "serial serial1=nullmodem port:$port transparent:1 telnet:0 usedtr:0 rxdelay:0 txdelay:0" \
    -c "mount c $drive" \
    -c "c:" \
    -c "cd \\RAVI" \
    -c "CALL RAVILOAD.BAT" \
    >"$log" 2>&1 </dev/null

# DOSRAVI

DOSRAVI is a reliable remote-control and file-transfer environment for
8086-compatible MS-DOS machines.  A Python host uploads files, runs a child
program through a foreground `DOSRAVI.COM` agent, captures DOS stdout/stderr,
and retrieves verified artifacts.  The first hardware target is a Pocket8086
connected through a null-modem RS-232 cable; the first showcase is the
read-only Willem programmer workflow described in [`PLAN.md`](PLAN.md).

The wire protocol is transport-independent.  Physical serial ports use raw
8N1; DOSBox-X can expose its null-modem UART as a TCP socket.  The host library
contains no POSIX details above the transport layer.

The DOS console shows terse logical activity such as `PING PONG`,
`PUT INPUT.BIN 4096`, `GET READ.BIN`, and `EXEC WILLEM.COM` followed by
`EXIT 0`. Checksums, offsets, arguments, JSON, payloads, and repeated chunks
stay off the slow local display. Command-line option names are case-insensitive.

For a persistent emulator agent with no window, X server, sound, or MIDI:

```sh
make dosbox-headless
dosravi --tcp 127.0.0.1:5000 info
```

The launcher uses SDL dummy video/audio drivers and records the PID and log in
`build/headless/`. It stays in the foreground; run host commands from another
shell and use Ctrl-C to stop it. Pass another TCP port directly to
`tools/run_dosbox_headless.sh` when 5000 is occupied.

## Host usage

Python 3.10 or newer is required and there are no runtime dependencies.

```sh
python3 -m pip install -e .
dosravi --serial /dev/ttyUSB0 --baud 38400 ping
dosravi --tcp 127.0.0.1:5000 info
dosravi --serial /dev/ttyUSB0 --baud 38400 link-test --size 1048576 --passes 10

# Build WILLEM.COM from https://github.com/ddanila/willem-v30 first.
dosravi --serial /dev/ttyUSB0 run \
  --put WILLEM.COM:WILLEM.COM \
  --exec "WILLEM.COM R2764 READ.BIN 378" \
  --get READ.BIN --get WILLEM.LOG

dosravi --serial /dev/ttyUSB0 willem-sweep \
  --program WILLEM.COM \
  --device 2764 \
  --profiles conservative,address2,oe2,latch2,balanced,address1,oe1,latch1,fast,powerfast \
  --output sessions/2764-sweep \
  --note programmer-revision=PCB5.0E \
  --note machine=Pocket8086 \
  --note chip-marking=RECORD-COMPLETE-MARKING \
  --note datasheet=RECORD-EXACT-DOCUMENT-REVISION \
  --note supply=RECORD-MEASURED-VOLTAGE \
  --note socket=RECORD-POSITION-AND-ORIENTATION \
  --note dip-switches=RECORD-ALL-SWITCHES \
  --note cable-adapter=RECORD-LPT-AND-SERIAL-HARDWARE
```

Ordinary frame retries use `--timeout`; a received EXEC `STARTED` event switches
to the separate bounded `--exec-timeout` (300 seconds by default) without
retransmitting while the DOS child is running.
Session runners persist execution IDs before launch. Generic one-off `exec` and
`run` also accept `--execution-id 0x...` when an external workflow owns the
restart journal.
`run --stdin RESPONSES.TXT` uploads a bounded file as child DOS handle 0; this
supports reviewed answers to legacy prompts without providing an interactive
terminal or using the laptop keyboard.

`run` creates a session directory containing raw RX/TX streams, a decoded
transaction log, stdout/stderr, requested artifacts, hashes, timings, source
identity (including dirty-worktree state), and connection metadata. Failed
runs retain their partial trials and host error. `willem-read` enforces the
ten-run acceptance gate and rejects mismatching, trusted-image-disagreeing,
all-zero, and all-FF captures.
`willem-sweep` treats profile order as conservative-to-aggressive, stops at
the first failing profile, repeats the conservative profile to detect drift,
and reruns the timing step below the fastest passing profile as the proposed
production baseline.  Willem must emit a structured
`DOSRAVI_METRIC read_ms=N profile=NAME` line from its local PIT timing; host
EXEC wall time is never substituted for programmer speed.
For M4 only, `willem-read --legacy-current` accepts the unmodified Willem 0.0.5
append-log format and reports its coarse local power-on-to-safe-shutdown window.
It is labeled as legacy timing and is not used for optimized-profile claims.

Programming is deliberately narrower than reading. `willem-write` accepts
only `28C64`, requires `--write`, uploads a reviewed `WRITE.OK` token, and
requires recorded `endurance`, `erase-requirements`, and `chip-marking` notes.
It accepts the result only when `WILLEM.LOG` contains a structured
`DOSRAVI_WRITE_METRIC` record followed by proof of VCC/VPP shutdown, then runs
ten full reads against the requested image using the selected read profile.

The agent can update itself without touching the laptop:

```sh
dosravi --serial /dev/ttyUSB0 update build/dos/DOSRAVI.COM --expect-version 0.1.0
```

The host uploads and verifies `DOSRAVI.NEW`, stages it, waits for the launcher
to start the replacement, checks its INFO response, and confirms it.
`DOSRAVI.OLD` remains available.  A reset before confirmation makes
`RAVILOAD.BAT` restore that fallback automatically.

The launcher defaults to COM1 at 38400 baud. During link characterization it
can preserve another rate across replacement restarts, for example:

```dos
CALL C:\RAVI\RAVILOAD.BAT /COM1 /BAUD:19200 /ROOT:C:\RAVI
```

On the recorded Pocket8086 plus CP2102/MAX RS-232 setup, sustained transfers
work through 57,600 baud and 115,200 is rejected. Use 57,600 for the current
soak and production trials; this is setup-specific, not a universal default.

The hidden `--reference-root` transport runs the native reference agent and is
used only by integration tests.

## DOS build and installation

The DOS build requires Bruce Evans' `bcc`, `as86`/`ld86`, and NASM, matching
the `willem-v30` toolchain.

```sh
make test
make dos
make dos-test
make dist
```

Copy the contents of `build/dist` to `C:\RAVI`, add this line to
`AUTOEXEC.BAT`, and reboot:

```dos
C:\RAVI\DOSRAVI.COM /COM1 /BAUD:38400 /ROOT:C:\RAVI
```

Start at 9,600 baud for first physical bring-up.  Characterize each real UART,
cable, and USB-RS232 adapter before raising the rate.  A USB-TTL adapter must
never be connected directly to a PC RS-232 port.

The DOS agent uses ordinary DOS services for workspace and process behavior.
It accesses the UART directly and uses a small INT 21h file shim only where the
dev86 C runtime truncates file positions at its signed 32 KiB boundary.

The exact protocol is in [`docs/protocol.md`](docs/protocol.md), safety and
recovery invariants in [`docs/safety.md`](docs/safety.md), and physical details
which must be recorded before use in [`docs/hardware.md`](docs/hardware.md).

DOSRAVI is licensed under GPL-2.0-only.

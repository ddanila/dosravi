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

dosravi --serial /dev/ttyUSB0 run \
  --put ../willem-v30/build/dos/WILLEM.COM:WILLEM.COM \
  --exec "WILLEM.COM R2764 READ.BIN 378" \
  --get READ.BIN --get WILLEM.LOG

dosravi --serial /dev/ttyUSB0 willem-sweep \
  --program ../willem-v30/build/dos/WILLEM.COM \
  --device 2764 --profiles conservative,balanced,fast \
  --output sessions/2764-sweep \
  --note programmer=PCB5.0E --note chip-marking=RECORD-COMPLETE-MARKING
```

`run` creates a session directory containing raw RX/TX streams, a decoded
transaction log, stdout/stderr, requested artifacts, hashes, timings, source
identity, and connection metadata.  `willem-read` enforces the ten-run
acceptance gate and rejects mismatching, trusted-image-disagreeing, all-zero,
and all-FF captures.
`willem-sweep` treats profile order as conservative-to-aggressive, stops at
the first failing profile, repeats the conservative profile to detect drift,
and reruns the timing step below the fastest passing profile as the proposed
production baseline.  Willem must emit a structured
`DOSRAVI_METRIC read_ms=N profile=NAME` line from its local PIT timing; host
EXEC wall time is never substituted for programmer speed.

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

The exact protocol is in [`docs/protocol.md`](docs/protocol.md), safety and
recovery invariants in [`docs/safety.md`](docs/safety.md), and physical details
which must be recorded before use in [`docs/hardware.md`](docs/hardware.md).

DOSRAVI is licensed under GPL-2.0-only.

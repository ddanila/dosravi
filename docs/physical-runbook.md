# Pocket8086 physical runbook

This runbook deliberately separates initial hands-on wiring from subsequent
host-only experiments. Do not claim a milestone from emulator output.

## 1. Record and inspect before power

Copy `docs/hardware.md` into the first session notes. Record the Pocket8086
connector/gender, programmer revision and supply, adapter identities, cable
pinout, and complete chip markings. Confirm that both ends are true RS-232;
never connect a USB-TTL UART to the native PC serial port.

Build and validate the install directory:

```sh
make verify
```

The files to place initially in `C:\RAVI` are under `build/dist`. Review
`HWSETUP.TXT` and `RAVILOAD.BAT` before enabling its AUTOEXEC line.

On the already characterized Pocket8086 plus CP2102/MAX/null-modem setup,
start the production agent without options by typing `RAVI`. Its wrapper fixes
COM1, 57,600 baud, and `C:\RAVI`; the startup banner makes those effective
settings visible. Press `Ctrl+C` or `Esc` for a local clean exit.

## 2. UART loopback characterization

With the programmer disconnected and an RS-232 external loopback plug fitted,
run this locally once and retain `PROBE.TXT`:

```dos
C:
CD \RAVI
COMPROBE /EXTERNAL > PROBE.TXT
```

It tests 9,600, 19,200, 38,400, 57,600, and 115,200 baud and restores readable
UART state. Remove the loopback plug, attach the documented null-modem cable and
USB-RS232 adapter, then start at the lowest passing rate. Adjust the baud in
`RAVILOAD.BAT` during this initial bring-up only.

## 3. Full-protocol ceiling

For each candidate baud, run deterministic round trips and retain the session:

```sh
dosravi --serial /dev/ttyUSB0 --baud 9600 \
  --session-dir sessions/link-9600 link-test --size 1048576 --passes 10 \
  --note machine=Pocket8086 \
  --note cable-adapter=RECORD-CABLE-AND-USB-RS232
```

Increase one baud step at a time. The reliable ceiling requires every returned
hash to match; use a slower production rate if the ceiling is marginal.

## 4. Current Willem baseline

First run the empty-socket diagnostic with reviewed newline-separated prompt
responses supplied through file-backed stdin. Physically perform and record
each requested meter/connection check; a canned emulator response is not valid
physical evidence. Retrieve `WILLEM.LOG` and `WTRACE.BIN` and confirm the final
VCC/VPP-off line.

Then use `willem-read --legacy-current` for exactly ten reads of an already
supported known chip. Supply all required notes and `--trusted` when an
established image exists. This mode reports the unmodified Willem 0.0.5 local
logging-inclusive time window and never labels it an optimized profile.

## 5. Profile and new-device work

Only after M4 passes, use audited `/PROFILE:NAME` builds and `willem-sweep`.
Stop at the first failure, retain the failed session, rerun the conservative
profile for drift, and accept production only one step slower than the fastest
10/10 profile.

The initial `willem-v30` development branch is `dosravi-timing-profiles` at
commit `589033f`. Its adjacent one-variable sequence is:

```text
conservative,address2,oe2,latch2,balanced,address1,oe1,latch1,fast,powerfast
```

Build that exact branch and record its resulting `WILLEM.COM` SHA-256. The
tables and their structured PIT metrics pass 8086/80186 DOSBox-X and a complete
headless DOSRAVI upload/execute/retrieve integration, but none is physically
accepted yet.

РФ5 work remains read-only until the complete marking and exact datasheet
determine capacity, pinout, voltage, socket placement, DIP settings, and timing.
Writing remains locked to the documented 28C64 workflow, explicit `--write`,
reviewed `WRITE.OK`, endurance/erase notes, complete verification, and one
fresh post-write read. Repeated reads remain an explicit experiment, not the
standard write path.

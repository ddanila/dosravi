# DOSRAVI project plan

Status: software/emulator implementation verified; physical milestones pending

The current evidence and the exact hardware gates are tracked in
[`docs/status.md`](docs/status.md). Passing emulator tests does not mark a
physical milestone complete.

## Purpose

DOSRAVI is a serial remote-control and file-transfer environment for
8086-compatible MS-DOS computers. Its first physical target is the Pocket8086
used by `willem-v30`, connected to the development host through a null-modem
RS-232 link.

The first showcase is a short development loop for the Willem programmer,
culminating in read-only support for one or more РФ5 chips:

1. build `WILLEM.COM` on the modern host;
2. upload it and any input images to the Pocket8086;
3. execute it next to the real LPT-connected programmer;
4. retrieve ROM dumps, `WILLEM.LOG`, and `WTRACE.BIN`;
5. compare results, adjust the implementation or timing, and repeat.

After DOSRAVI has been installed and started, normal experiments must be
controlled entirely from the modern host. The laptop keyboard and display are
not part of the normal loop. The host must receive the executed program's
captured console output, DOS exit status, Willem log, ROM image, and any
requested trace.

All timing-sensitive programmer operations remain inside `WILLEM.COM`. DOSRAVI
must not proxy individual LPT operations over serial, because serial latency
would change the hardware protocol being measured.

The intended GitHub home is a separate public repository named
`ddanila/dosravi`. The project stays independent of `willem-v30` so that it can
later support other DOS software and machines. Once the generic workflow is
stable, `willem-v30` may add thin Make targets or scripts that invoke DOSRAVI.

## Goals

- Run as a small 8086-compatible foreground `.COM` program under MS-DOS 6.22.
- Use the Pocket8086's native serial port at the fastest physically reliable
  rate.
- Reliably upload programs and input files, execute them, and retrieve their
  results without moving disks between machines.
- Operate the laptop from the host without typing commands or inspecting
  results on the laptop screen during a normal run.
- Capture the DOS child's standard output and standard error, in addition to
  retrieving application-created logs and binary artifacts.
- Recover from link interruption, duplicate frames, a restarted host process,
  and partially transferred files.
- Update the DOS agent remotely without laptop interaction, while retaining
  the last agent binary as an automatic boot-time fallback until the new
  version has started, answered the host, and been explicitly confirmed.
- Record enough metadata to reproduce physical Willem experiments.
- Separate serial-link performance from Willem read/program performance.
- Make repeated physical trials cheap enough that reliability can be measured,
  rather than inferred from one successful run.
- Reuse the proven 8086 C89, `bcc`, NASM, DOSBox-X, and distribution practices
  established by `willem-v30`.

## Initial non-goals

- A TSR or background server that remains active while unrelated DOS software
  runs.
- Interactive remote desktop or a general terminal emulator.
- Proxying timing-sensitive ISA/LPT I/O over the serial link.
- Arbitrary memory writes, remote reboot, or unrestricted deletion.
- Automatically weakening any hardware-write safety gate.
- Replacing `WILLEM.COM` with host-side programmer logic.

## System shape

```text
Modern development host                    Pocket8086 / MS-DOS

source -> build -> DOSRAVI host CLI  <-->  DOSRAVI.COM -> EXEC WILLEM.COM
                  session records          COM port       LPT programmer
                  returned artifacts                      physical chip
```

### Modern host

A Python CLI will:

- open a physical serial device or an emulator transport;
- upload and download files with checksums and bounded retries;
- invoke a DOS program and collect its exit status;
- run repeatable multi-pass experiments;
- store raw RX/TX logs and a decoded JSON session record;
- verify returned artifacts before reporting success; and
- provide a library/API underneath the CLI so `willem-v30` can add small
  project-specific wrappers without copying transport code.

The first host implementation may use POSIX `termios`, as Jukuravi does. The
transport interface should not expose POSIX details to the protocol or command
layers, leaving room for Windows serial support later.

### DOS agent

`DOSRAVI.COM` will:

- target the 8086 instruction set and tiny memory model;
- remain a thin foreground transport/EXEC agent: orchestration, policy,
  experiment analysis, and artifact hashing stay on the modern host;
- use direct 8250-compatible UART I/O for useful throughput;
- discover conventional COM base addresses from the BIOS data area, while
  allowing an explicit base address;
- preserve the original UART state and restore it on normal exit;
- accept command-line option names case-insensitively and show terse one-line
  command activity with only the most useful filename, size, or exit status on
  the local DOS console;
- restrict file operations to a configured workspace such as `C:\RAVI`;
- write uploads to temporary files and rename them only after complete
  verification;
- cache only one verified download identity, invalidating it before every
  operation that can mutate workspace files, so GET does not rescan a complete
  file before each 512-byte chunk;
- use DOS 32-bit file positions rather than the C runtime's signed 32 KiB
  boundary, and a 64-byte nibble table for whole-file CRC efficiency;
- execute child `.COM`/`.EXE` programs with a normal DOS command tail; and
- temporarily redirect and capture the child's DOS standard output and
  standard error, restore the original DOS handles afterward, and return the
  child's output and DOS exit status when control comes back.
- support a two-phase self-update: verify an uploaded replacement, preserve the
  currently running binary as `DOSRAVI.OLD`, exit through a small launcher,
  start the replacement as `DOSRAVI.COM`, and retain or automatically restore
  the fallback when the new agent is not confirmed.

The initial installation is a foreground invocation from `AUTOEXEC.BAT`, so a
normal boot reaches a host-accessible agent without using the laptop keyboard,
for example:

```dos
DOSRAVI /COM1 /BAUD:38400 /ROOT:C:\RAVI
```

If an executed child hangs or corrupts DOS, the operator resets the laptop.
`AUTOEXEC.BAT` then restarts DOSRAVI and the host reconnects. A TSR design can
be evaluated later, after the foreground protocol is proven.

## Proposed v0.1 commands

| Command | Purpose |
|---|---|
| `PING` | Confirm protocol liveness without changing DOS state. |
| `INFO` | Report versions, DOS/machine details, COM base, UART capabilities, free memory, and free workspace disk space. |
| `LIST` | Enumerate files in the restricted workspace. |
| `PUT` | Upload or resume one file, then commit it after whole-file verification. |
| `GET` | Download a file with offset and checksum verification. |
| `CRC` | Return size and CRC-32 for a workspace file without transferring it. |
| `REMOVE` | Remove one explicitly named regular file inside the workspace. No wildcards or recursive deletion. |
| `EXEC` | Execute a named workspace program with arguments; report start acknowledgement, captured stdout/stderr, and final DOS exit status. |
| `UPDATE` | Verify and stage an uploaded agent, preserve the old binary, exit through the launcher, reconnect to the new agent, and confirm or roll back. |
| `QUIT` | Restore the UART and return to the DOS prompt. |

`EXEC` captures DOS handle 1 and handle 2 into per-execution workspace files.
The agent restores its original handles before sending the completion response.
The host then downloads both captures together with explicitly requested
application artifacts such as `WILLEM.LOG`, `WTRACE.BIN`, and the ROM image.
Programs that write directly to video memory or exclusively through BIOS video
services cannot be captured by DOS handle redirection; Willem's normal logged
and standard-output messages are the initial supported path.

`UPDATE` is a host-orchestrated two-phase operation, not an unrestricted rename
command. The host uploads `DOSRAVI.NEW` with normal `PUT` verification, sends
the expected size and CRC-32, and requests staging. The old agent renames the
current `DOSRAVI.COM` to `DOSRAVI.OLD`, promotes the verified new file, writes
an update-pending marker, restores the UART, and exits with the launcher's
reserved restart status. `RAVILOAD.BAT` immediately invokes the promoted
agent. The host reconnects, checks `PING` and `INFO`, and sends
`UPDATE_CONFIRM`, which removes the pending marker but keeps `DOSRAVI.OLD` as
the fallback. If the replacement exits, hangs, or the machine resets before
confirmation, the launcher restores `DOSRAVI.OLD` on the next boot. A connected
host may request `UPDATE_ROLLBACK` explicitly. Interrupted staging must either
leave the old binary active or leave enough marker state for deterministic
launcher rollback; it must never delete the sole known-good agent.

All commands carry a transaction identifier. Retrying an idempotent command
with the same identifier must not create a second effect. `EXEC` needs a
separate execution identifier and cached completion result so a lost final
response does not accidentally run a chip operation twice.

## Wire protocol direction

The exact bytes will be frozen in a protocol document before physical use.
The initial design is:

- binary 8N1 transport;
- COBS-delimited frames for unambiguous resynchronization;
- protocol version, frame type, flags, transaction/sequence identifier,
  payload length, payload, and CRC-16 in each frame;
- explicit file offset in every data operation;
- 512-byte conservative chunks initially, benchmarked up to 1,024 bytes;
- stop-and-wait transfer in v0.1 so DOS disk activity cannot cause the host to
  continue sending into an unbuffered 8250 UART;
- CRC-32 over each complete file;
- bounded timeouts and retries, with duplicate-frame replay; and
- a negotiated capability block so later versions can add larger windows or
  hardware flow control without changing the v0.1 contract.

The raw baud rate is independent of protocol compatibility. Begin physical
bring-up conservatively, then test 9,600, 19,200, 38,400, 57,600, and 115,200
baud. Do not assume that the UART is a FIFO-equipped 16550. The V30 should be
fast enough to poll at high rates, but the real UART, cable, adapter, and DOS
critical sections determine the reliable ceiling.

The physical connection must be RS-232 to RS-232 through a null-modem cable.
A USB-TTL UART is not electrically compatible with a native PC RS-232 port.

## Performance and reliability model

Three different rates must be measured and reported separately:

1. **Serial deployment rate**: bytes and elapsed time for uploading and
   downloading files, including protocol acknowledgements.
2. **Programmer read rate**: bytes and elapsed time measured locally on the
   Pocket8086 while `WILLEM.COM` reads the physical chip.
3. **Programmer write rate**: changed bytes, elapsed time, retries, late
   completions, and full verification time measured locally by `WILLEM.COM`.

Serial transfer time must never be included in a claimed Willem read or write
speed. Willem timings should use the hardware-clocked PIT approach already
used by `willem-v30`, not host timestamps around the remote command.

### Ten-read acceptance baseline

A candidate Willem read profile is considered repeatable only after all of the
following pass:

1. Perform ten complete reads as ten separate `WILLEM.COM` executions. Each
   execution performs its normal power-on and safe-shutdown sequence.
2. Disable full LPT tracing during speed measurements, because tracing changes
   timing. Enable it only to diagnose a failed profile.
3. Retain all ten images, logs, exit statuses, CRCs, and local elapsed times.
4. Require all ten images to be byte-for-byte identical.
5. If a trusted image exists, require every read to match it exactly.
6. Reject uniform all-`00` or all-`FF` captures and other known stuck-bus
   signatures even if they are repeatable.
7. Report minimum, median, maximum, and spread of the ten local read times.
8. Repeat the last conservative known-good profile after an aggressive sweep,
   to detect setup drift or a hardware connection that became marginal during
   testing.

Ten successful reads are a practical experimental gate, not proof that the
fastest passing setting has adequate engineering margin. After finding the
fastest 10/10 setting, select at least one slower timing step as the proposed
production baseline and run its ten-read acceptance again.

### Timing-profile sweep

Willem experiments should expose named runtime profiles or explicit diagnostic
timing parameters rather than requiring a source edit for every trial. Each
profile must record at least:

- address-shift/setup timing;
- output-enable settling time;
- input-chain latch and clock spacing;
- device power-on stabilization delay;
- write pulse and completion-poll policy, when applicable; and
- the exact `WILLEM.COM` build identity.

Change one timing dimension at a time. Start from the proven conservative
profile, make coarse reductions to find the boundary, then use finer steps.
The host runner should stop a sweep at the first mismatch, preserve the failed
artifacts, return the programmer to its safe state, and optionally rerun that
single case with tracing.

### Programming experiments

Read optimization comes first and is non-destructive. Programming experiments
must additionally:

- use only an electrically and algorithmically supported rewritable device;
- retain `willem-v30`'s explicit `/WRITE` and `WRITE.OK` gates;
- never enable VPP unless the selected device and documented procedure require
  it;
- record changed versus already-matching bytes, retry counts, late completion
  counts, programming time, and independent full-verification time;
- verify the complete programmed image, then perform ten normal reads of that
  image using the accepted read profile; and
- account for device endurance and erase requirements before scheduling
  repeated whole-chip write cycles.

Useful test images include address-derived data and alternating `AA`/`55`
patterns, because they expose address and data coupling better than a uniform
image. The exact sequence depends on the first additional physical chip and
its erase/programming rules.

## Willem showcase workflow

The first end-to-end command should be conceptually equivalent to:

```sh
make dos

python3 dosravi.py run \
  --put build/dos/WILLEM.COM:WILLEM.COM \
  --exec "WILLEM D28C64 378" \
  --get WILLEM.LOG
```

A repeated read could become:

```sh
python3 dosravi.py willem-read \
  --program build/dos/WILLEM.COM \
  --device 2764 --lpt 378 --count 10 \
  --output sessions/2764-baseline
```

The first new-device experiment will use РФ5 chips. Before implementing the
device profile, record the complete markings and identify the exact datasheet,
capacity, programming voltage, pinout, socket placement, and Willem switch
configuration. The initial РФ5 milestone is strictly read-only.

The project-specific convenience command is not part of the wire protocol. It
is orchestration built from generic `PUT`, `EXEC`, `GET`, and `CRC` operations.

Every physical session directory should contain:

- host and DOSRAVI versions;
- source commit and `WILLEM.COM` SHA-256;
- complete DOS command line and timing profile;
- serial device, baud rate, and negotiated protocol parameters;
- raw serial RX and TX;
- decoded transaction log;
- DOS exit status;
- captured child standard output and standard error;
- local programmer timings reported by Willem;
- every returned image, `WILLEM.LOG`, and requested trace;
- size, CRC-32, and SHA-256 of every host-side artifact; and
- free-form hardware notes such as programmer revision, chip marking, supply,
  DIP configuration, and adapter/cable identity.

## Development and test strategy

### Native tests

- Build the protocol core as ordinary host C and test framing, CRCs, duplicate
  transactions, truncated frames, corrupt frames, offsets, and path rejection.
- Test the Python protocol implementation against the same fixtures.
- Fuzz frame decoding and confirm that arbitrary corruption always returns to
  a bounded resynchronization state.

### DOS emulator tests

- Build with the `bcc` + NASM tiny-model toolchain already installed for
  `willem-v30`.
- Run `DOSRAVI.COM` as 8086 and 80186/V30-compatible configurations in
  DOSBox-X.
- Connect the real Python host implementation through DOSBox-X null-modem
  transport.
- Exercise upload, interrupted upload/resume, download, duplicate commands,
  child execution, exit status, output collection, and reconnect.
- Add injected loss, corruption, duplicate, and delayed-response cases before
  trusting the physical link.

### Physical tests

- First use an RS-232 loopback plug to identify the UART and establish reliable
  baud rates without involving the Willem programmer.
- Transfer deterministic large files repeatedly and compare complete hashes.
- Run the current, already-understood Willem diagnostic before changing any
  programmer code.
- Run an existing known-chip read and compare it with the established expected
  image.
- Only then begin timing sweeps or support for additional devices.

## Milestones

### M0: Repository and contracts

- Create the Git repository and public GitHub repository.
- Select the license; GPL-2.0-only is the current proposal to align with
  `willem-v30` reuse.
- Add project layout, build rules, protocol draft, safety model, and CI.

### M1: UART characterization

- Build `COMPROBE.COM`.
- Discover COM1/COM2 bases and distinguish relevant 8250/16450/16550 features.
- Test internal/external loopback and measure the physical baud ceiling.
- Record the Pocket8086 connector and null-modem pinout.
- Current physical result: COM1/03F8h with a 16550A-compatible FIFO and the
  CP2102/MAX RS-232 path is accepted at 57,600 baud after three zero-retry,
  hash-verified 32 KiB round trips; 115,200 is rejected after repeated
  512-byte PUT timeouts.

### M2: Protocol and emulator loop

- Implement framing and CRCs in DOS C and Python.
- Establish `PING`/`INFO` over DOSBox-X null-modem transport.
- Add transaction replay, timeouts, raw logs, and corruption tests.

### M3: Deploy, execute, collect

- Implement safe workspace handling, `PUT`, `GET`, `CRC`, and `REMOVE`.
- Implement replay-safe `EXEC` with start and completion responses.
- Execute a harmless uploaded `.COM` fixture and retrieve its captured standard
  output, standard error, and file output without using the emulated DOS
  keyboard or display.
- Exercise a complete two-phase agent update in DOSBox-X, prove the replacement
  answers before confirmation, prove the old binary remains available, and
  prove an unconfirmed replacement is rolled back by the launcher.

### M4: Current Willem acceptance

- Deploy the unchanged current `WILLEM.COM`.
- Run a safe diagnostic and retrieve its log/trace.
- Read an already-supported known chip ten times.
- Confirm byte identity, expected-image identity, safe shutdown, and timing
  statistics.

### M5: Speed characterization

- Add runtime-selectable experimental read timing profiles to a Willem branch.
- Automate conservative-to-aggressive sweeps.
- Identify the fastest 10/10 setting and validate a slower guarded baseline.
- Keep failure evidence and confirm the conservative baseline again afterward.

### M6: РФ5 read-only showcase

- Inventory the physical РФ5 chips and record their complete markings.
- Identify the exact device datasheet and derive the socket, switch, power,
  address, and read-timing requirements without assuming compatibility from
  the short family name alone.
- Establish a trustworthy reference when possible, using a known dump, another
  programmer, or agreement among multiple independently read chips.
- Implement read-only support in a Willem development branch.
- Iterate through DOSRAVI until ten repeatable reads pass.
- Record DIP/socket/power configuration and the accepted timing profile.
- Promote the proven implementation, virtual tests, and documentation into
  standalone `willem-v30`.

### M7: Controlled write characterization

- Select a suitable rewritable device and define its endurance-aware test
  sequence.
- Preserve all existing write authorization and safe-shutdown gates.
- Measure programming and verification separately.
- Follow successful programming with ten accepted reads.
- Promote only physically repeatable algorithms and guarded timing profiles.

## Open decisions

- Record the exact Pocket8086 connector/gender and null-modem pinout;
  COM1/03F8h, the 16550A-compatible FIFO, the CP2102/MAX RS-232 adapter, and
  the accepted 57,600-baud protocol rate are already physically established.
- Record the complete markings of the available РФ5 chips and identify
  whether a trusted dump or second programmer is available for comparison.
- Confirm the public `dosravi` name and GPL-2.0-only license before creating the
  GitHub repository.
- Timing-profile representation is resolved for the first read-only sweep:
  audited named tables selected by `/PROFILE:NAME`, with exact parameters and
  local PIT timing logged. Normal commands do not expose arbitrary write/VPP
  timing values.
- Decide whether completely unattended recovery from a hung child is required.
  Automatic startup removes normal keyboard/display use, but a child that never
  returns cannot be recovered by the foreground DOS agent. True no-touch crash
  recovery requires a separate reset mechanism or a carefully bounded DOS-side
  watchdog.

## Definition of the first useful release

The first release is complete when the same Python host code can talk to both
DOSBox-X and the physical Pocket8086, upload the current `WILLEM.COM`, execute
ten read-only Willem trials without using the laptop keyboard or display,
capture stdout/stderr, retrieve and verify every requested log/image/trace,
report serial and programmer timing separately, survive ordinary serial
interruptions, update the DOS agent remotely with a retained automatic
fallback, and leave the programmer in its documented safe powered-down state
after every completed or failed command.

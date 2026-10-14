# Implementation status

Status reviewed 2026-08-30. `make verify` is the local acceptance command.

| Milestone | State | Evidence or remaining gate |
|---|---|---|
| M0 repository/contracts | Verified | The public `ddanila/dosravi` repository, MIT license, layout, CI, protocol, safety model, and explicit boundary from the separately built GPL `WILLEM.COM` are established. |
| M1 UART characterization | Physical link accepted; inventory partial | Pocket8086 COM1 is 03F8h and reports a 16550A-compatible FIFO with internal and external loopback PASS. The CP2102/MAX/RS-232-to-TTL chain also passed loopback. A marginal USB cable produced requests without usable replies and one corrupted INFO byte; after cable replacement, three 4 KiB link passes and a post-restart 1 KiB pass were exact at 57,600 baud. The earlier 32 KiB soak also passed; 115,200 remains unsuitable for sustained 512-byte frames. Exact connector/pin recording remains. |
| M2 protocol/emulator | Verified | Cross-language framing fixtures, CRCs, bounded decoder, retry/replay/resume, raw logs, property tests, fault injection, and DOSBox-X TCP null-modem tests pass, including a 64 KiB round trip across the dev86 runtime's 32 KiB file-position boundary. |
| M3 deploy/execute/update | Verified | Headless 8086 and 80186 DOSBox-X runs cover interrupted PUT, resumed GET, path rejection, duplicate transaction/execution replay, child output/artifact/status collection, update confirmation, retained fallback, boot rollback, and clean launcher return. A physical two-phase update also promoted a replacement while retaining `DOSRAVI.OLD`. |
| M4 current Willem | Physical programmer path verified; legacy baseline pending | The real Willem programmed and verified five AT28C64 images through headless DOSRAVI with structured metrics and safe shutdown. The unmodified Willem 0.0.5 diagnostic also completes in emulation through file-backed stdin, with stdout/stderr, append log, and trace retrieval. Its separate legacy ten-read acceptance baseline still needs the complete programmer/cable inventory and a deliberately selected trusted read image. |
| M5 speed characterization | Emulator integration verified; hardware pending | The host sweep enforces one decreasing read dimension per adjacent table (including power stabilization), stable build identity, first-failure stop, trace rerun, drift check, and slower production reacceptance. The `willem-v30` `dosravi-timing-profiles` branch at `589033f` supplies audited tables plus local PIT read/write metrics; its binary passed 8086/80186 DOSBox-X and live headless DOSRAVI upload/EXEC/artifact parsing, including the 28C64 `powerfast` record. Physical ten-read sweeps remain required. |
| M6 РФ5 showcase | Hardware pending | No device may be inferred from the family name. Complete chip markings, exact datasheet, socket/switch/power facts, and a trustworthy reference method are required before read-only Willem support or trials. |
| M7 controlled write | AT28C64 and M2764A physical | The AT28C64B and paired image writes remain physically verified. The exact ST M2764A two-stage path also programmed four M2764AF1 devices as two EktaSoft 3.7 D15/D16 pairs. Empty-socket rails were 5.74 V VCC under the explicit marginal gate and 12.66 V VPP; every high-voltage phase shut down safely and every device passed a later trusted read at the 5.07 V normal setting. A nonblank candidate and residual bytes after an interrupted run were rejected before VPP. |

## Local verification completed

- Host C and Python tests, Hypothesis fault/property tests, serial termios tests,
  ruff, and cppcheck.
- A sanitized AFL++ decoder smoke campaign.
- Headerless 8086 DOS builds with `bcc` and NASM.
- Fully headless DOSBox-X integration using SDL dummy video and audio, with no
  X server or visible UI.
- DOS 8.3/CRLF distribution validation.

## Remaining physical inputs

For the milestones still awaiting physical closure, record:

1. Pocket8086 serial connector/gender and exact null-modem pinout plus retained
   external-loopback results. The 57,600-baud full-protocol soak now passes.
2. Willem programmer revision, supply, LPT address, cable/adapter identity, and
   current diagnostic result.
3. The supported known chip and trusted reference image for the first ten-read
   baseline.
4. Complete РФ5 markings and exact datasheet/reference-programmer information.

The completed M7 writes retained the exact chip/image identities, reviewed
`WRITE.OK` derivation, audited Willem algorithm/profile, complete verify
metrics, and safe shutdown. The Ekta4401 results were D15 CRC32 `5E306759`,
8,167 changed/25 unchanged, and D16 CRC32 `3B734DEC`, 8,173 changed/19
unchanged; both verified 8,192/8,192 with zero retries. D15's approximately
393-second child run exceeded the former 300-second host wait, but its
persistent execution ID recovered the cached success without executing twice.
D16 used a 900-second execution timeout and completed normally. The later C6
D15 result was CRC32 `A1DC319C`, 3,151 changed/5,041 unchanged; C6 D16 was
CRC32 `2D9CE4D5`, 4,529 changed/3,663 unchanged. Both verified 8,192/8,192,
reported zero retry bytes, retries, and late completions, and shut VCC/VPP off.
Their retained session names are
`at28c64-jukunet-c6-d15-write-20260818` and
`at28c64-jukunet-c6-d16-write-20260818`.

The M2764AF1 results used D15 SHA-256
`d6c4ec7418f05e5761ef450e6ee36fb2579d65d9cbf87dce265eaf1c0d077596`
and D16 SHA-256
`35b348ae7c88dc8cb24d1bc9d62a06212fdc2c2f601eddf8e00b233893d92817`.
Both D15 devices recorded 7,890 programmed and 302 FF-skipped bytes; both D16
devices recorded 6,657 programmed and 1,535 FF-skipped bytes. All used one
initial pulse per programmed byte, one matching overprogram pulse, zero
retries, a complete 8,192-byte high-voltage comparison, safe shutdown, and a
separate exact 5 V read. The accepted session pairs are
`juku37-d15-program-20260826` / `juku37-d15-final-verify-20260826`,
`juku37-d16-program-attempt2-20260826` /
`juku37-d16-final-verify-20260826`,
`juku37-d15-copy2-program-20260826` /
`juku37-d15-copy2-final-verify-20260826`, and
`juku37-d16-copy2-retry2-program-20260826` /
`juku37-d16-copy2-final-verify-20260826`.

Store each run in a dedicated session directory. A failed or interrupted
physical run remains evidence and must not be replaced by an emulator claim.
Follow [`physical-runbook.md`](physical-runbook.md) for the ordered commands.

## RAVI refactor regression gates

Before extracting shared host code, run `make check` and `make dos-test`.
`make verify` additionally retains decoder fuzzing and DOS distribution checks.
The fast tests use real PTYs/socket pairs for byte transport and deterministic
fault injection for short writes, readiness races, EOF, one write deadline,
failed setup/restore cleanup, and exact attempted-TX/received-RX logging.
Execution tests cover a bounded STARTED wait, duplicate/unrelated events,
no automatic retransmission after STARTED, and host reconnect versus target
restart. The actual DOS integration now exercises cache loss by restarting the
agent through its launcher and explicitly submitting the old execution ID.
It also guards status 85 after captured EXEC: the tested bcc cleanup path lost
that status, so normal agent shutdown now flushes stdio and terminates through
DOS directly, which closes the process handles.
That last test deliberately executes the harmless fixture twice: it documents
why an application must not automatically repeat an uncertain real operation.

CI runs on pull requests, default-branch pushes, and manual dispatch, cancelling
superseded runs. `tools/select_ci.py` skips dependencies for prose-only changes,
runs the native and actual-DOS checks for code changes, and adds the AFL smoke
campaign for C decoder/harness changes. Unknown paths or unavailable diffs run
all checks. Ordinary CI tests the physical target's 8086 instruction set;
manual dispatch and default local `make dos-test` also exercise 80186.
`DOSRAVI_TEST_CPUS=8086 make dos-test` reproduces the ordinary CI emulator gate.
The packaged Ubuntu 24.04 DOSBox-X avoids compiling an emulator in each job.

Preserve the existing wire fixtures, CLI, output artifacts, and execution
semantics during extraction. A transport writes all bytes or raises (a prefix
may already have been sent), reads up to the requested length, distinguishes
idle timeout from EOF, and never reconnects or resets a target implicitly.
Serial and TCP writes have a five-second total deadline, independent of the
previous read timeout. The logging TX stream records attempts, not delivery.

Both reference and DOS agent execution caches are volatile. Recreating the
host can recover a result while the same agent still retains its bounded cache
entry; restarting the agent loses that guarantee. There is no boot/session
identity in protocol v1 that could establish otherwise. A future shared RAVI API must expose that limit,
retain the host execution journal, and require reconciliation of unknown
outcomes rather than promise durable exactly-once execution.

New targets should implement only their supported capabilities (memory/CALL
or files/EXEC). Add a target-specific integration fixture before promoting its
backend; these DOS tests do not qualify a bare Z80 ROM, DTR heartbeat, reset
wiring, or physical serial timing. Firmware and protocol redesign are separate
from this preparatory test work.

Local validation on 2026-10-14 passed: `make check` (51 Python tests, the C
protocol tests, Ruff and cppcheck), `make fuzz`, and `make dos-test` on both
8086 and 80186. The workflow also passed actionlint. These are local test
results, not a new physical qualification or a hosted CI result.


## Shared RAVI host library

The Python transport, DOS v1 codec and client now live in
[ddanila/ravi](https://github.com/ddanila/ravi). `dosravi.client`,
`dosravi.protocol` and `dosravi.transport` retain compatibility imports, so the
CLI, agent fixture and existing tests exercise that same implementation.
The C agent, launcher, programmer workflows and qualification evidence remain
in DOSRAVI; the wire format is unchanged.

`third_party/ravi` and the wheel's Git dependency pin the same reviewed commit.
Source execution uses the submodule independent of the current directory and
rejects an already imported sibling library. Installed wheels use their declared
dependency. Initialize the submodule after cloning; update both pins together.
A pin change selects native and actual-DOS CI checks, while unchanged C decoder
code does not require another fuzz campaign.

The shared `FileTarget` interface exposes the existing file/EXEC operations and
metadata explicitly reports volatile replay scope and no remote boot identity.
See the library's [architecture](https://github.com/ddanila/ravi/blob/main/docs/architecture.md),
[target guide](https://github.com/ddanila/ravi/blob/main/docs/adding-targets.md)
and [test/update procedure](https://github.com/ddanila/ravi/blob/main/docs/testing.md).
This extraction does not qualify Robotron 1715 hardware.

Extraction validation on 2026-10-14: `make check` (51 Python tests, C protocol,
Ruff and cppcheck), DOSBox-X integration on both 8086 and 80186, and an isolated
wheel/CLI installation using the published RAVI dependency all passed.

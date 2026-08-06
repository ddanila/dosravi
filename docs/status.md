# Implementation status

Status reviewed 2026-08-07. `make verify` is the local acceptance command.

| Milestone | State | Evidence or remaining gate |
|---|---|---|
| M0 repository/contracts | Partial | Local Git repository, GPL-2.0-only text, layout, CI, protocol and safety documents exist. Public `ddanila/dosravi` creation and the name/license confirmation remain user decisions. |
| M1 UART characterization | Physical link accepted; inventory partial | Pocket8086 COM1 is 03F8h and reports a 16550A-compatible FIFO with internal loopback PASS. The CP2102/MAX RS-232 path passed three zero-retry 32 KiB hash-verified round trips at 57,600 baud; 115,200 passed short requests but failed sustained 512-byte frames. Exact connector/pin recording and external-loopback evidence remain. |
| M2 protocol/emulator | Verified | Cross-language framing fixtures, CRCs, bounded decoder, retry/replay/resume, raw logs, property tests, fault injection, and DOSBox-X TCP null-modem tests pass, including a 64 KiB round trip across the dev86 runtime's 32 KiB file-position boundary. |
| M3 deploy/execute/update | Verified | Headless 8086 and 80186 DOSBox-X runs cover interrupted PUT, resumed GET, path rejection, duplicate transaction/execution replay, child output/artifact/status collection, update confirmation, retained fallback, boot rollback, and clean launcher return. A physical two-phase update also promoted a replacement while retaining `DOSRAVI.OLD`. |
| M4 current Willem | Emulator diagnostic verified; hardware pending | The unmodified Willem 0.0.5 diagnostic completed headlessly through file-backed stdin; stdout/stderr, append log, and trace were retrieved and hashed with safe shutdown. The legacy ten-read parser exists. It still needs the real programmer, supported known chip, and trusted expected image. |
| M5 speed characterization | Emulator integration verified; hardware pending | The host sweep enforces one decreasing read dimension per adjacent table (including power stabilization), stable build identity, first-failure stop, trace rerun, drift check, and slower production reacceptance. The `willem-v30` `dosravi-timing-profiles` branch at `589033f` supplies audited tables plus local PIT read/write metrics; its binary passed 8086/80186 DOSBox-X and live headless DOSRAVI upload/EXEC/artifact parsing, including the 28C64 `powerfast` record. Physical ten-read sweeps remain required. |
| M6 РФ5 showcase | Hardware pending | No device may be inferred from the family name. Complete chip markings, exact datasheet, socket/switch/power facts, and a trustworthy reference method are required before read-only Willem support or trials. |
| M7 controlled write | Emulator integration verified; hardware pending | The host accepts only 28C64, requires `--write`, `WRITE.OK`, hardware/endurance notes, structured local write/verify metrics, safe shutdown proof, and ten accepted post-write reads. The Willem branch emits independently timed programming/verification and identity/count metrics under DOSBox-X. A specific physical device and endurance-aware sequence are still required. |

## Local verification completed

- Host C and Python tests, Hypothesis fault/property tests, serial termios tests,
  ruff, and cppcheck.
- A sanitized AFL++ decoder smoke campaign.
- Headerless 8086 DOS builds with `bcc` and NASM.
- Fully headless DOSBox-X integration using SDL dummy video and audio, with no
  X server or visible UI.
- DOS 8.3/CRLF distribution validation.

## Required physical inputs

Before M1/M4-M7 can be claimed, record:

1. Pocket8086 serial connector/gender and exact null-modem pinout plus retained
   external-loopback results. The 57,600-baud full-protocol soak now passes.
2. Willem programmer revision, supply, LPT address, cable/adapter identity, and
   current diagnostic result.
3. The supported known chip and trusted reference image for the first ten-read
   baseline.
4. Complete РФ5 markings and exact datasheet/reference-programmer information.
5. For writing, the exact 28C64 marking/datasheet, endurance and erase rules,
   reviewed `WRITE.OK`, and the audited Willem write algorithm/profile.

Store each run in a dedicated session directory. A failed or interrupted
physical run remains evidence and must not be replaced by an emulator claim.
Follow [`physical-runbook.md`](physical-runbook.md) for the ordered commands.

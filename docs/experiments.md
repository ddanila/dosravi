# Experiment rules

Serial deployment throughput and programmer operation timing are independent
measurements.  Session manifests report upload/download bytes and wall time;
Willem reports its local PIT-clocked read/program/verify intervals.  Never
describe host time around EXEC as chip speed.

An accepted read profile consists of ten separate executions, with trace off,
ten retained images/logs/statuses/CRCs/local times, byte identity across all
images, trusted-image identity when available, rejection of stuck-bus
signatures, and minimum/median/maximum/spread reporting.  After an aggressive
sweep, rerun the last conservative profile.  The proposed production profile
is at least one timing step slower than the fastest profile that passes 10/10,
and it receives its own ten-read acceptance.

Sweep one dimension at a time: address setup, OE settling, input latch/clock,
power stabilization, then write pulse/poll policy only when writing is later
authorized.  Every profile records exact values and the WILLEM.COM SHA-256.
Stop at the first mismatch, retain artifacts, ensure safe shutdown, and rerun
that case with trace only when diagnosis is requested.

Named profiles are the only normal host-facing timing interface.  The initial
representation is the read-only `/PROFILE:NAME` Willem option; profile tables
remain compiled into the audited Willem build and the log records every exact
parameter plus `DOSRAVI_METRIC read_ms=N profile=NAME`.  Normal commands do not
accept arbitrary write pulse or VPP values.  `dosravi willem-sweep` takes a
comma-separated conservative-to-aggressive list and implements the sweep,
drift check, and one-step-slower production selection rules above.

The pre-profile M4 baseline is the sole exception. `--legacy-current` parses
the last complete unmodified Willem 0.0.5 append-log run, requires READ of the
requested device with tracing off, an 8,192-byte completion, and ordered safe
shutdown, and measures the local DOS timestamp window from VCC enable through
shutdown. This coarse logging-inclusive value is never presented as an M5
optimized programmer rate.

Each profiled read must precede its metric with one exact audited record:

```text
DOSRAVI_PROFILE name=NAME address_setup_us=N oe_settle_us=N input_latch_us=N input_clock_us=N power_on_ms=N build_id=COMPILE_TIME_ID
```

The host rejects a profile-name mismatch and independently records the uploaded
`WILLEM.COM` SHA-256; `build_id` is a non-self-referential compile-time label.
The sweep also rejects adjacent accepted tables unless exactly one of the five
read timing dimensions, including power-on stabilization, strictly decreases
while the build ID remains fixed. Drift and production reruns must reproduce their
original accepted parameter dictionaries exactly.
Each experiment directory contains a durable `executions.json`; it is written
before EXEC and binds stable execution IDs to the program/build/arguments. A
different operation cannot reuse that directory.

Programming additionally requires a documented rewritable device, endurance
accounting, both existing authorization gates, device-appropriate VPP policy,
changed/already-matching/retry/late-completion counts, separate programming and
full verification times, complete verification, and one normal fresh read.

The write runner expects one final structured metric line (all values are
unsigned decimal integers):

```text
DOSRAVI_WRITE_METRIC program_ms=N verify_ms=N changed=N unchanged=N retry_bytes=N retries=N late=N image_crc32=8_HEX_DIGITS build_id=COMPILE_TIME_ID
```

The evidence after that line must contain `Safe shutdown complete: VCC off, VPP
off`. The host prefers the current command's captured `STDOUT.TXT`, falling
back to `WILLEM.LOG` for older evidence. It records the metric, removes the
remote `WRITE.OK` token, and performs one fresh full read compared byte-for-byte
with the requested image. `--post-write-count 2..10` is available for an
explicit repeated-read experiment.
For the initial 28C64 workflow, changed plus unchanged must cover all 8,192
bytes, and retry-byte/late counts cannot exceed the changed-byte count.

All Willem runners require notes for programmer revision, complete chip
marking, supply, socket placement/orientation, DIP switches, and cable/adapter
identity. Writing additionally requires the exact datasheet, endurance, and
erase requirements; the command fails before opening the transport when any
of these records is absent.
Device, LPT, and profile values are restricted to single validated DOS tokens;
they cannot smuggle additional command-tail switches. A supplied trusted image
is stored in the session artifact manifest with CRC-32 and SHA-256.

For ST M2764A, `willem-write --device M2764A` requires the additional
`--program-phase-only` hold plus `programming-vcc`, `programming-vpp`,
`ambient-temperature`, `rail-measurement`, and `blank-check` notes. It uploads
the separate `M2764A.OK` token, parses `DOSRAVI_M2764A_METRIC`, and stops after
safe shutdown with final 5 V verification still required. The later normal-rail
`willem-read --device 2764 --trusted ... --count 1 --final-verify` is a
separate recorded session requiring `final-vcc` and `final-vpp` notes;
high-voltage byte verification is not substituted for it.

The first physical use on 2026-08-26 programmed four M2764AF1 devices as two
EktaSoft 3.7 D15/D16 pairs. Every accepted program phase reported a complete
blank scan, one initial pulse and one overprogram pulse per changed byte, zero
retries, complete high-voltage comparison, and safe shutdown; every later
normal-rail trusted read matched. The retained failure evidence is equally
important: one nonblank candidate and residual bytes after an interrupted run
were rejected before VPP, and the latter device was accepted only after a
longer second UV erase produced an all-FF scan.

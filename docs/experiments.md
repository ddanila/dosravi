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

Programming additionally requires a documented rewritable device, endurance
accounting, both existing authorization gates, device-appropriate VPP policy,
changed/already-matching/retry/late-completion counts, separate programming and
full verification times, complete verification, and ten normal accepted reads.

The write runner expects one final structured metric line (all values are
unsigned decimal integers):

```text
DOSRAVI_WRITE_METRIC program_ms=N verify_ms=N changed=N unchanged=N retry_bytes=N retries=N late=N
```

The log after that line must contain `Safe shutdown complete: VCC off, VPP
off`. The host records the metric, removes the remote `WRITE.OK` token, and
performs ten fresh full reads compared byte-for-byte with the requested image.

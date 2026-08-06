# Safety and recovery model

The DOS agent is deliberately not a general remote shell.

- The configured workspace is resolved at startup.  Remote paths are single
  DOS 8.3 filenames: no drive, separator, `.`/`..`, wildcard, device name, or
  directory component is accepted.
- LIST exposes regular workspace files.  REMOVE deletes one explicitly named
  regular file and has no wildcard or recursive form.
- Uploads never replace their destination until full size and CRC-32 match.
  Interrupted `.PART` data is resumable only when its saved identity matches.
  DOS replacement uses a hidden recoverable backup around the two renames; a
  retried PUT_BEGIN restores it if promotion was interrupted.
- GET/CRC retain at most one verified file identity to avoid repeated full-file
  scans on the 8086. Every upload, removal, child execution, or agent update
  invalidates it before workspace contents can change.
- All operations are replay-safe.  EXEC has a persistent execution identity so
  losing its final response cannot repeat a physical operation.
- Child stdout and stderr use separate per-execution files.  Original DOS
  handles and UART registers are restored along every normal return path.
- DOSRAVI has no memory-write, reboot, VPP, or hardware-safety-bypass command.
  It never proxies LPT operations.  `WILLEM.COM` retains `/WRITE` and
  `WRITE.OK` authorization and owns programmer safe shutdown.
- A serial interruption causes a bounded retry.  A host restart begins with
  PING/INFO, resumes uploads by offset, verifies remote CRCs, and queries the
  same execution identifier rather than choosing a new one.
- A child which hangs or damages DOS cannot return control to a foreground
  agent.  Reset the Pocket8086; AUTOEXEC starts DOSRAVI again.  Fully unattended
  crash recovery requires an explicitly designed external reset or watchdog
  and is not silently claimed by v0.1.
- Agent replacement is limited to the two-phase UPDATE workflow.  A complete
  uploaded image is CRC-verified before promotion, `DOSRAVI.OLD` is never
  discarded during staging, and `RAVILOAD.BAT` restores it after an
  unconfirmed reset.  Host confirmation is sent only after the replacement
  answers PING/INFO over the real UART path.
- Normal PUT/REMOVE operations deny the agent, fallback, pending marker, and
  launcher control names. `DOSRAVI.NEW` can be uploaded, but it can only be
  promoted by the CRC-checked UPDATE command.
- Physical execution IDs are written and fsynced to the session before EXEC.
  Resuming the same output directory reuses those IDs. Completed write evidence
  is bound to the image CRC and Willem build hash, so a host restart does not
  silently schedule the programming operation again.

Before physical programmer use, verify the null-modem electrical connection,
begin at a conservative baud, run a harmless diagnostic, and prove an existing
known-chip read.  Trace changes timing and is disabled for speed measurements.
Programming experiments remain out of scope until the read-only gates and the
device-specific electrical documentation are complete.

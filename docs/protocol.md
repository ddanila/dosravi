# DOSRAVI wire protocol v0.1

This document freezes protocol version 1.  Multi-byte integers are unsigned
little-endian.  Unknown versions, frame types, commands, and required fields
are rejected; peers never guess a newer interpretation.

## Transport and framing

The byte stream is binary 8N1.  A frame is COBS-encoded and followed by a zero
delimiter.  The decoded frame is:

| Offset | Size | Meaning |
|---:|---:|---|
| 0 | 1 | protocol version (`1`) |
| 1 | 1 | frame type (`1` request, `2` response, `3` event) |
| 2 | 1 | flags (`bit 0 MORE`, `bit 1 REPLAY`) |
| 3 | 1 | reserved, must be zero |
| 4 | 4 | transaction identifier |
| 8 | 4 | sequence identifier, zero in stop-and-wait v0.1 |
| 12 | 2 | payload byte length |
| 14 | n | payload, at most 4,096 bytes |
| 14+n | 2 | CRC-16/CCITT-FALSE over header and payload |

CRC-16 uses polynomial `0x1021`, initial value `0xffff`, no reflection, and no
final XOR.  Whole-file CRC-32 is the standard reflected IEEE CRC used by zlib.
A decoder stores at most 4,608 encoded bytes.  An oversized, corrupt, or
truncated candidate is discarded through the next zero delimiter, bounding
memory use and resynchronization time.

## Payloads

A request begins with one command byte followed by zero or more TLVs.  A
response begins with the echoed command byte and a status byte, followed by
TLVs.  A TLV is a one-byte tag, a two-byte value length, and the value.

Stable tags are: `PATH=1`, `OFFSET=2`, `SIZE=3`, `CRC32=4`, `DATA=5`,
`ARGS=6`, `EXEC_ID=7`, `EXIT_CODE=8`, `STDOUT=9`, `STDERR=10`, `JSON=11`,
`MESSAGE=12`, `CHUNK_SIZE=13`, `ELAPSED_MS=14`, and `ARTIFACT=15`.  Integer
values occupy exactly four bytes.  Paths and arguments are ASCII.  JSON is
UTF-8 and only used for human-oriented INFO/LIST metadata, never for transfer
control.

Status values are `OK=0`, `BAD_REQUEST=1`, `NOT_FOUND=2`, `DENIED=3`,
`IO_ERROR=4`, `CRC_MISMATCH=5`, `OFFSET_MISMATCH=6`, `BUSY=7`,
`UNSUPPORTED=8`, and `INTERNAL=9`.

## Commands

| Code | Command | Required request fields | Successful response |
|---:|---|---|---|
| 1 | PING | none | MESSAGE=`PONG` |
| 2 | INFO | none | JSON capability object |
| 3 | LIST | none | JSON array of regular files |
| 4 | PUT_BEGIN | PATH, SIZE, CRC32 | resumable OFFSET |
| 5 | PUT_DATA | PATH, OFFSET, DATA | next OFFSET |
| 6 | PUT_COMMIT | PATH, SIZE, CRC32 | SIZE, CRC32 |
| 7 | GET | PATH, OFFSET, CHUNK_SIZE | SIZE, CRC32, OFFSET, DATA |
| 8 | CRC | PATH | SIZE, CRC32 |
| 9 | REMOVE | PATH | no fields |
| 10 | EXEC | PATH, ARGS, EXEC_ID | EXEC_ID, EXIT_CODE, STDOUT, STDERR, ELAPSED_MS |
| 11 | EXEC_RESULT | EXEC_ID | cached execution result (reserved for asynchronous agents) |
| 12 | QUIT | none | no fields, then UART restoration |
| 13 | UPDATE | PATH=`DOSRAVI.NEW`, SIZE, CRC32 | staged acknowledgement, then launcher restart |
| 14 | UPDATE_CONFIRM | none | pending marker removed; fallback retained |
| 15 | UPDATE_ROLLBACK | none | rollback acknowledgement, then launcher restart |

The public PUT operation is the three-command sequence above.  The receiver
writes `PATH.PART`, persists expected size/CRC metadata, and returns its current
length after reconnect.  PUT_COMMIT recalculates the complete CRC, closes the
file, and atomically renames it only on an exact size and CRC match.  GET always
identifies the complete file and the returned chunk's explicit offset.  v0.1
uses stop-and-wait and a default 512-byte chunk; peers advertise a larger safe
limit before it is used.

Every request has a nonzero host-selected transaction identifier.  The agent
caches recent encoded responses.  An identical repeated transaction is not
dispatched again; the cached response is returned with REPLAY set.  Reusing a
transaction identifier with different request bytes is a protocol error.

EXEC additionally has a stable execution identifier whose completed result is
cached independently of the frame replay window.  A host reconnect may submit
the same execution identifier without running the program twice.  The agent
acknowledges only after redirecting DOS handles 1 and 2, restores both handles
after INT 21h/4B00 returns, obtains the child status through INT 21h/4D00, and
then responds.  A hung child requires external reset in the foreground design.

UPDATE accepts only the fixed `DOSRAVI.NEW` staging name and checks the complete
size and CRC-32 again.  The old agent is retained as `DOSRAVI.OLD`; a pending
marker makes an unconfirmed boot recoverable.  Staging and rollback respond
before restoring the UART and returning the reserved status 85 to
`RAVILOAD.BAT`.  The host must reconnect, verify PING/INFO, and issue
UPDATE_CONFIRM.  Confirmation removes only the marker, not the fallback.

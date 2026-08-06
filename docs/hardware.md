# Physical inventory and bring-up record

No value in this file is a substitute for inspecting the real hardware.  Fill
one copy per setup and retain it with session records.

## Pocket8086 serial link

- Machine serial connector and gender: **not yet recorded**
- BIOS COM number and base address: **COM1, 03F8h** (COM2 at 02F8h is internal/reserved)
- UART model/capabilities from COMPROBE: **COM1 and COM2 report 16550A-compatible FIFOs; internal loopback PASS**
- Null-modem cable pinout: **existing Juku wiring used as-is; exact pins still need recording; do not add another TX/RX crossover**
- USB-RS232 adapter identity: **CP2102 USB bridge with MAX-level RS-232 adapter**
- Reliable loopback baud ceiling: **unconfirmed**
- Reliable full-protocol baud ceiling: **57,600 accepted for the current setup**

Physical protocol trials passed PING/INFO and hash-verified round trips at
19,200, 38,400, and 57,600 baud without retries. After the optimized agent was
self-updated, three 32 KiB round trips at 57,600 all matched CRC32 `aa023caa`
with zero retries. Fresh uploads sustained about 1,502 B/s and cached-identity
downloads about 2,465 B/s; the first upload also resumed and committed the old
interrupted 32 KiB temporary. At 115,200 baud, PING/INFO passed but a sustained
512-byte PUT frame timed out on every retry, so 115,200 is rejected for this
setup. Evidence is in `sessions/pocket-link-57600-soak-v2`.

Use only an RS-232-level adapter through a null-modem connection.  Record TX,
RX, signal ground, and any handshake loopbacks explicitly.  Do not attach a
TTL UART directly.

COMPROBE and DOSRAVI restore the readable UART registers and whether a usable
FIFO had been enabled. The original FIFO trigger level is write-only and cannot
be reconstructed; restoration re-enables such a FIFO at its default trigger.

## Willem / chip session

- Programmer PCB revision and compatibility mode: **unconfirmed**
- Power supply and measured voltage: **unconfirmed**
- LPT base: **unconfirmed**
- Socket position/orientation: **unconfirmed**
- Complete DIP switch diagram: **unconfirmed**
- Chip complete top marking and manufacturer: **unconfirmed**
- Datasheet revision/source: **unconfirmed**
- Capacity, pinout, VCC, and (if relevant) VPP: **unconfirmed**
- Trusted dump or independent programmer: **unconfirmed**
- Accepted named read timing profile: **unconfirmed**

РФ5 is a family shorthand, not sufficient device identification.  Read-only
support must not be selected until the complete marking identifies capacity,
pinout, supply, socket placement, switch settings, and timing from the exact
datasheet.  VPP remains disabled for the read-only milestone.

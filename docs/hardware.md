# Physical inventory and bring-up record

No value in this file is a substitute for inspecting the real hardware.  Fill
one copy per setup and retain it with session records.

## Pocket8086 serial link

- Machine serial connector and gender: **unconfirmed**
- BIOS COM number and base address: **unconfirmed**
- UART model/capabilities from COMPROBE: **unconfirmed**
- Null-modem cable pinout: **unconfirmed**
- USB-RS232 adapter identity: **unconfirmed**
- Reliable loopback baud ceiling: **unconfirmed**
- Reliable full-protocol baud ceiling: **unconfirmed**

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

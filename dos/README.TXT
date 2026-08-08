DOSRAVI 0.1.1

Run COMPROBE first and record its output. Install an RS-232 loopback plug and
run COMPROBE /EXTERNAL to test 9600 through 115200 baud. The normal foreground
command after choosing a reliable rate is:

  DOSRAVI /COM1 /BAUD:38400 /ROOT:C:\RAVI

For the recorded Pocket8086 and CP2102/MAX/null-modem setup, type only:

  RAVI

RAVI.BAT uses the update-aware loader with COM1, 57600 baud, and C:\RAVI.
The agent prints its version, port, baud, UART base, workspace, and READY when
it starts. Press Ctrl+C or Esc to restore the UART and return to DOS. A remote
QUIT command remains supported.

Valid rates are 9600, 19200, 38400, 57600, and 115200. /BASE:3F8 overrides
the BIOS COM base only when hardware inspection proves that it is necessary.
QUIT restores readable UART registers and returns to DOS.

Add RAVILOAD.BAT to AUTOEXEC.BAT only after the correct workspace and serial
hardware have been verified. The launcher completes two-phase self-update and
restores DOSRAVI.OLD after an unconfirmed reset. Do not invoke DOSRAVI directly
if remote self-update is required. A hung child still needs a machine reset.

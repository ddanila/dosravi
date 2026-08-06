from __future__ import annotations

import os
import pty
import termios
import unittest

from dosravi.transport import SerialTransport


class SerialTransportTests(unittest.TestCase):
    def test_raw_8n1_configuration_and_restore(self) -> None:
        master, slave = pty.openpty()
        try:
            device = os.ttyname(slave)
            original = termios.tcgetattr(slave)
            transport = SerialTransport(device, 38400)
            configured = termios.tcgetattr(transport.fd)
            self.assertEqual(configured[0], 0)
            self.assertEqual(configured[1], 0)
            self.assertEqual(configured[2] & termios.CSIZE, termios.CS8)
            self.assertFalse(configured[2] & termios.PARENB)
            self.assertFalse(configured[2] & termios.CSTOPB)
            transport.close()
            restored = termios.tcgetattr(slave)
            self.assertEqual(restored, original)
        finally:
            os.close(master)
            os.close(slave)


if __name__ == "__main__":
    unittest.main()

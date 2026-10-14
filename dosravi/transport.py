"""Transport adapters for physical serial ports, DOSBox TCP, and tests."""

from __future__ import annotations

import os
import select
import socket
import termios
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from typing import BinaryIO


class TransportError(OSError):
    pass


class Transport(ABC):
    """Ordered bytes: write all or raise; read up to size (b"" on idle/zero size).

    A failed write may have sent a prefix. Never reconnect/replay in this layer.
    Serial/TCP writes have a five-second total deadline. close releases owned
    resources even when restoring device settings fails. No target reset here.
    """

    @abstractmethod
    def write(self, data: bytes) -> None:
        raise NotImplementedError

    @abstractmethod
    def read(self, size: int, timeout: float) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


_BAUDS = {
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
}


class SerialTransport(Transport):
    """Raw 8N1 POSIX serial transport with no hardware flow control."""

    def __init__(self, device: str, baud: int = 38400):
        if baud not in _BAUDS:
            raise ValueError(f"unsupported baud {baud}")
        self.fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.original_attrs = None
        try:
            attrs = termios.tcgetattr(self.fd)
            self.original_attrs = [*attrs[:6], list(attrs[6])]
            attrs[0] = 0
            attrs[1] = 0
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attrs[3] = 0
            attrs[4] = _BAUDS[baud]
            attrs[5] = _BAUDS[baud]
            attrs[6][termios.VMIN] = 0
            attrs[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
            termios.tcflush(self.fd, termios.TCIOFLUSH)
        except BaseException:
            # Preserve the setup error even if a disconnected device cannot restore.
            try:
                self.close()
            except (OSError, termios.error):
                pass
            raise

    def write(self, data: bytes) -> None:
        deadline = time.monotonic() + 5.0
        view = memoryview(data)
        while view:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportError("serial write timeout")
            try:
                _, writable, _ = select.select([], [self.fd], [], remaining)
                if not writable:
                    raise TransportError("serial write timeout")
                written = os.write(self.fd, view)
            except (InterruptedError, BlockingIOError):
                continue
            if written == 0:
                raise TransportError("serial disconnected during write")
            view = view[written:]

    def read(self, size: int, timeout: float) -> bytes:
        if size <= 0:
            return b""
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            try:
                readable, _, _ = select.select(
                    [self.fd], [], [], max(0.0, deadline - time.monotonic())
                )
                if not readable:
                    return b""
                data = os.read(self.fd, size)
            except (InterruptedError, BlockingIOError):
                if time.monotonic() >= deadline:
                    return b""
                continue
            if not data:
                raise TransportError("serial disconnected during read")
            return data

    def close(self) -> None:
        if self.fd >= 0:
            fd, self.fd = self.fd, -1
            try:
                if self.original_attrs is not None:
                    termios.tcsetattr(fd, termios.TCSANOW, self.original_attrs)
            finally:
                os.close(fd)


class SocketTransport(Transport):
    """TCP client transport for a DOSBox-X null-modem server."""

    def __init__(self, host: str, port: int, connect_timeout: float = 5.0):
        self.socket = socket.create_connection((host, port), connect_timeout)
        try:
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except BaseException:
            self.socket.close()
            raise

    def write(self, data: bytes) -> None:
        self.socket.settimeout(5.0)
        self.socket.sendall(data)

    def read(self, size: int, timeout: float) -> bytes:
        if size <= 0:
            return b""
        self.socket.settimeout(max(timeout, 0.0))
        try:
            data = self.socket.recv(size)
        except (TimeoutError, BlockingIOError):
            return b""
        if not data:
            raise TransportError("socket disconnected during read")
        return data

    def close(self) -> None:
        self.socket.close()


class LoggedTransport(Transport):
    def __init__(self, inner: Transport, rx_log: BinaryIO, tx_log: BinaryIO):
        self.inner = inner
        self.rx_log = rx_log
        self.tx_log = tx_log

    def write(self, data: bytes) -> None:
        self.tx_log.write(data)
        self.tx_log.flush()
        self.inner.write(data)

    def read(self, size: int, timeout: float) -> bytes:
        data = self.inner.read(size, timeout)
        if data:
            self.rx_log.write(data)
            self.rx_log.flush()
        return data

    def close(self) -> None:
        self.inner.close()


class LoopbackTransport(Transport):
    """Synchronous in-process transport for the reference agent and tests."""

    def __init__(self, handler: Callable[[bytes], bytes]):
        self.handler = handler
        self.pending: deque[bytes] = deque()
        self.closed = False

    def write(self, data: bytes) -> None:
        if self.closed:
            raise TransportError("transport closed")
        response = self.handler(data)
        if response:
            self.pending.append(response)

    def read(self, size: int, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        while not self.pending and time.monotonic() < deadline:
            time.sleep(min(0.001, max(0.0, deadline - time.monotonic())))
        if not self.pending:
            return b""
        data = self.pending.popleft()
        if len(data) > size:
            self.pending.appendleft(data[size:])
            return data[:size]
        return data

    def close(self) -> None:
        self.closed = True

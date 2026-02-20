"""Serial transport wrapping pyserial."""

from __future__ import annotations

import serial


class SerialTransport:
    """Pyserial-backed transport for UART communication."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        bytesize: int = serial.EIGHTBITS,
        parity: str = serial.PARITY_NONE,
        stopbits: float = serial.STOPBITS_ONE,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._bytesize = bytesize
        self._parity = parity
        self._stopbits = stopbits
        self._serial: serial.Serial | None = None

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    @property
    def port(self) -> str:
        return self._port

    @property
    def baudrate(self) -> int:
        return self._baudrate

    def open(self) -> None:
        if self.is_open:
            raise RuntimeError(f"Port {self._port} is already open")
        self._serial = serial.Serial(
            port=self._port,
            baudrate=self._baudrate,
            bytesize=self._bytesize,
            parity=self._parity,
            stopbits=self._stopbits,
            timeout=0.05,  # 50ms read timeout for non-blocking behavior
        )

    def close(self) -> None:
        if self._serial is not None:
            if self._serial.is_open:
                self._serial.flush()
                self._serial.close()
            self._serial = None

    def read(self, size: int = 1024, timeout: float | None = None) -> bytes:
        if not self.is_open or self._serial is None:
            raise RuntimeError("Port is not open")
        if timeout is not None:
            old_timeout = self._serial.timeout
            self._serial.timeout = timeout
        try:
            data = self._serial.read(size)
        finally:
            if timeout is not None:
                self._serial.timeout = old_timeout
        return data

    def write(self, data: bytes) -> int:
        if not self.is_open or self._serial is None:
            raise RuntimeError("Port is not open")
        return self._serial.write(data)

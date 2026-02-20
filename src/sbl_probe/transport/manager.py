"""Connection manager — registry of named serial connections."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sbl_probe.decoders import registry as decoder_registry
from sbl_probe.decoders.base import Decoder
from sbl_probe.transport.serial import SerialTransport

if TYPE_CHECKING:
    from sbl_probe.capture.engine import CaptureEngine


@dataclass
class Connection:
    """A named serial connection with its transport and decoder."""

    name: str
    transport: SerialTransport
    decoder: Decoder
    capture: CaptureEngine | None = None
    bytes_in: int = 0
    bytes_out: int = 0
    opened_at: float = field(default_factory=time.monotonic)

    @property
    def is_capturing(self) -> bool:
        return self.capture is not None and self.capture.is_running

    @property
    def uptime(self) -> float:
        return time.monotonic() - self.opened_at

    def to_dict(self) -> dict:
        result = {
            "name": self.name,
            "port": self.transport.port,
            "baudrate": self.transport.baudrate,
            "is_open": self.transport.is_open,
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            "uptime_seconds": round(self.uptime, 1),
            "decoder": self.decoder.name,
            "capturing": self.is_capturing,
        }
        if self.is_capturing:
            result["capture_frames"] = len(self.capture.buffer)
        return result


class ConnectionManager:
    """Thread-safe registry of named connections."""

    def __init__(self) -> None:
        self._connections: dict[str, Connection] = {}
        self._lock = threading.Lock()

    def _auto_name(self, port: str) -> str:
        """Derive a connection name from the port path."""
        # /dev/ttyAMA4 -> ttyAMA4, /dev/ttyACM0 -> ttyACM0
        return port.rsplit("/", 1)[-1]

    def open(
        self,
        port: str,
        baudrate: int = 115200,
        name: str | None = None,
    ) -> Connection:
        """Open a serial connection and register it."""
        if name is None:
            name = self._auto_name(port)

        with self._lock:
            if name in self._connections:
                raise ValueError(f"Connection '{name}' already exists")

            # Check no other connection uses the same port
            for conn in self._connections.values():
                if conn.transport.port == port:
                    raise ValueError(
                        f"Port {port} is already open as '{conn.name}'"
                    )

            transport = SerialTransport(port=port, baudrate=baudrate)
            transport.open()

            decoder = decoder_registry.create("raw")
            conn = Connection(name=name, transport=transport, decoder=decoder)
            self._connections[name] = conn
            return conn

    def close(self, name: str) -> None:
        """Close and unregister a connection. Stops capture if active."""
        with self._lock:
            conn = self._connections.pop(name, None)
            if conn is None:
                raise ValueError(f"No connection named '{name}'")
            if conn.is_capturing:
                conn.capture.stop()
            conn.transport.close()

    def get(self, name: str) -> Connection:
        """Get a connection by name."""
        with self._lock:
            conn = self._connections.get(name)
            if conn is None:
                raise ValueError(f"No connection named '{name}'")
            return conn

    def list(self) -> list[Connection]:
        """List all active connections."""
        with self._lock:
            return list(self._connections.values())

    def set_decoder(self, name: str, decoder_name: str) -> Decoder:
        """Change the decoder on a connection."""
        with self._lock:
            conn = self._connections.get(name)
            if conn is None:
                raise ValueError(f"No connection named '{name}'")
            new_decoder = decoder_registry.create(decoder_name)
            conn.decoder = new_decoder
            return new_decoder

    def close_all(self) -> None:
        """Close all connections. Used during server shutdown."""
        with self._lock:
            for conn in self._connections.values():
                if conn.is_capturing:
                    conn.capture.stop()
                conn.transport.close()
            self._connections.clear()

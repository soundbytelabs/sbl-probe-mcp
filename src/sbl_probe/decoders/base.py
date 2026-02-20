"""Decoder protocol and Frame dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Frame:
    """Universal decoded unit from any protocol."""

    timestamp: float
    protocol: str       # "raw", "uart_log", "i2c", "spi"
    direction: str      # "rx", "tx", "bidir"
    data: bytes         # raw payload
    decoded: dict | None = None   # protocol-specific fields
    error: str | None = None

    def to_dict(self) -> dict:
        result: dict = {
            "timestamp": round(self.timestamp, 6),
            "protocol": self.protocol,
            "direction": self.direction,
            "data_hex": self.data.hex(),
        }
        # Include text representation for printable data
        try:
            text = self.data.decode("utf-8", errors="replace").rstrip("\r\n")
            result["text"] = text
        except Exception:
            pass
        if self.decoded is not None:
            result["decoded"] = self.decoded
        if self.error is not None:
            result["error"] = self.error
        return result


@runtime_checkable
class Decoder(Protocol):
    """Interface for protocol decoders."""

    @property
    def name(self) -> str: ...

    def feed(self, data: bytes, timestamp: float) -> list[Frame]: ...

    def reset(self) -> None: ...

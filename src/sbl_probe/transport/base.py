"""Transport protocol — structural typing for serial backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Transport(Protocol):
    """Interface for byte-level communication transports."""

    @property
    def is_open(self) -> bool: ...

    @property
    def port(self) -> str: ...

    def open(self) -> None: ...

    def close(self) -> None: ...

    def read(self, size: int = 1024, timeout: float | None = None) -> bytes: ...

    def write(self, data: bytes) -> int: ...

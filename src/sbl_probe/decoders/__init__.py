"""Protocol decoders for serial data."""

from __future__ import annotations

from typing import Callable

from sbl_probe.decoders.base import Frame, Decoder
from sbl_probe.decoders.midi import MidiDecoder
from sbl_probe.decoders.raw import RawDecoder

__all__ = ["Frame", "Decoder", "RawDecoder", "MidiDecoder", "DecoderRegistry"]


class DecoderRegistry:
    """Registry mapping decoder names to factory functions."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], Decoder]] = {}

    def register(self, name: str, factory: Callable[[], Decoder]) -> None:
        self._factories[name] = factory

    def create(self, name: str) -> Decoder:
        factory = self._factories.get(name)
        if factory is None:
            available = ", ".join(sorted(self._factories)) or "(none)"
            raise ValueError(
                f"Unknown decoder '{name}'. Available: {available}"
            )
        return factory()

    def list(self) -> list[str]:
        return sorted(self._factories)


# Default registry with built-in decoders
registry = DecoderRegistry()
registry.register("midi", MidiDecoder)
registry.register("raw", RawDecoder)

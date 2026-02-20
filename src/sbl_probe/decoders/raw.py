"""Raw decoder — line-oriented framing for serial data."""

from __future__ import annotations

from sbl_probe.decoders.base import Frame


class RawDecoder:
    """Line-oriented decoder that splits on newlines.

    Buffers partial lines until a newline is received.
    Handles both \\n and \\r\\n line endings.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    @property
    def name(self) -> str:
        return "raw"

    def feed(self, data: bytes, timestamp: float) -> list[Frame]:
        if not data:
            return []

        self._buffer.extend(data)
        frames: list[Frame] = []

        while b"\n" in self._buffer:
            idx = self._buffer.index(b"\n")
            line = bytes(self._buffer[: idx + 1])
            del self._buffer[: idx + 1]

            # Strip trailing \r\n or \n
            payload = line.rstrip(b"\r\n")
            if not payload:
                continue

            frames.append(
                Frame(
                    timestamp=timestamp,
                    protocol="raw",
                    direction="rx",
                    data=payload,
                )
            )

        return frames

    def flush(self) -> list[Frame]:
        """Flush any remaining buffered data as a frame."""
        if not self._buffer:
            return []
        import time

        payload = bytes(self._buffer)
        self._buffer.clear()
        return [
            Frame(
                timestamp=time.monotonic(),
                protocol="raw",
                direction="rx",
                data=payload,
            )
        ]

    def reset(self) -> None:
        self._buffer.clear()

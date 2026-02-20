"""Background capture engine — reader thread that feeds frames into a buffer."""

from __future__ import annotations

import threading
import time

from sbl_probe.capture.buffer import CaptureBuffer
from sbl_probe.decoders.base import Decoder
from sbl_probe.transport.base import Transport


class CaptureEngine:
    """Background reader thread that captures serial data into a ring buffer.

    Owns the transport read loop while active — manual read/read_raw
    should be blocked during capture.
    """

    def __init__(
        self,
        transport: Transport,
        decoder: Decoder,
        buffer: CaptureBuffer,
    ) -> None:
        self._transport = transport
        self._decoder = decoder
        self._buffer = buffer
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at: float | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def started_at(self) -> float | None:
        return self._started_at

    @property
    def buffer(self) -> CaptureBuffer:
        return self._buffer

    def start(self) -> None:
        if self.is_running:
            raise RuntimeError("Capture is already running")
        self._stop_event.clear()
        self._started_at = time.monotonic()
        self._thread = threading.Thread(
            target=self._reader_loop,
            daemon=True,
            name="sbl-capture",
        )
        self._thread.start()

    def stop(self) -> dict:
        """Stop capture and return summary stats."""
        if not self.is_running:
            raise RuntimeError("Capture is not running")
        self._stop_event.set()
        self._thread.join(timeout=3.0)
        self._thread = None

        duration = time.monotonic() - self._started_at if self._started_at else 0
        stats = self._buffer.stats
        return {
            "duration_seconds": round(duration, 1),
            "frames_captured": stats.frames_captured,
            "frames_dropped": stats.frames_dropped,
            "bytes_processed": stats.bytes_processed,
            "errors": stats.errors,
            "buffer_size": len(self._buffer),
        }

    def _reader_loop(self) -> None:
        """Main capture loop — runs in a background thread."""
        while not self._stop_event.is_set():
            try:
                data = self._transport.read(size=4096, timeout=0.05)
                if data:
                    self._buffer.stats.bytes_processed += len(data)
                    now = time.monotonic()
                    frames = self._decoder.feed(data, now)
                    if frames:
                        self._buffer.extend(frames)
            except Exception:
                self._buffer.stats.errors += 1
                # Brief pause on error to avoid tight spin
                self._stop_event.wait(0.1)

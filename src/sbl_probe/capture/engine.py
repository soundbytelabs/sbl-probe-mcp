"""Background capture engine — reader thread that feeds frames into a buffer."""

from __future__ import annotations

import re
import threading
import time
from collections import deque

from sbl_probe.capture.buffer import CaptureBuffer
from sbl_probe.decoders.base import Decoder, Frame
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
        filter_pattern: str | None = None,
        trigger_pattern: str | None = None,
        pretrigger: int = 0,
    ) -> None:
        self._transport = transport
        self._decoder = decoder
        self._buffer = buffer
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at: float | None = None
        self._duration: float | None = None

        # Ingress filter — only matching frames enter the buffer
        self._filter = re.compile(filter_pattern) if filter_pattern else None
        self._filter_pattern = filter_pattern

        # Trigger — wait for matching frame before buffering
        self._trigger = re.compile(trigger_pattern) if trigger_pattern else None
        self._trigger_pattern = trigger_pattern
        self._triggered = trigger_pattern is None  # no trigger = immediate start
        self._trigger_at: float | None = None
        self._pretrigger_size = pretrigger
        self._pretrigger_buf: deque[Frame] | None = (
            deque(maxlen=pretrigger) if pretrigger > 0 else None
        )

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def started_at(self) -> float | None:
        return self._started_at

    @property
    def buffer(self) -> CaptureBuffer:
        return self._buffer

    @property
    def triggered(self) -> bool:
        return self._triggered

    @property
    def trigger_pattern(self) -> str | None:
        return self._trigger_pattern

    @property
    def filter_pattern(self) -> str | None:
        return self._filter_pattern

    def start(self, duration: float | None = None) -> None:
        if self.is_running:
            raise RuntimeError("Capture is already running")
        self._duration = duration
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
        if self._thread is None:
            raise RuntimeError("Capture is not running")
        if self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=3.0)
        self._thread = None

        duration = time.monotonic() - self._started_at if self._started_at else 0
        stats = self._buffer.stats
        result = {
            "duration_seconds": round(duration, 1),
            "frames_captured": stats.frames_captured,
            "frames_dropped": stats.frames_dropped,
            "bytes_processed": stats.bytes_processed,
            "errors": stats.errors,
            "buffer_size": len(self._buffer),
        }
        if stats.frames_filtered > 0:
            result["frames_filtered"] = stats.frames_filtered
        if self._trigger_pattern is not None:
            result["triggered"] = self._triggered
            if self._trigger_at is not None:
                result["trigger_at"] = round(self._trigger_at, 6)
        return result

    def _apply_filter(self, frames: list[Frame]) -> list[Frame]:
        """Apply ingress filter, updating stats for filtered frames."""
        if not self._filter:
            return frames
        accepted = []
        for f in frames:
            text = f.data.decode("utf-8", errors="replace")
            if self._filter.search(text):
                accepted.append(f)
            else:
                self._buffer.stats.frames_filtered += 1
        return accepted

    def _reader_loop(self) -> None:
        """Main capture loop — runs in a background thread."""
        deadline = (self._started_at + self._duration) if self._duration else None
        while not self._stop_event.is_set():
            if deadline and time.monotonic() >= deadline:
                break
            try:
                data = self._transport.read(size=4096, timeout=0.05)
                if not data:
                    continue

                self._buffer.stats.bytes_processed += len(data)
                now = time.monotonic()
                frames = self._decoder.feed(data, now)
                if not frames:
                    continue

                # Apply ingress filter first
                frames = self._apply_filter(frames)
                if not frames:
                    continue

                if self._triggered:
                    # Normal capture mode
                    self._buffer.extend(frames)
                else:
                    # Waiting for trigger
                    self._process_trigger(frames)

            except Exception:
                self._buffer.stats.errors += 1
                # Brief pause on error to avoid tight spin
                self._stop_event.wait(0.1)

    def _process_trigger(self, frames: list[Frame]) -> None:
        """Check frames for trigger match. Flush pretrigger + remaining on match."""
        for i, f in enumerate(frames):
            text = f.data.decode("utf-8", errors="replace")
            if self._trigger.search(text):
                self._triggered = True
                self._trigger_at = f.timestamp

                # Flush pretrigger buffer
                if self._pretrigger_buf:
                    self._buffer.extend(list(self._pretrigger_buf))
                    self._pretrigger_buf = None

                # Buffer trigger frame + everything after it
                self._buffer.extend(frames[i:])
                return

            # Not triggered yet — accumulate in pretrigger
            if self._pretrigger_buf is not None:
                self._pretrigger_buf.append(f)

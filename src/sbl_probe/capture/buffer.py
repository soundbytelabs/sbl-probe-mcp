"""Ring buffer for captured frames with query support."""

from __future__ import annotations

import re
import threading
from collections import deque
from dataclasses import dataclass, field

from sbl_probe.decoders.base import Frame


@dataclass
class CaptureStats:
    """Running statistics for a capture session."""

    frames_captured: int = 0
    frames_dropped: int = 0
    bytes_processed: int = 0
    errors: int = 0


class CaptureBuffer:
    """Thread-safe ring buffer of decoded frames with query support."""

    def __init__(self, max_frames: int = 10000) -> None:
        self._frames: deque[Frame] = deque(maxlen=max_frames)
        self._max_frames = max_frames
        self._lock = threading.Lock()
        self.stats = CaptureStats()

    @property
    def max_frames(self) -> int:
        return self._max_frames

    def append(self, frame: Frame) -> None:
        with self._lock:
            was_full = len(self._frames) == self._max_frames
            self._frames.append(frame)
            self.stats.frames_captured += 1
            if was_full:
                self.stats.frames_dropped += 1

    def extend(self, frames: list[Frame]) -> None:
        with self._lock:
            for frame in frames:
                was_full = len(self._frames) == self._max_frames
                self._frames.append(frame)
                self.stats.frames_captured += 1
                if was_full:
                    self.stats.frames_dropped += 1

    def query(
        self,
        last_n: int | None = None,
        pattern: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> list[Frame]:
        """Query frames from the buffer.

        Args:
            last_n: Return only the last N frames (after filtering).
            pattern: Regex pattern to match against frame text.
            since: Only frames with timestamp >= since.
            until: Only frames with timestamp <= until.
        """
        compiled = re.compile(pattern) if pattern else None

        with self._lock:
            results: list[Frame] = []
            for frame in self._frames:
                if since is not None and frame.timestamp < since:
                    continue
                if until is not None and frame.timestamp > until:
                    continue
                if compiled is not None:
                    text = frame.data.decode("utf-8", errors="replace")
                    if not compiled.search(text):
                        continue
                results.append(frame)

        if last_n is not None:
            results = results[-last_n:]

        return results

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._frames)

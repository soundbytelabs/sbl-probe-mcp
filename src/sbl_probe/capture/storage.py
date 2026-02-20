"""JSON Lines storage for capture data."""

from __future__ import annotations

import json
from pathlib import Path

from sbl_probe.decoders.base import Frame


def save_jsonl(frames: list[Frame], path: str | Path) -> int:
    """Save frames to a JSON Lines file. Returns frame count."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for frame in frames:
            json.dump(frame.to_dict(), f, separators=(",", ":"))
            f.write("\n")
    return len(frames)


def load_jsonl(path: str | Path) -> list[dict]:
    """Load frames from a JSON Lines file. Returns list of frame dicts."""
    path = Path(path)
    frames = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                frames.append(json.loads(line))
    return frames

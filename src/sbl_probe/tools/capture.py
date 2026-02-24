"""Capture tools: capture_start, capture_stop, capture_read, capture_stats, capture_save, capture_load."""

from __future__ import annotations

from sbl_probe.capture.buffer import CaptureBuffer
from sbl_probe.capture.engine import CaptureEngine
from sbl_probe.capture.storage import save_jsonl, load_jsonl
from sbl_probe.transport.manager import ConnectionManager


def register_tools(mcp, manager: ConnectionManager) -> None:
    """Register capture tools with the MCP server."""

    @mcp.tool()
    def capture_start(
        name: str,
        max_frames: int = 10000,
        duration: float | None = None,
        filter: str | None = None,
        trigger: str | None = None,
        pretrigger: int = 0,
    ) -> dict:
        """Start background capture on a connection.

        Continuously reads from the serial port and stores decoded frames
        in a ring buffer. Use capture_read to query the buffer.

        While capture is active, read/read_raw are disabled on this
        connection — use capture_read instead.

        Args:
            name: Connection name.
            max_frames: Max frames in the ring buffer. Default: 10000.
            duration: Optional capture duration in seconds. When set, capture
                auto-stops after this many seconds. The buffer persists for
                querying with capture_read.
            filter: Optional regex pattern. Only frames matching this pattern
                are buffered. Non-matching frames are silently dropped (tracked
                in frames_filtered stat).
            trigger: Optional regex pattern. When set, capture waits in a
                "waiting" state until a frame matches the trigger. Then
                buffering begins (including the trigger frame). One-shot.
            pretrigger: Number of frames to keep before the trigger fires.
                When trigger fires, these frames are flushed into the buffer
                first, providing context. Only used with trigger. Default: 0.
        """
        try:
            conn = manager.get(name)
            if conn.is_capturing:
                return {"error": f"Capture already running on '{name}'"}

            buf = CaptureBuffer(max_frames=max_frames)
            engine = CaptureEngine(
                transport=conn.transport,
                decoder=conn.decoder,
                buffer=buf,
                filter_pattern=filter,
                trigger_pattern=trigger,
                pretrigger=pretrigger,
            )
            conn.capture = engine
            engine.start(duration=duration)

            result: dict = {
                "status": "capturing",
                "connection": name,
                "max_frames": max_frames,
            }
            if duration is not None:
                result["duration"] = duration
            if filter is not None:
                result["filter"] = filter
            if trigger is not None:
                result["trigger"] = trigger
                result["trigger_state"] = "waiting"
                if pretrigger > 0:
                    result["pretrigger"] = pretrigger
            return result
        except ValueError as e:
            return {"error": str(e)}

    @mcp.tool()
    def capture_stop(name: str) -> dict:
        """Stop capture on a connection and return summary.

        The capture buffer is preserved — you can still query it with
        capture_read or save it with capture_save after stopping.

        Args:
            name: Connection name.
        """
        try:
            conn = manager.get(name)
            if conn.capture is None:
                return {"error": f"No capture on '{name}'"}

            summary = conn.capture.stop()
            return {
                "status": "stopped",
                "connection": name,
                **summary,
            }
        except (ValueError, RuntimeError) as e:
            return {"error": str(e)}

    @mcp.tool()
    def capture_read(
        name: str,
        last_n: int | None = None,
        pattern: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> dict:
        """Read frames from a capture buffer.

        Works while capture is running or after it's been stopped
        (buffer persists until the connection is closed or a new
        capture is started).

        Args:
            name: Connection name.
            last_n: Return only the last N frames (after filtering).
            pattern: Regex pattern to match against frame text.
            since: Only frames with timestamp >= this value.
            until: Only frames with timestamp <= this value.
        """
        try:
            conn = manager.get(name)
            if conn.capture is None:
                return {"error": f"No capture buffer on '{name}'. Start one with capture_start."}

            frames = conn.capture.buffer.query(
                last_n=last_n,
                pattern=pattern,
                since=since,
                until=until,
            )
            return {
                "frames": [f.to_dict() for f in frames],
                "count": len(frames),
                "total_in_buffer": len(conn.capture.buffer),
                "capturing": conn.is_capturing,
            }
        except ValueError as e:
            return {"error": str(e)}

    @mcp.tool()
    def capture_stats(name: str, groups: dict[str, str] | None = None) -> dict:
        """Get capture buffer statistics, optionally with frame counts grouped by pattern.

        Returns buffer size, capture stats, and optional per-group frame counts.
        Groups use first-match-wins semantics — each frame counts toward at most
        one group. Frames matching no group are counted as "unmatched".

        Args:
            name: Connection name.
            groups: Optional dict mapping group names to regex patterns.
                Example: {"enc": "enc delta", "btn": "btn\\\\d+", "knob": "knob\\\\d+"}
        """
        try:
            conn = manager.get(name)
            if conn.capture is None:
                return {"error": f"No capture buffer on '{name}'. Start one with capture_start."}

            buf = conn.capture.buffer
            stats = buf.stats

            result: dict = {
                "connection": name,
                "capturing": conn.is_capturing,
                "buffer_size": len(buf),
                "buffer_max": buf.max_frames,
                "stats": {
                    "frames_captured": stats.frames_captured,
                    "frames_dropped": stats.frames_dropped,
                    "bytes_processed": stats.bytes_processed,
                    "errors": stats.errors,
                },
            }
            if stats.frames_filtered > 0:
                result["stats"]["frames_filtered"] = stats.frames_filtered
            if conn.capture.trigger_pattern is not None:
                result["trigger"] = (
                    "fired" if conn.capture.triggered else "waiting"
                )
            if groups:
                result["groups"] = buf.group_counts(groups)

            return result
        except ValueError as e:
            return {"error": str(e)}

    @mcp.tool()
    def capture_save(name: str, path: str) -> dict:
        """Save capture buffer to a JSON Lines file.

        Args:
            name: Connection name.
            path: File path to save to (e.g., /tmp/capture.jsonl).
        """
        try:
            conn = manager.get(name)
            if conn.capture is None:
                return {"error": f"No capture buffer on '{name}'."}

            frames = conn.capture.buffer.query()
            count = save_jsonl(frames, path)
            return {
                "status": "saved",
                "path": path,
                "frames_saved": count,
            }
        except (ValueError, OSError) as e:
            return {"error": str(e)}

    @mcp.tool()
    def capture_load(path: str) -> dict:
        """Load frames from a previously saved JSON Lines capture file.

        Args:
            path: File path to load from.
        """
        try:
            frames = load_jsonl(path)
            return {
                "frames": frames,
                "count": len(frames),
            }
        except (OSError, ValueError) as e:
            return {"error": str(e)}

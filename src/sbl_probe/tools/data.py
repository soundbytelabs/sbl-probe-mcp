"""Data I/O tools: read_raw, write, read."""

from __future__ import annotations

import asyncio
import base64
import time

from sbl_probe.transport.manager import ConnectionManager


def _decode_input(data: str, encoding: str) -> bytes:
    """Decode user-provided data string to bytes."""
    if encoding == "utf8":
        return data.encode("utf-8")
    elif encoding == "hex":
        return bytes.fromhex(data)
    elif encoding == "base64":
        return base64.b64decode(data)
    else:
        raise ValueError(f"Unknown encoding: {encoding}. Use utf8, hex, or base64.")


def _encode_output(data: bytes, encoding: str) -> str:
    """Encode bytes to a user-friendly string."""
    if encoding == "utf8":
        return data.decode("utf-8", errors="replace")
    elif encoding == "hex":
        return data.hex()
    elif encoding == "base64":
        return base64.b64encode(data).decode("ascii")
    else:
        raise ValueError(f"Unknown encoding: {encoding}. Use utf8, hex, or base64.")


def _blocking_read(
    manager: ConnectionManager,
    name: str,
    timeout: float,
    max_bytes: int,
) -> tuple[bytes, int]:
    """Blocking read loop — runs in a thread via asyncio.to_thread."""
    conn = manager.get(name)
    buf = bytearray()
    deadline = time.monotonic() + timeout

    while len(buf) < max_bytes:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        chunk_timeout = min(remaining, 0.05)
        chunk = conn.transport.read(
            size=max_bytes - len(buf),
            timeout=chunk_timeout,
        )
        if chunk:
            buf.extend(chunk)
            conn.bytes_in += len(chunk)

    return bytes(buf), len(buf)


def _blocking_read_frames(
    manager: ConnectionManager,
    name: str,
    timeout: float,
    max_frames: int,
) -> list[dict]:
    """Blocking read + decode loop — runs in a thread via asyncio.to_thread."""
    conn = manager.get(name)
    frames = []
    deadline = time.monotonic() + timeout

    while len(frames) < max_frames:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        chunk_timeout = min(remaining, 0.05)
        chunk = conn.transport.read(size=4096, timeout=chunk_timeout)
        if chunk:
            conn.bytes_in += len(chunk)
            now = time.monotonic()
            new_frames = conn.decoder.feed(chunk, now)
            for f in new_frames:
                frames.append(f.to_dict())
                if len(frames) >= max_frames:
                    break

    return frames


def register_tools(mcp, manager: ConnectionManager) -> None:
    """Register data I/O tools with the MCP server."""

    @mcp.tool()
    async def read_raw(
        name: str,
        timeout: float = 1.0,
        max_bytes: int = 4096,
        encoding: str = "utf8",
    ) -> dict:
        """Read raw bytes from a serial connection.

        Args:
            name: Connection name.
            timeout: Max seconds to wait for data. Default: 1.0.
            max_bytes: Max bytes to read. Default: 4096.
            encoding: Output encoding — utf8, hex, or base64. Default: utf8.
        """
        try:
            conn = manager.get(name)
            if conn.is_capturing:
                return {"error": f"Capture is active on '{name}'. Use capture_read instead."}
            raw, count = await asyncio.to_thread(
                _blocking_read, manager, name, timeout, max_bytes
            )
            return {
                "data": _encode_output(raw, encoding),
                "bytes": count,
                "encoding": encoding,
            }
        except ValueError as e:
            return {"error": str(e)}

    @mcp.tool()
    async def write(
        name: str,
        data: str,
        encoding: str = "utf8",
    ) -> dict:
        """Write data to a serial connection.

        Args:
            name: Connection name.
            data: Data to write.
            encoding: Input encoding — utf8, hex, or base64. Default: utf8.
        """
        try:
            conn = manager.get(name)
            raw = _decode_input(data, encoding)
            written = conn.transport.write(raw)
            conn.bytes_out += written
            return {"bytes_written": written}
        except (ValueError, RuntimeError) as e:
            return {"error": str(e)}

    @mcp.tool()
    async def read(
        name: str,
        timeout: float = 1.0,
        max_frames: int = 100,
    ) -> dict:
        """Read decoded frames from a serial connection.

        Uses the connection's active decoder (default: raw/line-oriented) to
        split incoming bytes into structured frames with timestamps.

        Args:
            name: Connection name.
            timeout: Max seconds to wait for data. Default: 1.0.
            max_frames: Max frames to return. Default: 100.
        """
        try:
            conn = manager.get(name)
            if conn.is_capturing:
                return {"error": f"Capture is active on '{name}'. Use capture_read instead."}
            frames = await asyncio.to_thread(
                _blocking_read_frames, manager, name, timeout, max_frames
            )
            return {
                "frames": frames,
                "count": len(frames),
            }
        except ValueError as e:
            return {"error": str(e)}

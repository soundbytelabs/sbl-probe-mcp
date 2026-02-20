"""Diagnostic tools: probe_baud."""

from __future__ import annotations

import asyncio

from sbl_probe.transport.serial import SerialTransport


COMMON_BAUD_RATES = [
    9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600,
]


def _score_data(data: bytes) -> float:
    """Score how likely data is to be valid text. 0.0 = garbage, 1.0 = clean ASCII."""
    if not data:
        return 0.0
    printable = sum(
        1 for b in data
        if 0x20 <= b <= 0x7E or b in (0x09, 0x0A, 0x0D)  # tab, lf, cr
    )
    return printable / len(data)


def _try_baud(port: str, baud: int, sample_time: float) -> tuple[int, float, int]:
    """Try a baud rate and return (baud, score, bytes_read)."""
    transport = SerialTransport(port=port, baudrate=baud)
    try:
        transport.open()
        data = bytearray()
        # Read in small chunks for sample_time seconds
        import time
        deadline = time.monotonic() + sample_time
        while time.monotonic() < deadline:
            chunk = transport.read(size=1024, timeout=0.1)
            if chunk:
                data.extend(chunk)
        score = _score_data(bytes(data))
        return baud, score, len(data)
    except OSError:
        return baud, 0.0, 0
    finally:
        transport.close()


def register_tools(mcp) -> None:
    """Register diagnostic tools with the MCP server."""

    @mcp.tool()
    async def probe_baud(
        port: str,
        sample_time: float = 0.5,
        threshold: float = 0.8,
    ) -> dict:
        """Auto-detect baud rate by trying common rates and scoring for printable text.

        The port must NOT be currently open in a connection. Tries each common
        baud rate, reads for sample_time seconds, and scores the data for
        printable ASCII content.

        Args:
            port: Serial port path (e.g., /dev/ttyACM1).
            sample_time: Seconds to sample at each baud rate. Default: 0.5.
            threshold: Minimum printability score (0.0-1.0) to consider a match. Default: 0.8.
        """
        results = []
        for baud in COMMON_BAUD_RATES:
            baud_rate, score, nbytes = await asyncio.to_thread(
                _try_baud, port, baud, sample_time
            )
            results.append({
                "baud": baud_rate,
                "score": round(score, 3),
                "bytes_read": nbytes,
            })

        # Find best match above threshold
        best = max(results, key=lambda r: (r["score"], r["bytes_read"]))
        detected = best["baud"] if best["score"] >= threshold else None

        return {
            "detected_baud": detected,
            "results": results,
        }

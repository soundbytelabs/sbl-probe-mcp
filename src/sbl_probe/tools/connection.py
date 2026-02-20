"""Connection management tools: list_ports, open, close, connections."""

from __future__ import annotations

import os
from pathlib import Path

import serial.tools.list_ports

from sbl_probe.transport.manager import ConnectionManager


def _resolve_by_id(port: str) -> str | None:
    """Find the /dev/serial/by-id/ path for a given port, if any."""
    by_id = Path("/dev/serial/by-id")
    if not by_id.exists():
        return None
    for link in by_id.iterdir():
        try:
            if os.path.realpath(str(link)) == os.path.realpath(port):
                return str(link)
        except OSError:
            continue
    return None


def register_tools(mcp, manager: ConnectionManager) -> None:
    """Register connection management tools with the MCP server."""

    @mcp.tool()
    def list_ports(include_all: bool = False) -> list[dict]:
        """List available serial ports with metadata.

        Args:
            include_all: Include non-USB ports (e.g., Bluetooth). Default: False.
        """
        ports = serial.tools.list_ports.comports()
        result = []
        for p in sorted(ports, key=lambda x: x.device):
            # Skip Bluetooth and other non-relevant ports unless asked
            if not include_all:
                desc_lower = (p.description or "").lower()
                if "bluetooth" in desc_lower or "bt" in desc_lower:
                    continue

            info: dict = {
                "port": p.device,
                "description": p.description or "",
                "hwid": p.hwid or "",
            }
            if p.vid is not None:
                info["usb_vid"] = f"0x{p.vid:04X}"
                info["usb_pid"] = f"0x{p.pid:04X}" if p.pid else None
            if p.serial_number:
                info["serial_number"] = p.serial_number
            if p.manufacturer:
                info["manufacturer"] = p.manufacturer
            if p.product:
                info["product"] = p.product

            by_id = _resolve_by_id(p.device)
            if by_id:
                info["by_id_path"] = by_id

            result.append(info)
        return result

    @mcp.tool()
    def open(port: str, baud: int = 115200, name: str | None = None) -> dict:
        """Open a serial connection.

        Args:
            port: Serial port path (e.g., /dev/ttyAMA4).
            baud: Baud rate. Default: 115200.
            name: Optional name for this connection. Auto-derived from port if omitted.
        """
        try:
            conn = manager.open(port=port, baudrate=baud, name=name)
            return {
                "status": "opened",
                **conn.to_dict(),
            }
        except (ValueError, RuntimeError, OSError) as e:
            return {"status": "error", "error": str(e)}

    @mcp.tool()
    def close(name: str) -> dict:
        """Close a serial connection.

        Args:
            name: Name of the connection to close.
        """
        try:
            manager.close(name)
            return {"status": "closed", "name": name}
        except ValueError as e:
            return {"status": "error", "error": str(e)}

    @mcp.tool()
    def connections() -> list[dict]:
        """List all active serial connections with status and stats."""
        return [c.to_dict() for c in manager.list()]

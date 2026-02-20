"""Entry point for python -m sbl_probe."""

from sbl_probe.server import mcp

mcp.run(transport="stdio")

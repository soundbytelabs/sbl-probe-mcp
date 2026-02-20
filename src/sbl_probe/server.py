"""sbl-probe MCP server — serial communication & protocol analysis."""

from __future__ import annotations

import atexit

from mcp.server.fastmcp import FastMCP

from sbl_probe.transport.manager import ConnectionManager
from sbl_probe.tools import connection as connection_tools
from sbl_probe.tools import data as data_tools
from sbl_probe.tools import protocol as protocol_tools
from sbl_probe.tools import diagnostics as diagnostics_tools
from sbl_probe.tools import capture as capture_tools

mcp = FastMCP("sbl-probe")

# Shared connection manager — module-level singleton
_manager = ConnectionManager()
atexit.register(_manager.close_all)

# Register all tool modules
connection_tools.register_tools(mcp, _manager)
data_tools.register_tools(mcp, _manager)
protocol_tools.register_tools(mcp, _manager)
diagnostics_tools.register_tools(mcp)
capture_tools.register_tools(mcp, _manager)

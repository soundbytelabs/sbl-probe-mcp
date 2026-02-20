"""Tests for MCP tool parameter validation and error handling."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from sbl_probe.transport.manager import ConnectionManager
from sbl_probe.tools.data import _decode_input, _encode_output


class TestEncodings:
    def test_decode_utf8(self):
        assert _decode_input("hello", "utf8") == b"hello"

    def test_decode_hex(self):
        assert _decode_input("48656c6c6f", "hex") == b"Hello"

    def test_decode_base64(self):
        assert _decode_input("SGVsbG8=", "base64") == b"Hello"

    def test_decode_invalid_encoding(self):
        with pytest.raises(ValueError, match="Unknown encoding"):
            _decode_input("data", "ascii")

    def test_encode_utf8(self):
        assert _encode_output(b"hello", "utf8") == "hello"

    def test_encode_hex(self):
        assert _encode_output(b"\xff\x00", "hex") == "ff00"

    def test_encode_base64(self):
        assert _encode_output(b"Hello", "base64") == "SGVsbG8="

    def test_encode_invalid_encoding(self):
        with pytest.raises(ValueError, match="Unknown encoding"):
            _encode_output(b"data", "ascii")

    def test_encode_utf8_replaces_invalid(self):
        """Non-UTF8 bytes get replacement character."""
        result = _encode_output(b"\xff\xfe", "utf8")
        assert "\ufffd" in result


class TestToolErrorHandling:
    """Test that tools return error dicts instead of raising."""

    @patch("sbl_probe.transport.manager.SerialTransport")
    def test_open_bad_port(self, mock_transport_cls):
        """Opening a nonexistent port returns an error dict."""
        from mcp.server.fastmcp import FastMCP
        from sbl_probe.tools.connection import register_tools

        mock_transport_cls.side_effect = OSError("No such port")

        mgr = ConnectionManager()
        mcp = FastMCP("test")
        register_tools(mcp, mgr)

        # Call the open tool directly
        result = asyncio.get_event_loop().run_until_complete(
            mcp.call_tool("open", {"port": "/dev/nonexistent"})
        )
        # FastMCP returns tool result — check it contains error info
        assert any("error" in str(r).lower() for r in result)

    def test_close_nonexistent(self):
        """Closing a nonexistent connection returns an error dict."""
        from mcp.server.fastmcp import FastMCP
        from sbl_probe.tools.connection import register_tools

        mgr = ConnectionManager()
        mcp = FastMCP("test")
        register_tools(mcp, mgr)

        result = asyncio.get_event_loop().run_until_complete(
            mcp.call_tool("close", {"name": "nope"})
        )
        assert any("error" in str(r).lower() for r in result)

    def test_read_raw_nonexistent_connection(self):
        """Reading from nonexistent connection returns error."""
        from mcp.server.fastmcp import FastMCP
        from sbl_probe.tools.data import register_tools

        mgr = ConnectionManager()
        mcp = FastMCP("test")
        register_tools(mcp, mgr)

        result = asyncio.get_event_loop().run_until_complete(
            mcp.call_tool("read_raw", {"name": "nope"})
        )
        assert any("error" in str(r).lower() for r in result)

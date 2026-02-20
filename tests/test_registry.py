"""Tests for decoder registry and protocol tools."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from sbl_probe.decoders import DecoderRegistry
from sbl_probe.decoders.raw import RawDecoder
from sbl_probe.tools.diagnostics import _score_data


class TestDecoderRegistry:
    def test_register_and_create(self):
        reg = DecoderRegistry()
        reg.register("raw", RawDecoder)
        dec = reg.create("raw")
        assert dec.name == "raw"

    def test_create_unknown_raises(self):
        reg = DecoderRegistry()
        with pytest.raises(ValueError, match="Unknown decoder 'nope'"):
            reg.create("nope")

    def test_error_message_lists_available(self):
        reg = DecoderRegistry()
        reg.register("raw", RawDecoder)
        with pytest.raises(ValueError, match="Available: raw"):
            reg.create("nope")

    def test_list(self):
        reg = DecoderRegistry()
        assert reg.list() == []
        reg.register("raw", RawDecoder)
        reg.register("abc", RawDecoder)  # just for testing
        assert reg.list() == ["abc", "raw"]  # sorted

    def test_default_registry_has_raw(self):
        from sbl_probe.decoders import registry
        assert "raw" in registry.list()
        dec = registry.create("raw")
        assert dec.name == "raw"


class TestSetDecoder:
    @patch("sbl_probe.transport.manager.SerialTransport")
    def test_set_decoder_on_connection(self, mock_transport_cls):
        from sbl_probe.transport.manager import ConnectionManager

        mock_transport = MagicMock()
        mock_transport.port = "/dev/ttyTEST"
        mock_transport.baudrate = 115200
        mock_transport.is_open = True
        mock_transport_cls.return_value = mock_transport

        mgr = ConnectionManager()
        conn = mgr.open("/dev/ttyTEST", name="test")
        assert conn.decoder.name == "raw"

        # Set to raw again (only decoder we have) — should create a fresh instance
        old_decoder = conn.decoder
        new_decoder = mgr.set_decoder("test", "raw")
        assert new_decoder.name == "raw"
        assert conn.decoder is not old_decoder

    @patch("sbl_probe.transport.manager.SerialTransport")
    def test_set_decoder_unknown_raises(self, mock_transport_cls):
        from sbl_probe.transport.manager import ConnectionManager

        mock_transport = MagicMock()
        mock_transport.port = "/dev/ttyTEST"
        mock_transport.is_open = True
        mock_transport_cls.return_value = mock_transport

        mgr = ConnectionManager()
        mgr.open("/dev/ttyTEST", name="test")

        with pytest.raises(ValueError, match="Unknown decoder"):
            mgr.set_decoder("test", "nonexistent")

    def test_set_decoder_no_connection_raises(self):
        from sbl_probe.transport.manager import ConnectionManager

        mgr = ConnectionManager()
        with pytest.raises(ValueError, match="No connection"):
            mgr.set_decoder("nope", "raw")


class TestDecodeBuffer:
    def test_decode_utf8(self):
        from mcp.server.fastmcp import FastMCP
        from sbl_probe.transport.manager import ConnectionManager
        from sbl_probe.tools.protocol import register_tools

        mgr = ConnectionManager()
        mcp = FastMCP("test")
        register_tools(mcp, mgr)

        result = asyncio.get_event_loop().run_until_complete(
            mcp.call_tool("decode_buffer", {
                "data": "line one\nline two\n",
                "decoder": "raw",
            })
        )
        # FastMCP returns list of content blocks
        assert any("line one" in str(r) for r in result)
        assert any("line two" in str(r) for r in result)

    def test_decode_hex(self):
        from mcp.server.fastmcp import FastMCP
        from sbl_probe.transport.manager import ConnectionManager
        from sbl_probe.tools.protocol import register_tools

        mgr = ConnectionManager()
        mcp = FastMCP("test")
        register_tools(mcp, mgr)

        # "hello\n" in hex
        result = asyncio.get_event_loop().run_until_complete(
            mcp.call_tool("decode_buffer", {
                "data": "68656c6c6f0a",
                "decoder": "raw",
                "encoding": "hex",
            })
        )
        assert any("hello" in str(r) for r in result)

    def test_decode_unknown_decoder(self):
        from mcp.server.fastmcp import FastMCP
        from sbl_probe.transport.manager import ConnectionManager
        from sbl_probe.tools.protocol import register_tools

        mgr = ConnectionManager()
        mcp = FastMCP("test")
        register_tools(mcp, mgr)

        result = asyncio.get_event_loop().run_until_complete(
            mcp.call_tool("decode_buffer", {
                "data": "test\n",
                "decoder": "nonexistent",
            })
        )
        assert any("error" in str(r).lower() for r in result)


class TestListDecoders:
    def test_list_decoders(self):
        from mcp.server.fastmcp import FastMCP
        from sbl_probe.transport.manager import ConnectionManager
        from sbl_probe.tools.protocol import register_tools

        mgr = ConnectionManager()
        mcp = FastMCP("test")
        register_tools(mcp, mgr)

        result = asyncio.get_event_loop().run_until_complete(
            mcp.call_tool("list_decoders", {})
        )
        assert any("raw" in str(r) for r in result)


class TestScoreData:
    def test_clean_ascii(self):
        assert _score_data(b"Hello, world!\n") == 1.0

    def test_pure_garbage(self):
        score = _score_data(bytes(range(128, 256)))
        assert score == 0.0

    def test_mixed(self):
        # 50% printable
        data = b"AB" + bytes([0x80, 0x81])
        score = _score_data(data)
        assert score == 0.5

    def test_empty(self):
        assert _score_data(b"") == 0.0

    def test_tabs_and_newlines_count(self):
        assert _score_data(b"\t\n\r") == 1.0

    def test_embedded_log_line(self):
        score = _score_data(b"K1=65535 K2=25993\r\n")
        assert score == 1.0


class TestProbeBaud:
    @patch("sbl_probe.tools.diagnostics.SerialTransport")
    def test_detects_correct_baud(self, mock_transport_cls):
        """When one baud rate yields clean text, it's detected."""

        def make_transport(port, baudrate):
            mock = MagicMock()
            mock.port = port
            mock.baudrate = baudrate
            if baudrate == 115200:
                mock.read.return_value = b"K1=65535 K2=25993\r\n"
            else:
                mock.read.return_value = bytes(range(128, 148))
            return mock

        mock_transport_cls.side_effect = make_transport

        from sbl_probe.tools.diagnostics import _try_baud

        # Good baud
        baud, score, nbytes = _try_baud("/dev/ttyTEST", 115200, 0.1)
        assert score > 0.8
        assert nbytes > 0

        # Bad baud
        baud, score, nbytes = _try_baud("/dev/ttyTEST", 9600, 0.1)
        assert score == 0.0

    @patch("sbl_probe.tools.diagnostics.SerialTransport")
    def test_no_data_returns_zero(self, mock_transport_cls):
        mock = MagicMock()
        mock.read.return_value = b""
        mock_transport_cls.return_value = mock

        from sbl_probe.tools.diagnostics import _try_baud

        baud, score, nbytes = _try_baud("/dev/ttyTEST", 9600, 0.1)
        assert score == 0.0
        assert nbytes == 0

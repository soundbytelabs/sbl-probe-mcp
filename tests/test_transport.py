"""Tests for transport layer with mocked serial ports."""

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from sbl_probe.transport.serial import SerialTransport
from sbl_probe.transport.manager import ConnectionManager, Connection


class TestSerialTransport:
    @patch("sbl_probe.transport.serial.serial.Serial")
    def test_open_close(self, mock_serial_cls):
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_cls.return_value = mock_ser

        t = SerialTransport("/dev/ttyTEST", baudrate=9600)
        assert not t.is_open

        t.open()
        assert t.is_open
        mock_serial_cls.assert_called_once_with(
            port="/dev/ttyTEST",
            baudrate=9600,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=0.05,
        )

        t.close()
        mock_ser.flush.assert_called_once()
        mock_ser.close.assert_called_once()

    @patch("sbl_probe.transport.serial.serial.Serial")
    def test_double_open_raises(self, mock_serial_cls):
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_serial_cls.return_value = mock_ser

        t = SerialTransport("/dev/ttyTEST")
        t.open()
        with pytest.raises(RuntimeError, match="already open"):
            t.open()

    @patch("sbl_probe.transport.serial.serial.Serial")
    def test_read(self, mock_serial_cls):
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_ser.read.return_value = b"hello"
        mock_serial_cls.return_value = mock_ser

        t = SerialTransport("/dev/ttyTEST")
        t.open()
        data = t.read(1024)
        assert data == b"hello"

    @patch("sbl_probe.transport.serial.serial.Serial")
    def test_write(self, mock_serial_cls):
        mock_ser = MagicMock()
        mock_ser.is_open = True
        mock_ser.write.return_value = 5
        mock_serial_cls.return_value = mock_ser

        t = SerialTransport("/dev/ttyTEST")
        t.open()
        n = t.write(b"hello")
        assert n == 5
        mock_ser.write.assert_called_once_with(b"hello")

    def test_read_when_closed(self):
        t = SerialTransport("/dev/ttyTEST")
        with pytest.raises(RuntimeError, match="not open"):
            t.read()

    def test_write_when_closed(self):
        t = SerialTransport("/dev/ttyTEST")
        with pytest.raises(RuntimeError, match="not open"):
            t.write(b"data")

    def test_port_property(self):
        t = SerialTransport("/dev/ttyAMA4")
        assert t.port == "/dev/ttyAMA4"

    def test_baudrate_property(self):
        t = SerialTransport("/dev/ttyAMA4", baudrate=9600)
        assert t.baudrate == 9600

    @patch("sbl_probe.transport.serial.serial.Serial")
    def test_close_idempotent(self, mock_serial_cls):
        """Closing a transport that's already closed doesn't raise."""
        t = SerialTransport("/dev/ttyTEST")
        t.close()  # Should not raise


class TestConnectionManager:
    @patch("sbl_probe.transport.manager.SerialTransport")
    def test_open_and_get(self, mock_transport_cls):
        mock_transport = MagicMock()
        mock_transport.port = "/dev/ttyTEST"
        mock_transport.baudrate = 115200
        mock_transport.is_open = True
        mock_transport_cls.return_value = mock_transport

        mgr = ConnectionManager()
        conn = mgr.open("/dev/ttyTEST", name="test")

        assert conn.name == "test"
        assert conn.bytes_in == 0
        assert conn.bytes_out == 0
        mock_transport.open.assert_called_once()

        # get returns same connection
        assert mgr.get("test") is conn

    @patch("sbl_probe.transport.manager.SerialTransport")
    def test_auto_naming(self, mock_transport_cls):
        mock_transport = MagicMock()
        mock_transport.port = "/dev/ttyAMA4"
        mock_transport.baudrate = 115200
        mock_transport.is_open = True
        mock_transport_cls.return_value = mock_transport

        mgr = ConnectionManager()
        conn = mgr.open("/dev/ttyAMA4")
        assert conn.name == "ttyAMA4"

    @patch("sbl_probe.transport.manager.SerialTransport")
    def test_duplicate_name_raises(self, mock_transport_cls):
        mock_transport = MagicMock()
        mock_transport.port = "/dev/ttyTEST"
        mock_transport.is_open = True
        mock_transport_cls.return_value = mock_transport

        mgr = ConnectionManager()
        mgr.open("/dev/ttyTEST", name="test")
        with pytest.raises(ValueError, match="already exists"):
            mgr.open("/dev/ttyTEST2", name="test")

    @patch("sbl_probe.transport.manager.SerialTransport")
    def test_duplicate_port_raises(self, mock_transport_cls):
        mock_transport = MagicMock()
        mock_transport.port = "/dev/ttyTEST"
        mock_transport.is_open = True
        mock_transport_cls.return_value = mock_transport

        mgr = ConnectionManager()
        mgr.open("/dev/ttyTEST", name="a")
        with pytest.raises(ValueError, match="already open"):
            mgr.open("/dev/ttyTEST", name="b")

    @patch("sbl_probe.transport.manager.SerialTransport")
    def test_close(self, mock_transport_cls):
        mock_transport = MagicMock()
        mock_transport.port = "/dev/ttyTEST"
        mock_transport.is_open = True
        mock_transport_cls.return_value = mock_transport

        mgr = ConnectionManager()
        mgr.open("/dev/ttyTEST", name="test")
        mgr.close("test")

        mock_transport.close.assert_called_once()
        with pytest.raises(ValueError, match="No connection"):
            mgr.get("test")

    def test_close_nonexistent_raises(self):
        mgr = ConnectionManager()
        with pytest.raises(ValueError, match="No connection"):
            mgr.close("nope")

    def test_get_nonexistent_raises(self):
        mgr = ConnectionManager()
        with pytest.raises(ValueError, match="No connection"):
            mgr.get("nope")

    @patch("sbl_probe.transport.manager.SerialTransport")
    def test_list(self, mock_transport_cls):
        mock_transport = MagicMock()
        mock_transport.port = "/dev/ttyTEST"
        mock_transport.baudrate = 115200
        mock_transport.is_open = True
        mock_transport_cls.return_value = mock_transport

        mgr = ConnectionManager()
        assert mgr.list() == []

        mgr.open("/dev/ttyTEST", name="test")
        conns = mgr.list()
        assert len(conns) == 1
        assert conns[0].name == "test"

    @patch("sbl_probe.transport.manager.SerialTransport")
    def test_close_all(self, mock_transport_cls):
        transports = []

        def make_transport(**kwargs):
            m = MagicMock()
            m.port = kwargs.get("port", "/dev/ttyTEST")
            m.baudrate = kwargs.get("baudrate", 115200)
            m.is_open = True
            transports.append(m)
            return m

        mock_transport_cls.side_effect = make_transport

        mgr = ConnectionManager()
        mgr.open("/dev/tty1", name="a")
        mgr.open("/dev/tty2", name="b")
        mgr.close_all()

        for t in transports:
            t.close.assert_called_once()
        assert mgr.list() == []


class TestConnectionToDict:
    @patch("sbl_probe.transport.manager.SerialTransport")
    def test_to_dict(self, mock_transport_cls):
        mock_transport = MagicMock()
        mock_transport.port = "/dev/ttyAMA4"
        mock_transport.baudrate = 115200
        mock_transport.is_open = True
        mock_transport_cls.return_value = mock_transport

        mgr = ConnectionManager()
        conn = mgr.open("/dev/ttyAMA4", name="daisy")
        conn.bytes_in = 100
        conn.bytes_out = 50

        d = conn.to_dict()
        assert d["name"] == "daisy"
        assert d["port"] == "/dev/ttyAMA4"
        assert d["baudrate"] == 115200
        assert d["is_open"] is True
        assert d["bytes_in"] == 100
        assert d["bytes_out"] == 50
        assert d["decoder"] == "raw"
        assert "uptime_seconds" in d

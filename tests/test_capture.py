"""Tests for capture engine, buffer, and storage."""

import json
import time
import threading
from unittest.mock import MagicMock, patch

import pytest

from sbl_probe.capture.buffer import CaptureBuffer
from sbl_probe.capture.engine import CaptureEngine
from sbl_probe.capture.storage import save_jsonl, load_jsonl
from sbl_probe.decoders.base import Frame
from sbl_probe.decoders.raw import RawDecoder


def _make_frame(text: str, ts: float = 1.0) -> Frame:
    return Frame(
        timestamp=ts,
        protocol="raw",
        direction="rx",
        data=text.encode("utf-8"),
    )


class TestCaptureBuffer:
    def test_append_and_len(self):
        buf = CaptureBuffer(max_frames=100)
        assert len(buf) == 0
        buf.append(_make_frame("hello"))
        assert len(buf) == 1
        assert buf.stats.frames_captured == 1

    def test_ring_behavior(self):
        buf = CaptureBuffer(max_frames=3)
        buf.append(_make_frame("a"))
        buf.append(_make_frame("b"))
        buf.append(_make_frame("c"))
        buf.append(_make_frame("d"))  # should drop "a"
        assert len(buf) == 3
        assert buf.stats.frames_captured == 4
        assert buf.stats.frames_dropped == 1
        frames = buf.query()
        assert [f.data for f in frames] == [b"b", b"c", b"d"]

    def test_extend(self):
        buf = CaptureBuffer(max_frames=100)
        frames = [_make_frame("a"), _make_frame("b"), _make_frame("c")]
        buf.extend(frames)
        assert len(buf) == 3
        assert buf.stats.frames_captured == 3

    def test_query_all(self):
        buf = CaptureBuffer(max_frames=100)
        buf.append(_make_frame("a"))
        buf.append(_make_frame("b"))
        frames = buf.query()
        assert len(frames) == 2

    def test_query_last_n(self):
        buf = CaptureBuffer(max_frames=100)
        for i in range(10):
            buf.append(_make_frame(f"line{i}"))
        frames = buf.query(last_n=3)
        assert len(frames) == 3
        assert frames[0].data == b"line7"

    def test_query_pattern(self):
        buf = CaptureBuffer(max_frames=100)
        buf.append(_make_frame("K1=65535 K2=25993"))
        buf.append(_make_frame("ERROR: something broke"))
        buf.append(_make_frame("K1=65530 K2=25100"))
        frames = buf.query(pattern=r"ERROR")
        assert len(frames) == 1
        assert b"ERROR" in frames[0].data

    def test_query_pattern_regex(self):
        buf = CaptureBuffer(max_frames=100)
        buf.append(_make_frame("K1=65535 K2=25993"))
        buf.append(_make_frame("K1=65530 K2=25100"))
        buf.append(_make_frame("K1=0 K2=0"))
        frames = buf.query(pattern=r"K2=251\d+")
        assert len(frames) == 1

    def test_query_since(self):
        buf = CaptureBuffer(max_frames=100)
        buf.append(_make_frame("old", ts=1.0))
        buf.append(_make_frame("mid", ts=5.0))
        buf.append(_make_frame("new", ts=10.0))
        frames = buf.query(since=5.0)
        assert len(frames) == 2
        assert frames[0].data == b"mid"

    def test_query_until(self):
        buf = CaptureBuffer(max_frames=100)
        buf.append(_make_frame("old", ts=1.0))
        buf.append(_make_frame("mid", ts=5.0))
        buf.append(_make_frame("new", ts=10.0))
        frames = buf.query(until=5.0)
        assert len(frames) == 2
        assert frames[-1].data == b"mid"

    def test_query_since_until(self):
        buf = CaptureBuffer(max_frames=100)
        buf.append(_make_frame("a", ts=1.0))
        buf.append(_make_frame("b", ts=3.0))
        buf.append(_make_frame("c", ts=5.0))
        buf.append(_make_frame("d", ts=7.0))
        frames = buf.query(since=2.0, until=6.0)
        assert len(frames) == 2
        assert frames[0].data == b"b"
        assert frames[1].data == b"c"

    def test_query_combined_filters(self):
        buf = CaptureBuffer(max_frames=100)
        buf.append(_make_frame("K1=100", ts=1.0))
        buf.append(_make_frame("ERROR: bad", ts=2.0))
        buf.append(_make_frame("K1=200", ts=3.0))
        buf.append(_make_frame("ERROR: worse", ts=4.0))
        # Pattern + since + last_n
        frames = buf.query(pattern=r"ERROR", since=1.5, last_n=1)
        assert len(frames) == 1
        assert frames[0].data == b"ERROR: worse"

    def test_clear(self):
        buf = CaptureBuffer(max_frames=100)
        buf.append(_make_frame("data"))
        buf.clear()
        assert len(buf) == 0

    def test_thread_safety(self):
        """Concurrent appends don't crash."""
        buf = CaptureBuffer(max_frames=1000)
        errors = []

        def writer(start):
            try:
                for i in range(100):
                    buf.append(_make_frame(f"thread-{start}-{i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(buf) == 400


class TestCaptureEngine:
    def test_start_stop_lifecycle(self):
        """Engine starts, captures frames, and stops cleanly."""
        transport = MagicMock()
        transport.is_open = True
        # Simulate serial data arriving
        call_count = 0

        def mock_read(size=4096, timeout=0.05):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                return f"line{call_count}\n".encode()
            return b""

        transport.read.side_effect = mock_read

        decoder = RawDecoder()
        buf = CaptureBuffer(max_frames=100)
        engine = CaptureEngine(transport, decoder, buf)

        assert not engine.is_running
        engine.start()
        assert engine.is_running

        # Give the reader thread time to process
        time.sleep(0.3)

        summary = engine.stop()
        assert not engine.is_running
        assert summary["frames_captured"] >= 1
        assert summary["bytes_processed"] > 0
        assert len(buf) >= 1

    def test_double_start_raises(self):
        transport = MagicMock()
        transport.read.return_value = b""
        decoder = RawDecoder()
        buf = CaptureBuffer()
        engine = CaptureEngine(transport, decoder, buf)

        engine.start()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                engine.start()
        finally:
            engine.stop()

    def test_stop_when_not_running_raises(self):
        transport = MagicMock()
        decoder = RawDecoder()
        buf = CaptureBuffer()
        engine = CaptureEngine(transport, decoder, buf)

        with pytest.raises(RuntimeError, match="not running"):
            engine.stop()

    def test_error_handling(self):
        """Transport errors increment error count but don't kill the thread."""
        transport = MagicMock()
        transport.is_open = True
        call_count = 0

        def mock_read(size=4096, timeout=0.05):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Port vanished")
            return b""

        transport.read.side_effect = mock_read

        decoder = RawDecoder()
        buf = CaptureBuffer()
        engine = CaptureEngine(transport, decoder, buf)

        engine.start()
        time.sleep(0.3)
        summary = engine.stop()

        assert summary["errors"] >= 1

    def test_buffer_accessible_during_capture(self):
        """Can query the buffer while capture is running."""
        transport = MagicMock()
        call_count = 0

        def mock_read(size=4096, timeout=0.05):
            nonlocal call_count
            call_count += 1
            if call_count <= 5:
                return f"data{call_count}\n".encode()
            return b""

        transport.read.side_effect = mock_read

        decoder = RawDecoder()
        buf = CaptureBuffer()
        engine = CaptureEngine(transport, decoder, buf)

        engine.start()
        time.sleep(0.3)

        # Query while still capturing
        frames = buf.query()
        assert len(frames) >= 1

        engine.stop()


class TestStorage:
    def test_save_and_load_roundtrip(self, tmp_path):
        frames = [
            _make_frame("hello world", ts=1.0),
            _make_frame("K1=65535 K2=25993", ts=2.0),
        ]
        path = tmp_path / "capture.jsonl"
        count = save_jsonl(frames, path)
        assert count == 2

        loaded = load_jsonl(path)
        assert len(loaded) == 2
        assert loaded[0]["text"] == "hello world"
        assert loaded[1]["text"] == "K1=65535 K2=25993"

    def test_save_creates_directories(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "capture.jsonl"
        save_jsonl([_make_frame("test")], path)
        assert path.exists()

    def test_load_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        loaded = load_jsonl(path)
        assert loaded == []

    def test_jsonl_format(self, tmp_path):
        """Verify each line is valid JSON."""
        frames = [_make_frame("a"), _make_frame("b")]
        path = tmp_path / "capture.jsonl"
        save_jsonl(frames, path)

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert "timestamp" in obj
            assert "data_hex" in obj


class TestConnectionCaptureState:
    @patch("sbl_probe.transport.manager.SerialTransport")
    def test_to_dict_shows_capture_state(self, mock_transport_cls):
        from sbl_probe.transport.manager import ConnectionManager

        mock_transport = MagicMock()
        mock_transport.port = "/dev/ttyTEST"
        mock_transport.baudrate = 115200
        mock_transport.is_open = True
        mock_transport.read.return_value = b""
        mock_transport_cls.return_value = mock_transport

        mgr = ConnectionManager()
        conn = mgr.open("/dev/ttyTEST", name="test")

        d = conn.to_dict()
        assert d["capturing"] is False
        assert "capture_frames" not in d

    @patch("sbl_probe.transport.manager.SerialTransport")
    def test_close_stops_capture(self, mock_transport_cls):
        from sbl_probe.transport.manager import ConnectionManager
        from sbl_probe.capture.buffer import CaptureBuffer
        from sbl_probe.capture.engine import CaptureEngine

        mock_transport = MagicMock()
        mock_transport.port = "/dev/ttyTEST"
        mock_transport.baudrate = 115200
        mock_transport.is_open = True
        mock_transport.read.return_value = b""
        mock_transport_cls.return_value = mock_transport

        mgr = ConnectionManager()
        conn = mgr.open("/dev/ttyTEST", name="test")

        # Start a capture
        buf = CaptureBuffer()
        engine = CaptureEngine(conn.transport, conn.decoder, buf)
        conn.capture = engine
        engine.start()
        assert conn.is_capturing

        # Close should stop the capture
        mgr.close("test")
        assert not engine.is_running

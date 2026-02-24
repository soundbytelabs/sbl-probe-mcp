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

    def test_start_with_duration_auto_stops(self):
        """Engine auto-stops after the specified duration."""
        transport = MagicMock()
        call_count = 0

        def mock_read(size=4096, timeout=0.05):
            nonlocal call_count
            call_count += 1
            return f"line{call_count}\n".encode()

        transport.read.side_effect = mock_read

        decoder = RawDecoder()
        buf = CaptureBuffer(max_frames=100)
        engine = CaptureEngine(transport, decoder, buf)

        engine.start(duration=0.2)
        assert engine.is_running

        # Wait for duration to expire
        time.sleep(0.5)
        assert not engine.is_running
        assert len(buf) >= 1

    def test_stop_after_duration_expired(self):
        """Calling stop() after duration expired returns summary without error."""
        transport = MagicMock()
        transport.read.return_value = b"data\n"

        decoder = RawDecoder()
        buf = CaptureBuffer(max_frames=100)
        engine = CaptureEngine(transport, decoder, buf)

        engine.start(duration=0.1)
        time.sleep(0.3)

        # Thread has exited, but stop() should still work
        assert not engine.is_running
        summary = engine.stop()
        assert "frames_captured" in summary
        assert "duration_seconds" in summary

    def test_duration_early_stop(self):
        """Calling stop() before duration expires stops cleanly."""
        transport = MagicMock()
        transport.read.return_value = b""

        decoder = RawDecoder()
        buf = CaptureBuffer(max_frames=100)
        engine = CaptureEngine(transport, decoder, buf)

        engine.start(duration=10.0)  # Long duration
        assert engine.is_running

        summary = engine.stop()
        assert not engine.is_running
        assert "frames_captured" in summary

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


class TestIngressFilter:
    """Tests for the capture engine ingress filter (FDP-002 feature 1)."""

    def test_filter_passes_matching_frames(self):
        transport = MagicMock()
        call_count = 0

        def mock_read(size=4096, timeout=0.05):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return b"enc delta: 5\n"
            if call_count == 2:
                return b"knob1: 32000\n"
            if call_count == 3:
                return b"enc delta: -3\n"
            return b""

        transport.read.side_effect = mock_read
        decoder = RawDecoder()
        buf = CaptureBuffer(max_frames=100)
        engine = CaptureEngine(transport, decoder, buf, filter_pattern=r"enc delta")

        engine.start()
        time.sleep(0.3)
        engine.stop()

        frames = buf.query()
        assert len(frames) == 2
        assert all(b"enc delta" in f.data for f in frames)

    def test_filter_rejects_non_matching_frames(self):
        transport = MagicMock()
        call_count = 0

        def mock_read(size=4096, timeout=0.05):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                return f"knob{call_count}: {call_count * 1000}\n".encode()
            return b""

        transport.read.side_effect = mock_read
        decoder = RawDecoder()
        buf = CaptureBuffer(max_frames=100)
        engine = CaptureEngine(transport, decoder, buf, filter_pattern=r"enc delta")

        engine.start()
        time.sleep(0.3)
        engine.stop()

        assert len(buf) == 0
        assert buf.stats.frames_filtered == 3

    def test_filter_tracks_filtered_count(self):
        transport = MagicMock()
        call_count = 0

        def mock_read(size=4096, timeout=0.05):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return b"enc delta: 5\n"
            if call_count == 2:
                return b"knob1: 32000\n"
            if call_count == 3:
                return b"knob2: 16000\n"
            return b""

        transport.read.side_effect = mock_read
        decoder = RawDecoder()
        buf = CaptureBuffer(max_frames=100)
        engine = CaptureEngine(transport, decoder, buf, filter_pattern=r"enc")

        engine.start()
        time.sleep(0.3)
        summary = engine.stop()

        assert len(buf) == 1
        assert buf.stats.frames_filtered == 2
        assert summary["frames_filtered"] == 2

    def test_no_filter_buffers_everything(self):
        transport = MagicMock()
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

        engine.start()
        time.sleep(0.3)
        engine.stop()

        assert len(buf) == 3
        assert buf.stats.frames_filtered == 0

    def test_filter_with_regex(self):
        transport = MagicMock()
        call_count = 0

        def mock_read(size=4096, timeout=0.05):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return b"btn1: pressed\n"
            if call_count == 2:
                return b"btn2: released\n"
            if call_count == 3:
                return b"enc delta: 5\n"
            return b""

        transport.read.side_effect = mock_read
        decoder = RawDecoder()
        buf = CaptureBuffer(max_frames=100)
        engine = CaptureEngine(transport, decoder, buf, filter_pattern=r"btn\d+")

        engine.start()
        time.sleep(0.3)
        engine.stop()

        assert len(buf) == 2
        assert buf.stats.frames_filtered == 1


class TestGroupCounts:
    """Tests for CaptureBuffer.group_counts (FDP-002 feature 2)."""

    def test_empty_buffer(self):
        buf = CaptureBuffer(max_frames=100)
        counts = buf.group_counts({"enc": "enc", "btn": "btn"})
        assert counts == {"enc": 0, "btn": 0, "unmatched": 0}

    def test_single_group(self):
        buf = CaptureBuffer(max_frames=100)
        buf.append(_make_frame("enc delta: 5"))
        buf.append(_make_frame("enc delta: -3"))
        buf.append(_make_frame("other stuff"))
        counts = buf.group_counts({"enc": "enc delta"})
        assert counts == {"enc": 2, "unmatched": 1}

    def test_multiple_groups(self):
        buf = CaptureBuffer(max_frames=100)
        buf.append(_make_frame("enc delta: 5"))
        buf.append(_make_frame("btn1: pressed"))
        buf.append(_make_frame("knob1: 32000"))
        buf.append(_make_frame("enc delta: -3"))
        buf.append(_make_frame("btn2: released"))
        buf.append(_make_frame("knob2: 16000"))
        buf.append(_make_frame("something else"))

        counts = buf.group_counts({
            "enc": r"enc delta",
            "btn": r"btn\d+",
            "knob": r"knob\d+",
        })
        assert counts == {"enc": 2, "btn": 2, "knob": 2, "unmatched": 1}

    def test_first_match_wins(self):
        buf = CaptureBuffer(max_frames=100)
        # "enc btn" matches both groups — first group wins
        buf.append(_make_frame("enc btn combo"))
        counts = buf.group_counts({"enc": "enc", "btn": "btn"})
        assert counts == {"enc": 1, "btn": 0, "unmatched": 0}

    def test_all_unmatched(self):
        buf = CaptureBuffer(max_frames=100)
        buf.append(_make_frame("random data"))
        buf.append(_make_frame("more stuff"))
        counts = buf.group_counts({"enc": "enc", "btn": "btn"})
        assert counts == {"enc": 0, "btn": 0, "unmatched": 2}

    def test_counts_add_up_to_buffer_size(self):
        buf = CaptureBuffer(max_frames=100)
        for i in range(10):
            buf.append(_make_frame(f"enc delta: {i}"))
        for i in range(5):
            buf.append(_make_frame(f"btn{i}: pressed"))
        for i in range(3):
            buf.append(_make_frame(f"misc {i}"))

        counts = buf.group_counts({"enc": "enc", "btn": "btn"})
        total = sum(counts.values())
        assert total == len(buf)


class TestTriggerMode:
    """Tests for capture engine trigger mode (FDP-002 feature 3)."""

    def test_trigger_fires(self):
        transport = MagicMock()
        call_count = 0

        def mock_read(size=4096, timeout=0.05):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return b"idle noise\n"
            if call_count == 2:
                return b"more noise\n"
            if call_count == 3:
                return b"ERROR: something broke\n"
            if call_count == 4:
                return b"post-error data\n"
            return b""

        transport.read.side_effect = mock_read
        decoder = RawDecoder()
        buf = CaptureBuffer(max_frames=100)
        engine = CaptureEngine(
            transport, decoder, buf, trigger_pattern=r"ERROR"
        )

        assert not engine.triggered
        engine.start()
        time.sleep(0.4)
        summary = engine.stop()

        assert engine.triggered
        assert summary["triggered"] is True
        assert "trigger_at" in summary
        # Should have captured the trigger frame + post-trigger
        frames = buf.query()
        assert len(frames) >= 1
        assert any(b"ERROR" in f.data for f in frames)
        # Pre-trigger noise should NOT be in buffer
        assert not any(b"idle noise" in f.data for f in frames)

    def test_trigger_never_fires(self):
        transport = MagicMock()
        call_count = 0

        def mock_read(size=4096, timeout=0.05):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                return f"normal line {call_count}\n".encode()
            return b""

        transport.read.side_effect = mock_read
        decoder = RawDecoder()
        buf = CaptureBuffer(max_frames=100)
        engine = CaptureEngine(
            transport, decoder, buf, trigger_pattern=r"ERROR"
        )

        engine.start()
        time.sleep(0.3)
        summary = engine.stop()

        assert not engine.triggered
        assert summary["triggered"] is False
        assert len(buf) == 0

    def test_pretrigger_flushes_context(self):
        transport = MagicMock()
        call_count = 0

        def mock_read(size=4096, timeout=0.05):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return b"context-1\n"
            if call_count == 2:
                return b"context-2\n"
            if call_count == 3:
                return b"context-3\n"
            if call_count == 4:
                return b"ERROR: crash\n"
            if call_count == 5:
                return b"aftermath\n"
            return b""

        transport.read.side_effect = mock_read
        decoder = RawDecoder()
        buf = CaptureBuffer(max_frames=100)
        engine = CaptureEngine(
            transport, decoder, buf,
            trigger_pattern=r"ERROR",
            pretrigger=2,
        )

        engine.start()
        time.sleep(0.5)
        engine.stop()

        frames = buf.query()
        texts = [f.data.decode() for f in frames]
        # Should have pretrigger context + trigger + aftermath
        assert "context-2" in texts
        assert "context-3" in texts
        assert "ERROR: crash" in texts
        # context-1 is outside pretrigger window (only 2 kept)
        assert "context-1" not in texts

    def test_pretrigger_overflow(self):
        """Pretrigger deque evicts oldest when full."""
        transport = MagicMock()
        call_count = 0

        def mock_read(size=4096, timeout=0.05):
            nonlocal call_count
            call_count += 1
            if call_count <= 10:
                return f"pre-{call_count}\n".encode()
            if call_count == 11:
                return b"TRIGGER\n"
            return b""

        transport.read.side_effect = mock_read
        decoder = RawDecoder()
        buf = CaptureBuffer(max_frames=100)
        engine = CaptureEngine(
            transport, decoder, buf,
            trigger_pattern=r"TRIGGER",
            pretrigger=3,
        )

        engine.start()
        time.sleep(0.5)
        engine.stop()

        frames = buf.query()
        texts = [f.data.decode() for f in frames]
        # Only last 3 pre-trigger frames + trigger
        assert "TRIGGER" in texts
        assert "pre-8" in texts
        assert "pre-9" in texts
        assert "pre-10" in texts
        assert "pre-1" not in texts
        assert "pre-7" not in texts

    def test_trigger_plus_filter_compose(self):
        """Filter runs first, then trigger checks filtered frames."""
        transport = MagicMock()
        call_count = 0

        def mock_read(size=4096, timeout=0.05):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return b"knob1: 30000\n"  # filtered out
            if call_count == 2:
                return b"btn1: pressed\n"  # passes filter, not trigger
            if call_count == 3:
                return b"btn1: ERROR\n"  # passes filter, IS trigger
            if call_count == 4:
                return b"btn2: released\n"  # passes filter, post-trigger
            if call_count == 5:
                return b"knob2: 16000\n"  # filtered out
            return b""

        transport.read.side_effect = mock_read
        decoder = RawDecoder()
        buf = CaptureBuffer(max_frames=100)
        engine = CaptureEngine(
            transport, decoder, buf,
            filter_pattern=r"btn",
            trigger_pattern=r"ERROR",
        )

        engine.start()
        time.sleep(0.5)
        engine.stop()

        frames = buf.query()
        texts = [f.data.decode() for f in frames]
        # Only btn frames after trigger
        assert "btn1: ERROR" in texts
        assert "btn2: released" in texts
        # Pre-trigger btn frame not buffered (no pretrigger)
        assert "btn1: pressed" not in texts
        # Knob frames always filtered
        assert not any("knob" in t for t in texts)
        assert buf.stats.frames_filtered >= 2

    def test_no_trigger_captures_immediately(self):
        """Without trigger, capture starts immediately (backwards compat)."""
        transport = MagicMock()
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

        assert engine.triggered  # No trigger = already triggered
        engine.start()
        time.sleep(0.3)
        engine.stop()

        assert len(buf) == 3

    def test_trigger_mid_batch(self):
        """Trigger fires mid-batch — frames after trigger in same batch are buffered."""
        transport = MagicMock()
        call_count = 0

        def mock_read(size=4096, timeout=0.05):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Multiple lines in one read — trigger is in the middle
                return b"before\nTRIGGER\nafter\n"
            return b""

        transport.read.side_effect = mock_read
        decoder = RawDecoder()
        buf = CaptureBuffer(max_frames=100)
        engine = CaptureEngine(
            transport, decoder, buf, trigger_pattern=r"TRIGGER"
        )

        engine.start()
        time.sleep(0.3)
        engine.stop()

        frames = buf.query()
        texts = [f.data.decode() for f in frames]
        assert "TRIGGER" in texts
        assert "after" in texts
        assert "before" not in texts

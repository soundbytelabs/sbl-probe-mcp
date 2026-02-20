"""Tests for protocol decoders."""

import time

from sbl_probe.decoders.base import Frame, Decoder
from sbl_probe.decoders.raw import RawDecoder


class TestFrame:
    def test_to_dict_basic(self):
        f = Frame(
            timestamp=1.0,
            protocol="raw",
            direction="rx",
            data=b"hello",
        )
        d = f.to_dict()
        assert d["timestamp"] == 1.0
        assert d["protocol"] == "raw"
        assert d["direction"] == "rx"
        assert d["data_hex"] == "68656c6c6f"
        assert d["text"] == "hello"
        assert "decoded" not in d
        assert "error" not in d

    def test_to_dict_with_decoded_and_error(self):
        f = Frame(
            timestamp=2.5,
            protocol="uart_log",
            direction="rx",
            data=b"test",
            decoded={"level": "INFO"},
            error="parity",
        )
        d = f.to_dict()
        assert d["decoded"] == {"level": "INFO"}
        assert d["error"] == "parity"

    def test_frozen(self):
        f = Frame(timestamp=1.0, protocol="raw", direction="rx", data=b"x")
        try:
            f.timestamp = 2.0  # type: ignore
            assert False, "Should be frozen"
        except AttributeError:
            pass


class TestRawDecoder:
    def test_protocol_compliance(self):
        """RawDecoder satisfies the Decoder protocol."""
        assert isinstance(RawDecoder(), Decoder)

    def test_name(self):
        assert RawDecoder().name == "raw"

    def test_single_complete_line(self):
        dec = RawDecoder()
        frames = dec.feed(b"hello world\n", 1.0)
        assert len(frames) == 1
        assert frames[0].data == b"hello world"
        assert frames[0].timestamp == 1.0
        assert frames[0].protocol == "raw"
        assert frames[0].direction == "rx"

    def test_multiple_lines(self):
        dec = RawDecoder()
        frames = dec.feed(b"line1\nline2\nline3\n", 1.0)
        assert len(frames) == 3
        assert frames[0].data == b"line1"
        assert frames[1].data == b"line2"
        assert frames[2].data == b"line3"

    def test_partial_line_buffered(self):
        dec = RawDecoder()
        # No newline yet — should buffer
        frames = dec.feed(b"partial", 1.0)
        assert len(frames) == 0

        # Now complete the line
        frames = dec.feed(b" data\n", 2.0)
        assert len(frames) == 1
        assert frames[0].data == b"partial data"

    def test_crlf_handling(self):
        dec = RawDecoder()
        frames = dec.feed(b"windows\r\n", 1.0)
        assert len(frames) == 1
        assert frames[0].data == b"windows"

    def test_mixed_line_endings(self):
        dec = RawDecoder()
        frames = dec.feed(b"unix\nwindows\r\nmore\n", 1.0)
        assert len(frames) == 3
        assert frames[0].data == b"unix"
        assert frames[1].data == b"windows"
        assert frames[2].data == b"more"

    def test_empty_lines_skipped(self):
        dec = RawDecoder()
        frames = dec.feed(b"hello\n\nworld\n", 1.0)
        assert len(frames) == 2
        assert frames[0].data == b"hello"
        assert frames[1].data == b"world"

    def test_empty_input(self):
        dec = RawDecoder()
        frames = dec.feed(b"", 1.0)
        assert len(frames) == 0

    def test_flush(self):
        dec = RawDecoder()
        dec.feed(b"no newline", 1.0)
        frames = dec.flush()
        assert len(frames) == 1
        assert frames[0].data == b"no newline"

    def test_flush_empty(self):
        dec = RawDecoder()
        frames = dec.flush()
        assert len(frames) == 0

    def test_reset(self):
        dec = RawDecoder()
        dec.feed(b"buffered", 1.0)
        dec.reset()
        frames = dec.flush()
        assert len(frames) == 0

    def test_binary_data(self):
        dec = RawDecoder()
        frames = dec.feed(b"\x00\x01\x02\n\xff\xfe\n", 1.0)
        assert len(frames) == 2
        assert frames[0].data == b"\x00\x01\x02"
        assert frames[1].data == b"\xff\xfe"

    def test_sbl_log_line(self):
        """Typical SBL debug output."""
        dec = RawDecoder()
        frames = dec.feed(b"[00032150] ADC: ch0=2048 ch1=1891\r\n", 1.0)
        assert len(frames) == 1
        assert frames[0].data == b"[00032150] ADC: ch0=2048 ch1=1891"

"""Tests for the MIDI decoder."""

from sbl_probe.decoders.base import Decoder
from sbl_probe.decoders.midi import MidiDecoder, note_name


class TestNoteNames:
    def test_c4(self):
        assert note_name(60) == "C4"

    def test_a4(self):
        assert note_name(69) == "A4"

    def test_c_minus1(self):
        assert note_name(0) == "C-1"

    def test_middle_range(self):
        assert note_name(48) == "C3"
        assert note_name(72) == "C5"

    def test_sharps(self):
        assert note_name(61) == "C#4"
        assert note_name(70) == "A#4"

    def test_g9(self):
        assert note_name(127) == "G9"


class TestProtocolCompliance:
    def test_satisfies_decoder_protocol(self):
        assert isinstance(MidiDecoder(), Decoder)

    def test_name(self):
        assert MidiDecoder().name == "midi"


class TestNoteMessages:
    def test_note_on(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0x90, 60, 127]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "NoteOn ch=1 note=60(C4) vel=127"
        assert frames[0].protocol == "midi"
        assert frames[0].direction == "rx"

    def test_note_on_channel_10(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0x99, 36, 100]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "NoteOn ch=10 note=36(C2) vel=100"

    def test_note_off(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0x80, 60, 0]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "NoteOff ch=1 note=60(C4) vel=0"

    def test_note_on_velocity_zero_is_still_note_on(self):
        """MIDI convention: NoteOn vel=0 is equivalent to NoteOff, but we
        decode the actual message type, not the semantic meaning."""
        dec = MidiDecoder()
        frames = dec.feed(bytes([0x90, 60, 0]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "NoteOn ch=1 note=60(C4) vel=0"


class TestControlChange:
    def test_cc(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xB0, 74, 127]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "CC ch=1 cc=74 val=127"

    def test_cc_channel_16(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xBF, 1, 64]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "CC ch=16 cc=1 val=64"


class TestProgramChange:
    def test_program_change(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xC0, 5]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "PgmChg ch=1 pgm=5"


class TestPitchBend:
    def test_pitch_bend_center(self):
        dec = MidiDecoder()
        # Center = 8192 = 0x2000 -> LSB=0x00, MSB=0x40
        frames = dec.feed(bytes([0xE0, 0x00, 0x40]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "PitchBend ch=1 val=8192"

    def test_pitch_bend_max(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xE0, 0x7F, 0x7F]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "PitchBend ch=1 val=16383"

    def test_pitch_bend_min(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xE0, 0x00, 0x00]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "PitchBend ch=1 val=0"


class TestPressure:
    def test_channel_pressure(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xD0, 64]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "ChanPres ch=1 val=64"

    def test_poly_pressure(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xA0, 60, 64]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "PolyPres ch=1 note=60 val=64"


class TestSystemRealTime:
    def test_clock(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xF8]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "Clock"

    def test_start(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xFA]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "Start"

    def test_continue(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xFB]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "Continue"

    def test_stop(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xFC]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "Stop"

    def test_active_sensing(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xFE]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "ActiveSensing"

    def test_system_reset(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xFF]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "Reset"

    def test_realtime_mid_message(self):
        """Real-time messages can appear mid-message without disturbing state."""
        dec = MidiDecoder()
        # Note On, then clock between data bytes
        frames = dec.feed(bytes([0x90, 60]), 1.0)
        assert len(frames) == 0  # Incomplete note on

        frames = dec.feed(bytes([0xF8]), 1.0)  # Clock mid-message
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "Clock"

        frames = dec.feed(bytes([127]), 1.0)  # Velocity completes note on
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "NoteOn ch=1 note=60(C4) vel=127"

    def test_undefined_realtime_ignored(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xF9]), 1.0)
        assert len(frames) == 0
        frames = dec.feed(bytes([0xFD]), 1.0)
        assert len(frames) == 0


class TestSysEx:
    def test_basic_sysex(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xF0, 0x7E, 0x01, 0x06, 0x01, 0xF7]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "SysEx [6 bytes]"
        assert frames[0].data == bytes([0xF0, 0x7E, 0x01, 0x06, 0x01, 0xF7])

    def test_sysex_across_feeds(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xF0, 0x7E, 0x01]), 1.0)
        assert len(frames) == 0

        frames = dec.feed(bytes([0x06, 0x01, 0xF7]), 2.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "SysEx [6 bytes]"

    def test_realtime_during_sysex(self):
        """Real-time messages pass through during SysEx without terminating it."""
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xF0, 0x01, 0xF8, 0x02, 0xF7]), 1.0)
        assert len(frames) == 2
        assert frames[0].decoded["message"] == "Clock"
        assert frames[1].decoded["message"] == "SysEx [4 bytes]"
        # SysEx payload should not contain the clock byte
        assert frames[1].data == bytes([0xF0, 0x01, 0x02, 0xF7])

    def test_sysex_terminated_by_status(self):
        """Non-real-time status byte terminates SysEx abnormally."""
        dec = MidiDecoder()
        # SysEx followed by Note On — SysEx is dropped, Note On is parsed
        frames = dec.feed(bytes([0xF0, 0x01, 0x02, 0x90, 60, 127]), 1.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "NoteOn ch=1 note=60(C4) vel=127"


class TestRunningStatus:
    def test_running_status_note_on(self):
        """Multiple notes using running status (status byte omitted)."""
        dec = MidiDecoder()
        # First note with status, second without
        frames = dec.feed(bytes([0x90, 60, 100, 62, 110]), 1.0)
        assert len(frames) == 2
        assert frames[0].decoded["message"] == "NoteOn ch=1 note=60(C4) vel=100"
        assert frames[1].decoded["message"] == "NoteOn ch=1 note=62(D4) vel=110"

    def test_running_status_cc(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xB0, 74, 64, 75, 32]), 1.0)
        assert len(frames) == 2
        assert frames[0].decoded["message"] == "CC ch=1 cc=74 val=64"
        assert frames[1].decoded["message"] == "CC ch=1 cc=75 val=32"

    def test_running_status_program_change(self):
        """Program change is 1 data byte — running status still works."""
        dec = MidiDecoder()
        frames = dec.feed(bytes([0xC0, 5, 10]), 1.0)
        assert len(frames) == 2
        assert frames[0].decoded["message"] == "PgmChg ch=1 pgm=5"
        assert frames[1].decoded["message"] == "PgmChg ch=1 pgm=10"

    def test_running_status_across_feeds(self):
        """Running status persists across feed() calls."""
        dec = MidiDecoder()
        frames = dec.feed(bytes([0x90, 60, 100]), 1.0)
        assert len(frames) == 1

        # Next feed has no status byte — uses running status
        frames = dec.feed(bytes([62, 110]), 2.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "NoteOn ch=1 note=62(D4) vel=110"

    def test_new_status_clears_running_status(self):
        dec = MidiDecoder()
        dec.feed(bytes([0x90, 60, 100]), 1.0)

        # Different status byte
        frames = dec.feed(bytes([0xB0, 74, 64]), 2.0)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "CC ch=1 cc=74 val=64"

    def test_sysex_clears_running_status(self):
        dec = MidiDecoder()
        dec.feed(bytes([0x90, 60, 100]), 1.0)

        # SysEx clears running status
        dec.feed(bytes([0xF0, 0x01, 0xF7]), 2.0)

        # Data bytes without status should be ignored
        frames = dec.feed(bytes([62, 110]), 3.0)
        assert len(frames) == 0


class TestPartialMessages:
    def test_split_note_on(self):
        """Note On bytes arriving one at a time."""
        dec = MidiDecoder()
        assert dec.feed(bytes([0x90]), 1.0) == []
        assert dec.feed(bytes([60]), 1.1) == []
        frames = dec.feed(bytes([127]), 1.2)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "NoteOn ch=1 note=60(C4) vel=127"

    def test_split_cc(self):
        dec = MidiDecoder()
        assert dec.feed(bytes([0xB0]), 1.0) == []
        assert dec.feed(bytes([74]), 1.1) == []
        frames = dec.feed(bytes([127]), 1.2)
        assert len(frames) == 1
        assert frames[0].decoded["message"] == "CC ch=1 cc=74 val=127"


class TestEdgeCases:
    def test_empty_input(self):
        dec = MidiDecoder()
        assert dec.feed(b"", 1.0) == []

    def test_orphan_data_bytes(self):
        """Data bytes without a preceding status byte are ignored."""
        dec = MidiDecoder()
        frames = dec.feed(bytes([60, 127]), 1.0)
        assert len(frames) == 0

    def test_reset(self):
        dec = MidiDecoder()
        dec.feed(bytes([0x90, 60]), 1.0)  # Partial message
        dec.reset()
        # After reset, data bytes should be orphaned
        frames = dec.feed(bytes([127]), 2.0)
        assert len(frames) == 0

    def test_reset_clears_sysex(self):
        dec = MidiDecoder()
        dec.feed(bytes([0xF0, 0x01]), 1.0)  # Partial SysEx
        dec.reset()
        # F7 after reset should not produce a frame
        frames = dec.feed(bytes([0xF7]), 2.0)
        assert len(frames) == 0

    def test_frame_raw_data(self):
        """Verify the raw data field contains the full MIDI message bytes."""
        dec = MidiDecoder()
        frames = dec.feed(bytes([0x90, 60, 127]), 1.0)
        assert frames[0].data == bytes([0x90, 60, 127])

    def test_timestamp_preserved(self):
        dec = MidiDecoder()
        frames = dec.feed(bytes([0x90, 60, 127]), 42.5)
        assert frames[0].timestamp == 42.5

    def test_multiple_messages_in_one_feed(self):
        """Multiple complete messages in a single feed call."""
        dec = MidiDecoder()
        frames = dec.feed(
            bytes([
                0x90, 60, 100,    # Note On C4
                0x80, 60, 0,      # Note Off C4
                0xB0, 74, 64,     # CC 74
                0xC0, 5,          # Program Change
                0xF8,             # Clock
            ]),
            1.0,
        )
        assert len(frames) == 5
        assert frames[0].decoded["message"] == "NoteOn ch=1 note=60(C4) vel=100"
        assert frames[1].decoded["message"] == "NoteOff ch=1 note=60(C4) vel=0"
        assert frames[2].decoded["message"] == "CC ch=1 cc=74 val=64"
        assert frames[3].decoded["message"] == "PgmChg ch=1 pgm=5"
        assert frames[4].decoded["message"] == "Clock"

    def test_system_common_clears_running_status(self):
        """System common messages (F1-F6) clear running status."""
        dec = MidiDecoder()
        dec.feed(bytes([0x90, 60, 100]), 1.0)

        # Tune Request (0xF6) — system common, clears running status
        dec.feed(bytes([0xF6]), 2.0)

        # Data bytes should now be orphaned
        frames = dec.feed(bytes([62, 110]), 3.0)
        assert len(frames) == 0


class TestRegistration:
    def test_registered_in_default_registry(self):
        from sbl_probe.decoders import registry
        assert "midi" in registry.list()

    def test_create_from_registry(self):
        from sbl_probe.decoders import registry
        dec = registry.create("midi")
        assert dec.name == "midi"

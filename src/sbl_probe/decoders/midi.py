"""MIDI decoder — parses raw MIDI byte streams into human-readable messages."""

from __future__ import annotations

from sbl_probe.decoders.base import Frame

# Note names within an octave
_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(note: int) -> str:
    """Convert MIDI note number to name. 60 = C4, 69 = A4."""
    octave = (note // 12) - 1
    return f"{_NOTE_NAMES[note % 12]}{octave}"


# Channel message types: status high nibble -> (name, data_byte_count)
_CHANNEL_MESSAGES: dict[int, tuple[str, int]] = {
    0x80: ("NoteOff", 2),
    0x90: ("NoteOn", 2),
    0xA0: ("PolyPres", 2),
    0xB0: ("CC", 2),
    0xC0: ("PgmChg", 1),
    0xD0: ("ChanPres", 1),
    0xE0: ("PitchBend", 2),
}

# System real-time messages (single byte, no data)
_REALTIME: dict[int, str] = {
    0xF8: "Clock",
    0xFA: "Start",
    0xFB: "Continue",
    0xFC: "Stop",
    0xFE: "ActiveSensing",
    0xFF: "Reset",
}


def _format_channel_message(msg_type: int, channel: int, data: list[int]) -> str:
    """Format a channel message into a human-readable string."""
    type_info = _CHANNEL_MESSAGES[msg_type]
    name = type_info[0]
    ch = f"ch={channel + 1}"

    if msg_type == 0x80:  # Note Off
        return f"{name} {ch} note={data[0]}({note_name(data[0])}) vel={data[1]}"
    elif msg_type == 0x90:  # Note On
        return f"{name} {ch} note={data[0]}({note_name(data[0])}) vel={data[1]}"
    elif msg_type == 0xA0:  # Poly Pressure
        return f"{name} {ch} note={data[0]} val={data[1]}"
    elif msg_type == 0xB0:  # CC
        return f"{name} {ch} cc={data[0]} val={data[1]}"
    elif msg_type == 0xC0:  # Program Change
        return f"{name} {ch} pgm={data[0]}"
    elif msg_type == 0xD0:  # Channel Pressure
        return f"{name} {ch} val={data[0]}"
    elif msg_type == 0xE0:  # Pitch Bend
        val = data[0] | (data[1] << 7)
        return f"{name} {ch} val={val}"

    return f"Unknown {ch}"  # pragma: no cover


class MidiDecoder:
    """Stateful MIDI byte stream decoder.

    Parses raw MIDI bytes into human-readable messages. Handles running
    status (repeated status byte omission) and system real-time messages
    interleaved within channel messages.
    """

    def __init__(self) -> None:
        self._running_status: int = 0  # Last channel status byte
        self._data_buffer: list[int] = []
        self._expected_data: int = 0
        self._in_sysex: bool = False
        self._sysex_buffer: bytearray = bytearray()

    @property
    def name(self) -> str:
        return "midi"

    def feed(self, data: bytes, timestamp: float) -> list[Frame]:
        if not data:
            return []

        frames: list[Frame] = []

        for byte in data:
            frame = self._process_byte(byte, timestamp)
            if frame is not None:
                frames.append(frame)

        return frames

    def _process_byte(self, byte: int, timestamp: float) -> Frame | None:
        # System real-time: pass through immediately, don't disturb state
        if byte >= 0xF8:
            label = _REALTIME.get(byte)
            if label is not None:
                return self._make_frame(label, bytes([byte]), timestamp)
            # Undefined real-time bytes (0xF9, 0xFD) — ignore
            return None

        # Status byte (high bit set, not real-time)
        if byte & 0x80:
            # SysEx start
            if byte == 0xF0:
                self._in_sysex = True
                self._sysex_buffer = bytearray([0xF0])
                # Clear running status — SysEx cancels it
                self._running_status = 0
                self._data_buffer.clear()
                self._expected_data = 0
                return None

            # SysEx end
            if byte == 0xF7:
                if self._in_sysex:
                    self._sysex_buffer.append(0xF7)
                    payload = bytes(self._sysex_buffer)
                    self._in_sysex = False
                    self._sysex_buffer.clear()
                    return self._make_frame(
                        f"SysEx [{len(payload)} bytes]", payload, timestamp
                    )
                # Stray F7 — ignore
                return None

            # Any other status byte terminates SysEx
            if self._in_sysex:
                payload = bytes(self._sysex_buffer)
                self._in_sysex = False
                self._sysex_buffer.clear()
                # Don't emit — SysEx was terminated abnormally (non-F7 status)
                # Fall through to process this status byte

            # System common (0xF1-0xF6) — we don't fully parse these, just reset
            if 0xF1 <= byte <= 0xF6:
                self._running_status = 0
                self._data_buffer.clear()
                self._expected_data = 0
                return None

            # Channel message status byte
            msg_type = byte & 0xF0
            if msg_type in _CHANNEL_MESSAGES:
                self._running_status = byte
                self._data_buffer.clear()
                self._expected_data = _CHANNEL_MESSAGES[msg_type][1]
                return None

            return None  # pragma: no cover

        # Data byte (high bit clear)
        if self._in_sysex:
            self._sysex_buffer.append(byte)
            return None

        # No running status — orphan data byte
        if self._running_status == 0:
            return None

        # Accumulate data byte
        self._data_buffer.append(byte)

        # Check if message is complete
        if len(self._data_buffer) >= self._expected_data:
            msg_type = self._running_status & 0xF0
            channel = self._running_status & 0x0F
            data = list(self._data_buffer)
            raw = bytes([self._running_status] + data)

            self._data_buffer.clear()

            label = _format_channel_message(msg_type, channel, data)
            return self._make_frame(label, raw, timestamp)

        return None

    def _make_frame(self, decoded_text: str, raw_data: bytes, timestamp: float) -> Frame:
        return Frame(
            timestamp=timestamp,
            protocol="midi",
            direction="rx",
            data=raw_data,
            decoded={"message": decoded_text},
        )

    def reset(self) -> None:
        self._running_status = 0
        self._data_buffer.clear()
        self._expected_data = 0
        self._in_sysex = False
        self._sysex_buffer.clear()

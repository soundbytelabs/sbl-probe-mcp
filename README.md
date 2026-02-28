<!-- mcp-name: io.github.soundbytelabs/probe -->

# sbl-probe

Serial communication and protocol analysis MCP server. Gives AI coding assistants direct access to serial ports for reading, writing, decoding, and capturing embedded device output — no more copy-pasting from picocom.

Part of the [Sound Byte Labs](https://github.com/soundbytelabs) embedded tooling suite, alongside [sbl-debugger](https://github.com/soundbytelabs/sbl-debugger-mcp) for hardware debugging.

## Quick Start

```bash
# Install (editable, into SBL venv)
pip install -e .

# Or with test dependencies
pip install -e ".[dev]"
```

Register in `.mcp.json` at your workspace root:

```json
{
  "mcpServers": {
    "sbl-probe": {
      "type": "stdio",
      "command": "/path/to/venv/bin/python",
      "args": ["-m", "sbl_probe"]
    }
  }
}
```

Restart your MCP client and the tools are available immediately.

## Tools

### Connection Management

| Tool | Description |
|------|-------------|
| `list_ports` | List available serial ports with USB metadata and by-id paths |
| `open` | Open a serial connection (port, baud, optional name) |
| `close` | Close a named connection |
| `connections` | List active connections with stats |

### Data I/O

| Tool | Description |
|------|-------------|
| `read` | Read decoded frames using the active decoder (line-oriented by default) |
| `read_raw` | Read raw bytes in utf8, hex, or base64 |
| `write` | Write data to a connection |

### Protocol Analysis

| Tool | Description |
|------|-------------|
| `set_decoder` | Change the active decoder on a connection |
| `decode_buffer` | Run a decoder over a raw data buffer |
| `list_decoders` | List available decoder names |
| `probe_baud` | Auto-detect baud rate by scoring printable text across common rates |

### Capture & Replay

| Tool | Description |
|------|-------------|
| `capture_start` | Start background capture into a ring buffer |
| `capture_stop` | Stop capture, return summary stats |
| `capture_read` | Query captured frames (filter by regex, time range, last N) |
| `capture_save` | Save capture buffer to a JSON Lines file |
| `capture_load` | Load a previously saved capture |

## Architecture

```
sbl_probe/
├── server.py          # FastMCP server, tool wiring
├── transport/
│   ├── base.py        # Transport protocol (structural typing)
│   ├── serial.py      # pyserial wrapper
│   └── manager.py     # Named connection registry
├── decoders/
│   ├── base.py        # Frame dataclass + Decoder protocol
│   └── raw.py         # Line-oriented decoder
├── capture/
│   ├── buffer.py      # Thread-safe ring buffer with query support
│   ├── engine.py      # Background reader thread
│   └── storage.py     # JSON Lines save/load
└── tools/
    ├── connection.py   # list_ports, open, close, connections
    ├── data.py         # read, read_raw, write
    ├── protocol.py     # set_decoder, decode_buffer, list_decoders
    ├── capture.py      # capture_start/stop/read/save/load
    └── diagnostics.py  # probe_baud
```

Key design decisions:

- **Threaded pyserial** with `asyncio.to_thread()` — keeps the MCP event loop responsive without the complexity of `pyserial-asyncio`
- **Pluggable decoders** — register new decoders by name, swap at runtime via `set_decoder`
- **Background capture** — daemon thread feeds decoded frames into a ring buffer; query with regex, time range, or tail the last N frames
- **Error dicts, not exceptions** — tools return `{"error": "..."}` instead of crashing the server

## Adding a Custom Decoder

```python
from sbl_probe.decoders.base import Frame, Decoder
from sbl_probe.decoders import registry

class MyDecoder:
    @property
    def name(self) -> str:
        return "my_proto"

    def feed(self, data: bytes, timestamp: float) -> list[Frame]:
        # Parse data, return frames
        ...

    def reset(self) -> None:
        ...

registry.register("my_proto", MyDecoder)
```

## Running Tests

```bash
pytest                    # 92 tests
pytest -v                 # verbose
pytest tests/test_capture.py  # just capture tests
```

## Dependencies

- `mcp` — Official Python MCP SDK (FastMCP)
- `pyserial` — Serial port access
- Python >= 3.11

"""Protocol tools: set_decoder, decode_buffer, list_decoders."""

from __future__ import annotations

import time

from sbl_probe.decoders import registry as decoder_registry
from sbl_probe.transport.manager import ConnectionManager


def register_tools(mcp, manager: ConnectionManager) -> None:
    """Register protocol analysis tools with the MCP server."""

    @mcp.tool()
    def set_decoder(name: str, decoder: str) -> dict:
        """Change the active decoder on a connection.

        Args:
            name: Connection name.
            decoder: Decoder name (e.g., "raw"). Use list_decoders to see available options.
        """
        try:
            new_decoder = manager.set_decoder(name, decoder)
            return {
                "status": "ok",
                "connection": name,
                "decoder": new_decoder.name,
            }
        except ValueError as e:
            return {"error": str(e)}

    @mcp.tool()
    def decode_buffer(data: str, decoder: str = "raw", encoding: str = "utf8") -> dict:
        """Run a decoder over a raw data buffer and return frames.

        Useful for re-decoding previously captured data with a different decoder.

        Args:
            data: The data to decode.
            decoder: Decoder name to use. Default: "raw".
            encoding: Input encoding — utf8, hex, or base64. Default: utf8.
        """
        import base64

        try:
            if encoding == "utf8":
                raw = data.encode("utf-8")
            elif encoding == "hex":
                raw = bytes.fromhex(data)
            elif encoding == "base64":
                raw = base64.b64decode(data)
            else:
                return {"error": f"Unknown encoding: {encoding}"}

            dec = decoder_registry.create(decoder)
            frames = dec.feed(raw, time.monotonic())

            # Flush any remaining buffered data
            if hasattr(dec, "flush"):
                frames.extend(dec.flush())

            return {
                "frames": [f.to_dict() for f in frames],
                "count": len(frames),
                "decoder": decoder,
            }
        except ValueError as e:
            return {"error": str(e)}

    @mcp.tool()
    def list_decoders() -> list[str]:
        """List available decoder names."""
        return decoder_registry.list()

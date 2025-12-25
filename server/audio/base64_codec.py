from __future__ import annotations

import base64


class Base64AudioCodec:
    """Base64 encode/decode helpers for audio payloads."""

    @staticmethod
    def encode(data: bytes) -> str:
        """Encode raw bytes to base64 string (standard alphabet, padded)."""
        return base64.b64encode(data).decode("ascii")

    @staticmethod
    def decode(b64: str) -> bytes:
        """Decode base64 string into raw bytes. Raises ValueError on invalid input."""
        return base64.b64decode(b64, validate=True)

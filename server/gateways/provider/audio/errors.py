from __future__ import annotations


class AudioDecodingError(Exception):
    """Raised when base64 audio cannot be decoded."""


class AudioTranscodingError(Exception):
    """Raised when audio cannot be transcoded to the target format."""

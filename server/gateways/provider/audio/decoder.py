from __future__ import annotations

from ....audio import Base64AudioCodec
from .errors import AudioDecodingError


class AudioDeltaDecoder:
    """Decode base64-encoded audio payloads."""

    def decode(self, audio_b64: str) -> bytes:
        try:
            return Base64AudioCodec.decode(audio_b64)
        except ValueError as exc:
            raise AudioDecodingError(str(exc)) from exc

from __future__ import annotations

from ..audio import AudioChunk, AudioFormat, Base64AudioCodec


class AudioDurationCalculator:
    """Calculates audio duration for 16kHz mono 16-bit PCM audio."""

    PCM16_MONO_16K = AudioFormat(sample_rate_hz=16_000, channels=1, sample_format="pcm16")

    @classmethod
    def calculate_duration_ms(cls, audio_b64: str) -> float:
        """
        Calculate duration in milliseconds from base64-encoded audio.

        Args:
            audio_b64: Base64-encoded audio data (16kHz mono 16-bit PCM)

        Returns:
            Duration in milliseconds
        """
        # Decode base64 to get raw byte length
        audio_bytes = Base64AudioCodec.decode(audio_b64)
        return cls.calculate_duration_ms_from_bytes(audio_bytes)

    @classmethod
    def calculate_duration_ms_from_bytes(cls, audio_bytes: bytes) -> float:
        """
        Calculate duration in milliseconds from raw PCM audio bytes.
        """
        chunk = AudioChunk(pcm=audio_bytes, fmt=cls.PCM16_MONO_16K)
        return float(chunk.duration_ms())

from __future__ import annotations

import base64


class AudioDurationCalculator:
    """Calculates audio duration for 16kHz mono 16-bit PCM audio."""

    # Hardcoded audio format constants
    SAMPLE_RATE_HZ = 16_000
    CHANNELS = 1
    BYTES_PER_SAMPLE = 2  # 16-bit = 2 bytes

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
        audio_bytes = base64.b64decode(audio_b64, validate=True)
        num_bytes = len(audio_bytes)

        # Calculate number of samples: total_bytes / bytes_per_sample / channels
        num_samples = num_bytes / (cls.BYTES_PER_SAMPLE * cls.CHANNELS)

        # Duration (ms) = (samples / sample_rate) * 1000
        duration_ms = (num_samples / cls.SAMPLE_RATE_HZ) * 1000
        return duration_ms

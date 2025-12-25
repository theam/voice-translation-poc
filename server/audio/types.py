from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

SampleFormat = Literal["pcm16"]


class UnsupportedAudioFormatError(ValueError):
    """Raised when audio is not in a supported format (expected PCM16)."""


@dataclass(frozen=True)
class AudioFormat:
    """Describes raw PCM audio."""

    sample_rate_hz: int
    channels: int
    sample_format: SampleFormat

    def bytes_per_sample(self) -> int:
        """Return bytes per sample (PCM16 = 2)."""
        if self.sample_format != "pcm16":
            raise UnsupportedAudioFormatError(f"Unsupported audio sample format: {self.sample_format}")
        return 2

    def bytes_per_frame(self) -> int:
        """Return bytes per frame = bytes_per_sample * channels."""
        return self.bytes_per_sample() * self.channels


@dataclass
class AudioChunk:
    """A piece of PCM audio with optional timing metadata."""

    pcm: bytes
    fmt: AudioFormat
    timestamp_ms: Optional[int] = None
    sequence: Optional[int] = None

    def duration_ms(self) -> int:
        """Duration in milliseconds based on pcm length and format."""
        if not self.pcm:
            return 0
        frame_bytes = self.fmt.bytes_per_frame()
        total_frames = len(self.pcm) // frame_bytes
        return int((total_frames / self.fmt.sample_rate_hz) * 1000)

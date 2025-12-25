from __future__ import annotations

import audioop


class StreamingPcmResampler:
    """Stateful PCM16 resampler built on audioop.ratecv."""

    def __init__(self, src_rate_hz: int, dst_rate_hz: int, channels: int, sample_width: int = 2) -> None:
        self.src_rate_hz = src_rate_hz
        self.dst_rate_hz = dst_rate_hz
        self.channels = channels
        self.sample_width = sample_width
        self._state = None

    def process(self, pcm_bytes: bytes) -> bytes:
        """Resample a chunk of PCM bytes while preserving boundary state."""
        frame_bytes = self.sample_width * self.channels
        trimmed = pcm_bytes[: len(pcm_bytes) - (len(pcm_bytes) % frame_bytes)]
        if not trimmed:
            return b""

        out, self._state = audioop.ratecv(
            trimmed,
            self.sample_width,
            self.channels,
            self.src_rate_hz,
            self.dst_rate_hz,
            self._state,
        )
        return out

    def reset(self) -> None:
        """Reset internal resampling state."""
        self._state = None

    def flush(self) -> bytes:
        """Flush pending state (ratecv does not require explicit flush)."""
        return b""

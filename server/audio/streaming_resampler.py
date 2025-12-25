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
        self._pending = bytearray()

    def process(self, pcm_bytes: bytes) -> bytes:
        """Resample a chunk of PCM bytes while preserving boundary state."""
        if not pcm_bytes:
            return b""

        self._pending.extend(pcm_bytes)

        frame_bytes = self.sample_width * self.channels
        usable = len(self._pending) - (len(self._pending) % frame_bytes)
        if usable <= 0:
            return b""

        chunk = bytes(self._pending[:usable])
        del self._pending[:usable]

        out, self._state = audioop.ratecv(
            chunk,
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
        self._pending.clear()

    def flush(self) -> bytes:
        """Flush pending state (ratecv does not require explicit flush)."""
        if not self._pending:
            return b""

        frame_bytes = self.sample_width * self.channels
        remainder = len(self._pending) % frame_bytes
        if remainder:
            pad_len = frame_bytes - remainder
            self._pending.extend(b"\x00" * pad_len)

        chunk = bytes(self._pending)
        self._pending.clear()

        out, self._state = audioop.ratecv(
            chunk,
            self.sample_width,
            self.channels,
            self.src_rate_hz,
            self.dst_rate_hz,
            self._state,
        )
        return out

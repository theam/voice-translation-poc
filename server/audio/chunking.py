from __future__ import annotations

from dataclasses import dataclass

from .types import AudioFormat


@dataclass
class AudioChunker:
    """Chunking utilities for PCM streaming."""

    def trim_to_frame_boundary(self, pcm: bytes, fmt: AudioFormat) -> bytes:
        """Trim trailing bytes so len(pcm) is a multiple of fmt.bytes_per_frame()."""
        frame_bytes = fmt.bytes_per_frame()
        remainder = len(pcm) % frame_bytes
        if remainder == 0:
            return pcm
        return pcm[: len(pcm) - remainder]

    def split_by_ms(self, pcm: bytes, fmt: AudioFormat, chunk_ms: int) -> list[bytes]:
        """
        Split PCM into chunks of chunk_ms duration.
        - Always frame-aligned
        - Last chunk may be shorter (but still frame-aligned)
        """
        if chunk_ms <= 0:
            return []

        trimmed = self.trim_to_frame_boundary(pcm, fmt)
        chunk_size = self.bytes_for_ms(fmt, chunk_ms)
        if chunk_size <= 0:
            return [trimmed] if trimmed else []

        return [trimmed[i:i + chunk_size] for i in range(0, len(trimmed), chunk_size)]

    def join(self, chunks: list[bytes]) -> bytes:
        """Concatenate chunks."""
        return b"".join(chunks)

    def bytes_for_ms(self, fmt: AudioFormat, ms: int) -> int:
        """Compute expected bytes for given ms (rounded down to frame boundary)."""
        if ms <= 0:
            return 0
        frames = int(fmt.sample_rate_hz * ms / 1000)
        return frames * fmt.bytes_per_frame()

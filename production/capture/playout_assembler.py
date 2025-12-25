"""Audio playout timeline assembler.

Produces deterministic playout timestamps from jittery arrival times. This keeps
audio aligned regardless of the source system's chunk size or timestamping.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass
class _StreamPlayoutState:
    base_offset_ms: float
    cursor_ms: float = 0.0


class PlayoutAssembler:
    """Compute stable playout offsets for inbound audio streams."""

    def __init__(self, *, sample_rate: int, channels: int = 1, initial_buffer_ms: int = 80) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if channels <= 0:
            raise ValueError("channels must be positive")

        self.sample_rate = sample_rate
        self.channels = channels
        self.initial_buffer_ms = initial_buffer_ms
        self._streams: Dict[str, _StreamPlayoutState] = {}

    def add_chunk(self, stream_key: str, arrival_ms: float, pcm_bytes: bytes) -> Tuple[float, float]:
        """Add a PCM chunk and return its playout position and duration.

        Args:
            stream_key: Identifier for the logical stream (e.g., participant).
            arrival_ms: Arrival timestamp (relative to scenario start).
            pcm_bytes: Raw 16-bit PCM payload.

        Returns:
            Tuple of (start_ms, duration_ms) for the chunk on the playout timeline.
        """
        if not pcm_bytes:
            return self._get_or_create_state(stream_key, arrival_ms).base_offset_ms, 0.0

        state = self._get_or_create_state(stream_key, arrival_ms)
        duration_ms = len(pcm_bytes) / (self.sample_rate * self.channels * 2) * 1000.0
        start_ms = state.base_offset_ms + state.cursor_ms
        state.cursor_ms += duration_ms
        return start_ms, duration_ms

    def _get_or_create_state(self, stream_key: str, arrival_ms: float) -> _StreamPlayoutState:
        if stream_key not in self._streams:
            base_offset_ms = arrival_ms + self.initial_buffer_ms
            self._streams[stream_key] = _StreamPlayoutState(base_offset_ms=base_offset_ms)
        return self._streams[stream_key]


__all__ = ["PlayoutAssembler"]

"""Audio playout timeline assembler.

Produces deterministic playout timestamps from jittery arrival times. This keeps
audio aligned regardless of the source system's chunk size or timestamping.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Dict, Tuple


@dataclass
class _StreamPlayoutState:
    next_playout_ms: float | None = None


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
        self._logger = logging.getLogger(__name__)

    def add_chunk(
        self,
        stream_key: str,
        *,
        arrival_ms: float,
        media_now_ms: float,
        pcm_bytes: bytes,
    ) -> Tuple[float, float]:
        """Add a PCM chunk and return its playout position and duration.

        Args:
            stream_key: Identifier for the logical stream (e.g., participant).
            arrival_ms: Arrival timestamp (relative to scenario start).
            media_now_ms: Current scenario media clock position.
            pcm_bytes: Raw 16-bit PCM payload.

        Returns:
            Tuple of (start_ms, duration_ms) for the chunk on the playout timeline.
        """
        state = self._get_or_create_state(stream_key)

        frame_bytes = self.channels * 2  # 16-bit PCM per channel
        trimmed_len = len(pcm_bytes) - (len(pcm_bytes) % frame_bytes)
        duration_ms = trimmed_len / (self.sample_rate * self.channels * 2) * 1000.0 if trimmed_len else 0.0

        guard_window_ms = max(self.initial_buffer_ms * 10.0, 1000.0)
        if state.next_playout_ms is not None and media_now_ms < state.next_playout_ms - guard_window_ms:
            self._logger.warning(
                "Media clock behind playout cursor; clamping media_now_ms",
                extra={
                    "stream_key": stream_key,
                    "media_now_ms": media_now_ms,
                    "next_playout_ms": state.next_playout_ms,
                    "guard_window_ms": guard_window_ms,
                },
            )
            media_now_ms = state.next_playout_ms

        earliest = media_now_ms + self.initial_buffer_ms
        start_ms = earliest if state.next_playout_ms is None else max(earliest, state.next_playout_ms)
        if start_ms < media_now_ms:
            clamped_start = media_now_ms + self.initial_buffer_ms
            self._logger.warning(
                "Computed playout before media clock; clamping",
                extra={
                    "stream_key": stream_key,
                    "arrival_ms": arrival_ms,
                    "media_now_ms": media_now_ms,
                    "requested_start_ms": start_ms,
                    "clamped_start_ms": clamped_start,
                },
            )
            start_ms = clamped_start
        state.next_playout_ms = start_ms + duration_ms
        return start_ms, duration_ms

    def _get_or_create_state(self, stream_key: str) -> _StreamPlayoutState:
        if stream_key not in self._streams:
            self._streams[stream_key] = _StreamPlayoutState()
        return self._streams[stream_key]


__all__ = ["PlayoutAssembler"]

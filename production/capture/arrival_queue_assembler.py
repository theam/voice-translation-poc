"""Arrival-gated audio playout assembler.

Keeps per-stream playheads that advance based on arrival time and chunk
duration. This prevents inbound audio from playing before it arrives and avoids
time-compression when services emit bursty chunks.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Dict, Tuple


logger = logging.getLogger(__name__)


@dataclass
class _StreamState:
    playhead_ms: float = 0.0


class ArrivalQueueAssembler:
    """Compute arrival-gated playout offsets for inbound audio streams."""

    def __init__(self, *, sample_rate: int, channels: int = 1) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if channels <= 0:
            raise ValueError("channels must be positive")

        self.sample_rate = sample_rate
        self.channels = channels
        self._streams: Dict[str, _StreamState] = {}

    def add_chunk(self, stream_key: str, *, arrival_ms: float, pcm_bytes: bytes) -> Tuple[float, float]:
        """Add a PCM chunk and return its playout position and duration.

        Args:
            stream_key: Identifier for the logical stream (e.g., participant).
            arrival_ms: Wall-clock arrival timestamp (relative to scenario start).
            pcm_bytes: Raw 16-bit PCM payload.

        Returns:
            Tuple of (start_ms, duration_ms) on the arrival-gated timeline.
        """
        state = self._streams.setdefault(stream_key, _StreamState())

        frame_bytes = self.channels * 2  # 16-bit PCM per channel
        trimmed_len = len(pcm_bytes) - (len(pcm_bytes) % frame_bytes)
        duration_ms = trimmed_len / (self.sample_rate * self.channels * 2) * 1000.0 if trimmed_len else 0.0

        start_ms = max(arrival_ms, state.playhead_ms)
        if duration_ms > 0:
            state.playhead_ms = start_ms + duration_ms

        logger.debug(
            "ArrivalQueueAssembler scheduled chunk",
            extra={
                "stream_key": stream_key,
                "arrival_ms": arrival_ms,
                "start_ms": start_ms,
                "duration_ms": duration_ms,
                "playhead_ms": state.playhead_ms,
            },
        )

        return start_ms, duration_ms


__all__ = ["ArrivalQueueAssembler"]

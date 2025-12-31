"""Centralize wall-clock to scenario-time mapping for inbound audio."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass
class _StreamState:
    """Anchor and playhead tracking for a single inbound stream."""

    anchor_wall_ms: float
    turn_start_ms: float
    playhead_ms: float


class TimebaseMapper:
    """Map inbound wall-clock arrivals onto the scenario media timeline."""

    def __init__(self, *, sample_rate: int, channels: int = 1) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if channels <= 0:
            raise ValueError("channels must be positive")

        self.sample_rate = sample_rate
        self.channels = channels
        self._streams: Dict[str, _StreamState] = {}

    def _duration_ms(self, pcm_bytes: bytes) -> float:
        frame_bytes = self.channels * 2  # 16-bit PCM per channel
        trimmed_len = len(pcm_bytes) - (len(pcm_bytes) % frame_bytes)
        return trimmed_len / (self.sample_rate * self.channels * 2) * 1000.0 if trimmed_len else 0.0

    def map_inbound_audio(
        self,
        *,
        turn_id: str,
        arrival_ms: float,
        turn_start_ms: float,
        pcm_bytes: bytes,
    ) -> Tuple[float, float]:
        """Return scenario-timeline start/duration for inbound PCM.

        Args:
            turn_id: Turn identifier that the audio belongs to.
            arrival_ms: Wall-clock arrival (relative to scenario start).
            turn_start_ms: Scenario start time of the turn.
            pcm_bytes: PCM payload.
        """
        duration_ms = self._duration_ms(pcm_bytes)
        state = self._streams.get(turn_id)

        # (Re)anchor on first chunk or when the turn changes.
        if state is None or state.turn_start_ms != turn_start_ms:
            state = _StreamState(
                anchor_wall_ms=arrival_ms,
                turn_start_ms=turn_start_ms,
                playhead_ms=turn_start_ms,
            )
            self._streams[turn_id] = state

        scenario_ts = state.turn_start_ms + (arrival_ms - state.anchor_wall_ms)
        start_ms = max(scenario_ts, state.playhead_ms)

        if duration_ms > 0:
            state.playhead_ms = start_ms + duration_ms

        return start_ms, duration_ms


__all__ = ["TimebaseMapper"]

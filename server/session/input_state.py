from __future__ import annotations

from collections import deque
from enum import Enum
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

if TYPE_CHECKING:
    from ...config import SystemConfig


class InputStatus(str, Enum):
    SILENCE = "silence"
    SPEAKING = "speaking"

    def is_silence(self) -> bool:
        return self == InputStatus.SILENCE

    def is_speaking(self) -> bool:
        return self == InputStatus.SPEAKING


class InputState:
    """
    Production-grade speaking/silence state machine (fast, allocation-light).

    Call `update(now_ms, rms)` once per audio frame/chunk.

    Features:
      - EMA smoothing on RMS (reduces breath/spike sensitivity)
      - Schmitt trigger thresholds: voice_on_rms / voice_off_rms (prevents flip-flops)
      - Voting window (requires consistent energy before entering SPEAKING)
      - Time hysteresis on entry + silence timeout on exit
      - Minimum state hold time (optional, prevents rapid oscillation)
    """

    def __init__(self, config: SystemConfig) -> None:
        # Timing
        self.voice_hysteresis_ms = config.voice_hysteresis_ms
        self.silence_timeout_ms = config.silence_timeout_ms
        self.frame_ms = config.frame_ms
        self.min_state_hold_ms = config.min_state_hold_ms

        # RMS thresholds (Schmitt trigger)
        self.voice_on_rms = config.voice_on_rms
        self.voice_off_rms = config.voice_off_rms

        # EMA smoothing
        # Smaller alpha = smoother but slower response
        self.rms_ema_alpha = config.rms_ema_alpha

        # Voting window
        vote_window_ms = config.vote_window_ms
        self._vote_window_frames: int = max(1, vote_window_ms // max(1, self.frame_ms))
        self.vote_required_ratio = config.vote_required_ratio
        self._votes: deque[bool] = deque(maxlen=self._vote_window_frames)

        # Observable state
        self.status: InputStatus = InputStatus.SILENCE
        self.voice_detected_from_ms: Optional[int] = None
        self.voice_detected_last_ms: int = 0
        self._last_transition_ms: int = 0

        # Internal smoothing state
        self._rms_ema: Optional[float] = None

        # Listeners
        self._listeners: list[Callable[[InputState], Awaitable[None]]] = []

    def add_listener(self, listener: Callable[[InputState], Awaitable[None]]) -> None:
        self._listeners.append(listener)

    async def _notify_listeners(self) -> None:
        # Hot path is update(); notifications are rare (only on transitions).
        for listener in list(self._listeners):
            await listener(self)

    def _in_holdoff(self, now_ms: int) -> bool:
        return (now_ms - self._last_transition_ms) < self.min_state_hold_ms

    def _smooth(self, rms: float) -> float:
        if self._rms_ema is None:
            self._rms_ema = float(rms)
        else:
            a = self.rms_ema_alpha
            self._rms_ema = (a * float(rms)) + ((1.0 - a) * self._rms_ema)
        return self._rms_ema

    def _vote_ratio(self) -> float:
        if not self._votes:
            return 0.0
        # bools sum as ints in python
        return (sum(self._votes) / len(self._votes))

    async def update(self, now_ms: int, rms: float) -> bool:
        """
        Update state using the latest RMS value.
        Returns True if a SILENCE<->SPEAKING transition occurred.
        """
        smoothed = self._smooth(rms)

        # Determine "voice-like" for this frame depending on current state (Schmitt trigger)
        if self.status.is_silence():
            is_voice_frame = smoothed >= self.voice_on_rms
        else:
            # While speaking, tolerate lower energy without immediately calling it silence
            is_voice_frame = smoothed >= self.voice_off_rms

        self._votes.append(is_voice_frame)

        # --- SILENCE -> SPEAKING ---
        if self.status.is_silence():
            if is_voice_frame:
                if self.voice_detected_from_ms is None:
                    self.voice_detected_from_ms = now_ms

                # Require sustained time + enough votes in recent window
                elapsed = now_ms - self.voice_detected_from_ms
                if elapsed >= self.voice_hysteresis_ms:
                    if not self._in_holdoff(now_ms) and self._vote_ratio() >= self.vote_required_ratio:
                        self.status = InputStatus.SPEAKING
                        self.voice_detected_last_ms = now_ms
                        self._last_transition_ms = now_ms
                        await self._notify_listeners()
                        return True
            else:
                # Drop back below threshold: reset start marker (prevents breath spikes from accumulating time)
                self.voice_detected_from_ms = None

            return False

        # --- SPEAKING state maintenance ---
        if is_voice_frame:
            self.voice_detected_last_ms = now_ms
            return False

        # Not voice-like: only transition after sustained quiet duration
        if self.voice_detected_last_ms and not self._in_holdoff(now_ms):
            if (now_ms - self.voice_detected_last_ms) > self.silence_timeout_ms:
                self.status = InputStatus.SILENCE
                self.voice_detected_from_ms = None
                self._last_transition_ms = now_ms
                self._votes.clear()
                await self._notify_listeners()
                return True

        return False

    @property
    def is_speaking(self) -> bool:
        return self.status.is_speaking()


__all__ = ["InputState", "InputStatus"]

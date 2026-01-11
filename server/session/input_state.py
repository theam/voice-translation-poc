from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

if TYPE_CHECKING:
    from ...config import SystemConfig


class InputStatus(str, Enum):
    SILENCE = "silence"
    SPEAKING = "speaking"

    def is_silence(self) -> bool:
        """Check if this status is SILENCE."""
        return self == InputStatus.SILENCE

    def is_speaking(self) -> bool:
        """Check if this status is SPEAKING."""
        return self == InputStatus.SPEAKING


class InputState:
    """Tracks whether inbound audio recently contains speech.

    Observable state machine that notifies listeners on state transitions.
    """

    def __init__(self, config: SystemConfig) -> None:
        # Timing configuration
        self.voice_hysteresis_ms = config.voice_hysteresis_ms
        self.silence_timeout_ms = config.silence_timeout_ms

        # State
        self.status: InputStatus = InputStatus.SILENCE
        self.voice_detected_from_ms: Optional[int] = None
        self.voice_detected_last_ms: int = 0
        self._listeners: list[Callable[[InputState], Awaitable[None]]] = []

    def add_listener(self, listener: Callable[[InputState], Awaitable[None]]) -> None:
        """Register a listener to be notified on state transitions."""
        self._listeners.append(listener)

    async def _notify_listeners(self) -> None:
        """Notify all listeners of state change."""
        for listener in list(self._listeners):
            await listener(self)

    async def on_voice_detected(self, now_ms: int) -> bool:
        """Update state when voice is detected. Returns True if state transitioned."""
        if self.status.is_silence():
            # First voice detection in this segment
            if self.voice_detected_from_ms is None:
                self.voice_detected_from_ms = now_ms

            # Check hysteresis - need sustained voice before transitioning
            elapsed = now_ms - self.voice_detected_from_ms
            if elapsed < self.voice_hysteresis_ms:
                return False

            # Transition to SPEAKING
            self.status = InputStatus.SPEAKING
            self.voice_detected_last_ms = now_ms
            await self._notify_listeners()
            return True

        # Already speaking - just update last voice timestamp
        self.voice_detected_last_ms = now_ms
        return False

    async def on_silence_detected(self, now_ms: int) -> bool:
        """Update state when silence is detected. Returns True if state transitioned."""
        if self.status.is_speaking() and self.voice_detected_last_ms:
            if (now_ms - self.voice_detected_last_ms) > self.silence_timeout_ms:
                self.status = InputStatus.SILENCE
                self.voice_detected_from_ms = None
                await self._notify_listeners()
                return True
        return False

    @property
    def is_speaking(self) -> bool:
        return self.status.is_speaking()


__all__ = ["InputState", "InputStatus"]

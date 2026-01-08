from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class InputStatus(str, Enum):
    SILENCE = "silence"
    SPEAKING = "speaking"


@dataclass
class InputState:
    """Tracks whether inbound audio recently contains speech."""

    status: InputStatus = InputStatus.SILENCE
    voice_detected_from_ms: Optional[int] = None
    voice_detected_last_ms: int = 0

    def on_voice_detected(self, now_ms: int, hysteresis_ms: int = 0) -> bool:
        if self.status == InputStatus.SILENCE:
            # First voice detection in this segment
            if self.voice_detected_from_ms is None:
                self.voice_detected_from_ms = now_ms

            # Check hysteresis - need sustained voice before transitioning
            elapsed = now_ms - self.voice_detected_from_ms
            if elapsed < hysteresis_ms:
                return False

            # Transition to SPEAKING
            self.status = InputStatus.SPEAKING
            self.voice_detected_last_ms = now_ms
            return True

        # Already speaking - just update last voice timestamp
        self.voice_detected_last_ms = now_ms
        return False

    def on_silence_detected(self, now_ms: int, silence_threshold: int) -> bool:
        if self.status == InputStatus.SPEAKING and self.voice_detected_last_ms:
            if (now_ms - self.voice_detected_last_ms) > silence_threshold:
                self.status = InputStatus.SILENCE
                self.voice_detected_from_ms = None
                return True
        return False

    @property
    def is_speaking(self) -> bool:
        return self.status == InputStatus.SPEAKING


__all__ = ["InputState", "InputStatus"]

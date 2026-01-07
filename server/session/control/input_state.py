from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InputStatus(str, Enum):
    SILENCE = "silence"
    SPEAKING = "speaking"


@dataclass
class InputState:
    """Tracks whether inbound audio recently contains speech."""

    status: InputStatus = InputStatus.SILENCE
    last_voice_ms: int = 0

    def on_voice_detected(self, now_ms: int) -> None:
        self.status = InputStatus.SPEAKING
        self.last_voice_ms = now_ms

    def maybe_timeout_silence(self, now_ms: int, silence_timeout_ms: int) -> bool:
        if self.status == InputStatus.SPEAKING and self.last_voice_ms:
            if (now_ms - self.last_voice_ms) > silence_timeout_ms:
                self.status = InputStatus.SILENCE
                return True
        return False

    @property
    def is_speaking(self) -> bool:
        return self.status == InputStatus.SPEAKING


__all__ = ["InputState", "InputStatus"]

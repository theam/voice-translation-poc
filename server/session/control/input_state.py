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
    last_voice_ms: int = 0
    voice_detected_ms: Optional[int] = None

    def on_voice_detected(self, now_ms: int, hysteresis_ms: int = 0) -> None:
        if self.status == InputStatus.SILENCE and self.voice_detected_ms is None:
            self.voice_detected_ms = now_ms

        if self.status == InputStatus.SILENCE:
            base = self.voice_detected_ms if self.voice_detected_ms is not None else now_ms
            elapsed = now_ms - base
            if elapsed < hysteresis_ms:
                return

        self.status = InputStatus.SPEAKING
        self.last_voice_ms = now_ms
        self.voice_detected_ms = now_ms

    def on_silence_detected(self, now_ms: int, silence_threshold: int) -> bool:
        if self.status == InputStatus.SPEAKING and self.last_voice_ms:
            if (now_ms - self.last_voice_ms) > silence_threshold:
                self.status = InputStatus.SILENCE
                self.voice_detected_ms = None
                return True
        return False

    @property
    def is_speaking(self) -> bool:
        return self.status == InputStatus.SPEAKING


__all__ = ["InputState", "InputStatus"]

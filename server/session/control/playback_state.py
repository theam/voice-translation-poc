from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PlaybackStatus(str, Enum):
    IDLE = "idle"
    PLAYING = "playing"
    DRAINING = "draining"
    INTERRUPTED = "interrupted"


@dataclass
class PlaybackState:
    status: PlaybackStatus = PlaybackStatus.IDLE
    current_response_id: Optional[str] = None
    last_audio_sent_ms: int = 0
    provider_done: bool = False
    gate_closed: bool = False

    def on_outbound_audio_sent(self, now_ms: int, response_id: Optional[str] = None) -> None:
        self.last_audio_sent_ms = now_ms
        if response_id:
            self.current_response_id = response_id
        self.provider_done = False
        self.gate_closed = False
        self.status = PlaybackStatus.PLAYING

    def on_provider_done(self, response_id: Optional[str] = None) -> None:
        if response_id:
            self.current_response_id = response_id
        self.provider_done = True
        if self.status == PlaybackStatus.PLAYING:
            self.status = PlaybackStatus.DRAINING

    def on_gate_closed(self) -> None:
        self.gate_closed = True
        self.status = PlaybackStatus.INTERRUPTED

    def on_gate_opened(self) -> None:
        self.gate_closed = False
        if self.status == PlaybackStatus.INTERRUPTED:
            self.status = PlaybackStatus.IDLE

    def on_explicit_playback_end(self, reason: str = "", response_id: Optional[str] = None) -> None:
        if response_id:
            self.current_response_id = response_id
        self.status = PlaybackStatus.IDLE
        self.provider_done = False
        self.gate_closed = False

    def maybe_timeout_idle(self, now_ms: int, idle_timeout_ms: int) -> bool:
        if self.status in {PlaybackStatus.PLAYING, PlaybackStatus.DRAINING}:
            if self.last_audio_sent_ms and (now_ms - self.last_audio_sent_ms) > idle_timeout_ms:
                self.status = PlaybackStatus.IDLE
                return True
        return False

    @property
    def is_active(self) -> bool:
        return self.status in {PlaybackStatus.PLAYING, PlaybackStatus.DRAINING}

    @property
    def is_interrupting(self) -> bool:
        return self.status == PlaybackStatus.INTERRUPTED


__all__ = ["PlaybackState", "PlaybackStatus"]

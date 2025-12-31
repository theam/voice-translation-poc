"""Render final phone conversation audio from ConversationManager data."""
from __future__ import annotations

import logging
from pathlib import Path

from production.capture.conversation_manager import ConversationManager
from production.capture.conversation_tape import ConversationTape


logger = logging.getLogger(__name__)


class ConversationRenderer:
    """Render deterministic phone conversation audio from scenario timeline events."""

    def __init__(self, *, sample_rate: int = 16000, channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.channels = channels

    def write_wav(self, path: Path, conversation_manager: ConversationManager) -> None:
        """Render the mixed conversation WAV directly from the ConversationManager."""
        tape = ConversationTape(sample_rate=self.sample_rate)

        audio_events = conversation_manager.iter_audio_events()
        logger.info(
            "🎵 Rendering phone conversation",
            extra={
                "audio_events": len(audio_events),
                "sample_rate": self.sample_rate,
            },
        )
        for event in audio_events:
            tape.add_pcm(event.start_scn_ms, event.pcm_bytes)

        tape.write_wav(path)


__all__ = ["ConversationRenderer"]

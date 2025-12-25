"""Persist translated audio to disk."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from production.capture.collector import CollectedEvent
from production.capture.conversation_tape import ConversationTape


# Event types that contain audio content for persistence
AUDIO_EVENT_TYPES = [
    "translated_audio",
]


class AudioSink:
    def __init__(self, base_dir: Path, sample_rate: int = 16000) -> None:
        self.base_dir = base_dir
        self.sample_rate = sample_rate
        self.audio_dir = self.base_dir / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    def write_audio_events(self, events: Iterable[CollectedEvent]) -> None:
        tape = ConversationTape(sample_rate=self.sample_rate)

        for event in events:
            if event.audio_payload is None:
                continue

            start_ms = event.timestamp_ms if event.timestamp_ms is not None else 0.0
            tape.add_pcm(start_ms, event.audio_payload)

        file_path = self.audio_dir / "translated_audio.wav"
        tape.write_wav(file_path)


__all__ = ["AudioSink", "AUDIO_EVENT_TYPES"]

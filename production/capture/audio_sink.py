"""Persist translated audio to disk."""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Iterable

from production.capture.collector import CollectedEvent
from production.capture.conversation_tape import ConversationTape


class AudioSink:
    def __init__(self, base_dir: Path, sample_rate: int = 16000) -> None:
        self.base_dir = base_dir
        self.sample_rate = sample_rate
        self.audio_dir = self.base_dir / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    def write_audio_events(self, events: Iterable[CollectedEvent]) -> None:
        for idx, event in enumerate(events):
            if event.audio_payload is None:
                continue
            # Create language pair string for filename
            lang_pair = f"{event.source_language or 'unknown'}_to_{event.target_language or 'unknown'}" if event.source_language or event.target_language else 'unknown'
            file_path = self.audio_dir / f"{idx:03d}_{lang_pair}_{event.participant_id or 'p'}.wav"
            self._write_wav(file_path, event.audio_payload)

    def write_call_mix(self, tape: ConversationTape) -> None:
        """Persist a single WAV containing all audio (inbound + outbound)."""
        file_path = self.audio_dir / "call_mix.wav"
        tape.write_wav(file_path)

    def _write_wav(self, path: Path, payload: bytes) -> None:
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(payload)


__all__ = ["AudioSink"]

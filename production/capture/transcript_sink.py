"""Persist transcript events to structured JSON."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from production.capture.collector import CollectedEvent


# Event types that contain text content for transcription
TEXT_EVENT_TYPES = [
    "translated_delta",
    "translated_text",
]


class TranscriptSink:
    def __init__(self, base_dir: Path) -> None:
        self.path = base_dir / "transcripts.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_transcripts(self, events: Iterable[CollectedEvent]) -> None:
        serializable = [
            {
                "event_type": event.event_type,
                "timestamp_scn_ms": event.timestamp_scn_ms,
                "participant_id": event.participant_id,
                "source_language": event.source_language,
                "target_language": event.target_language,
                "text": event.text,
                "raw": event.raw,
            }
            for event in events
            if event.text is not None
        ]
        self.path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")


__all__ = ["TranscriptSink", "TEXT_EVENT_TYPES"]

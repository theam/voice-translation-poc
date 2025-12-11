"""Scenario data structures."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Participant:
    name: str
    source_language: str
    target_language: str
    audio_files: Dict[str, Path] = field(default_factory=dict)


@dataclass
class Event:
    id: str
    type: str
    participant: str
    audio_file: Optional[str] = None
    start_at_ms: int = 0
    barge_in: bool = False


@dataclass
class TranscriptExpectation:
    id: str
    event_id: str
    source_language: str
    target_language: str
    expected_text: Optional[str] = None
    regex: Optional[str] = None
    wer_threshold: Optional[float] = None


@dataclass
class Expectations:
    transcripts: List[TranscriptExpectation] = field(default_factory=list)
    sequence: List[str] = field(default_factory=list)
    max_latency_ms: Optional[int] = None


@dataclass
class Scenario:
    id: str
    description: str
    participants: Dict[str, Participant]
    events: List[Event]
    expectations: Expectations = field(default_factory=Expectations)
    tags: List[str] = field(default_factory=list)
    score_method: str = "average"  # Score calculator method ("average" or "garbled_turn")


__all__ = [
    "Participant",
    "Event",
    "TranscriptExpectation",
    "Expectations",
    "Scenario",
]

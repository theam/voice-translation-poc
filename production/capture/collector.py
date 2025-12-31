"""Event collection utilities."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class CollectedEvent:
    event_type: str
    timestamp_scn_ms: float
    participant_id: Optional[str] = None
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    text: Optional[str] = None
    audio_payload: Optional[bytes] = None
    raw: Dict | None = None
    arrival_wall_ms: Optional[float] = None


@dataclass
class EventCollector:
    events: List[CollectedEvent] = field(default_factory=list)

    def add(self, event: CollectedEvent) -> None:
        self.events.append(event)

    def by_type(self, event_type: str) -> List[CollectedEvent]:
        return [event for event in self.events if event.event_type == event_type]


__all__ = ["CollectedEvent", "EventCollector"]

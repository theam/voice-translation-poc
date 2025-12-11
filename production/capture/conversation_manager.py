"""Conversation management utilities for organizing ACS messages by turn."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from production.capture.collector import CollectedEvent
from production.utils.time_utils import Clock


logger = logging.getLogger(__name__)


@dataclass
class TurnSummary:
    """Aggregated view of ACS activity for a single scenario event (turn)."""

    turn_id: str
    metadata: Optional[dict] = None
    turn_start_ms: Optional[int] = None
    outbound_messages: List[dict] = field(default_factory=list)
    inbound_events: List[CollectedEvent] = field(default_factory=list)
    first_outbound_ms: Optional[int] = None
    turn_end_ms: Optional[int] = None

    def record_outgoing(
        self, message: dict, timestamp_ms: int, participant_id: str | None = None
    ) -> None:
        """Record an outbound ACS message for this turn."""
        outbound_entry = {"message": message}
        outbound_entry["timestamp_ms"] = timestamp_ms
        if self.first_outbound_ms is None:
            self.first_outbound_ms = timestamp_ms
        if participant_id:
            outbound_entry["participant_id"] = participant_id
        self.outbound_messages.append(outbound_entry)

    def record_incoming(self, event: CollectedEvent) -> None:
        """Record an inbound ACS event for this turn."""
        self.inbound_events.append(event)

    @property
    def translated_text_events(self) -> List[CollectedEvent]:
        return [event for event in self.inbound_events if event.event_type == "translated_delta"]

    def translation_text(self) -> str | None:
        """Return the complete translated text for this turn.

        Translation services send incremental text deltas. This concatenates
        all deltas in chronological order to produce the complete text.

        Returns:
            Complete translated text string (concatenated deltas), or None if no translation events exist
        """
        events = self.translated_text_events
        if not events:
            return None

        # Concatenate all delta texts
        return "".join(event.text for event in events if event.text)

    @property
    def first_response_ms(self) -> Optional[int]:
        if not self.inbound_events:
            return None
        return min(event.timestamp_ms for event in self.inbound_events)

    @property
    def completion_ms(self) -> Optional[int]:
        if not self.inbound_events:
            return None
        return max(event.timestamp_ms for event in self.inbound_events)

    @property
    def latency_ms(self) -> Optional[int]:
        if self.first_outbound_ms is None or self.first_response_ms is None:
            return None
        return self.first_response_ms - self.first_outbound_ms


class ConversationManager:
    """Groups inbound/outbound ACS messages by scenario event (turn)."""

    def __init__(self, *, clock: Clock, scenario_started_at_ms: int) -> None:
        self._turns: List[TurnSummary] = []
        self._turn_lookup: Dict[str, TurnSummary] = {}
        self._participant_turn: Dict[str, str] = {}
        self.clock = clock
        self.scenario_started_at_ms = scenario_started_at_ms
        self._last_outgoing_turn_id: Optional[str] = None

    def now_relative_ms(self) -> int:
        return max(0, self.clock.now_ms() - self.scenario_started_at_ms)

    def start_turn(self, turn_id: str, metadata: dict) -> TurnSummary:
        """Create a turn record before execution begins."""
        if metadata is None:
            raise ValueError("metadata is required when starting a turn")
        if turn_id in self._turn_lookup:
            raise ValueError("Starting the same turn multiple times is not allowed")

        turn_start_ms = self.now_relative_ms()
        summary = TurnSummary(turn_id=turn_id, metadata=metadata, turn_start_ms=turn_start_ms)
        if self._turns:
            # SET END TIMESTAMP TO THE PREVIOUS TURN
            self._turns[-1].turn_end_ms = turn_start_ms

        self._turns.append(summary)
        self._turn_lookup[turn_id] = summary

        logger.info(f"Turn created: '{turn_id}' at {turn_start_ms}ms (type: {metadata.get('type', 'unknown')})")

        return summary

    def get_turn(self, turn_id: str) -> TurnSummary:
        if turn_id not in self._turn_lookup:
            raise ValueError("Missing turn")
        return self._turn_lookup[turn_id]

    def register_outgoing(
        self,
        turn_id: str,
        message: dict,
        *,
        participant_id: Optional[str] = None,
    ) -> None:
        """Associate an outbound message with a turn."""
        turn = self.get_turn(turn_id)
        if participant_id:
            self._participant_turn[participant_id] = turn_id
        timestamp_ms = self.now_relative_ms()
        turn.record_outgoing(message, timestamp_ms=timestamp_ms, participant_id=participant_id)
        self._last_outgoing_turn_id = turn_id

    def register_incoming(self, event: CollectedEvent) -> None:
        """Assign an inbound event to the appropriate turn."""
        turn_id = self._resolve_turn_id(event)
        turn = self._turn_lookup.get(turn_id)
        if turn is None:
            raise ValueError(f"Missing turn for inbound event: {turn_id}")
        turn.record_incoming(event)

    def _resolve_turn_id(self, event: CollectedEvent) -> str:
        timestamp_ms = self.now_relative_ms()

        candidate: Optional[str] = None
        for turn in self._turns:
            start_at_ms = turn.turn_start_ms
            end_at_ms = turn.turn_end_ms
            if timestamp_ms >= start_at_ms and (end_at_ms is None or timestamp_ms < end_at_ms):
                return turn.turn_id
            if timestamp_ms >= start_at_ms:
                candidate = turn.turn_id

        if candidate:
            return candidate
        return self._turns[-1].turn_id if self._turns else "unassigned"

    def get_turn_summary(self, turn_id: str) -> Optional[TurnSummary]:
        return self._turn_lookup.get(turn_id)

    def iter_turns(self) -> Iterable[TurnSummary]:
        return list(self._turns)

    def inbound_events(self) -> List[CollectedEvent]:
        events: List[CollectedEvent] = []
        for turn in self._turns:
            events.extend(turn.inbound_events)
        return events

    def get_turns_summary(self) -> List[Dict[str, str | None]]:
        """Get summary of all turns with their IDs and translated text.

        Returns:
            List of dictionaries with turn_id and translation_text for each turn
        """
        summary = []
        for turn in self._turns:
            summary.append({
                "turn_id": turn.turn_id,
                "start_ms": turn.turn_start_ms,
                "translation_text": turn.translation_text()
            })
        return summary


__all__ = ["ConversationManager", "TurnSummary"]

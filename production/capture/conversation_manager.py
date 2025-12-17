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
    last_outbound_ms: Optional[int] = None
    turn_end_ms: Optional[int] = None

    def record_outgoing(
        self, message: dict, timestamp_ms: int, participant_id: str | None = None
    ) -> None:
        """Record an outbound ACS message for this turn."""
        outbound_entry = {"message": message}
        outbound_entry["timestamp_ms"] = timestamp_ms
        if self.first_outbound_ms is None:
            self.first_outbound_ms = timestamp_ms
        # Always update last outbound to track when audio finished
        self.last_outbound_ms = timestamp_ms
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
        """Get timestamp of first inbound event (any type).

        Note: For audio translation services, consider using first_audio_response_ms
        instead, as that measures when audio (what user hears) actually arrives.
        """
        if not self.inbound_events:
            return None
        return min(event.timestamp_ms for event in self.inbound_events)

    @property
    def first_audio_response_ms(self) -> Optional[int]:
        """Get timestamp of first audio event.

        For audio translation services, this is the true latency metric - when the
        user first hears the translation, not when text appears.
        """
        audio_events = [e for e in self.inbound_events if e.event_type == "translated_audio"]
        if not audio_events:
            return None
        return min(e.timestamp_ms for e in audio_events)

    @property
    def first_text_response_ms(self) -> Optional[int]:
        """Get timestamp of first text event (for comparison with audio)."""
        text_events = [e for e in self.inbound_events if e.event_type in ("translated_delta", "translated_text")]
        if not text_events:
            return None
        return min(e.timestamp_ms for e in text_events)

    @property
    def completion_ms(self) -> Optional[int]:
        if not self.inbound_events:
            return None
        return max(event.timestamp_ms for event in self.inbound_events)

    @property
    def latency_ms(self) -> Optional[int]:
        """Calculate latency from last outbound audio to first AUDIO response.

        With VAD (Voice Activity Detection) enabled, the translation service
        waits for the speaker to stop talking before processing. Therefore,
        latency should be measured from the LAST audio chunk sent, not the first.

        For audio translation services, this measures time until the user HEARS
        the translation (first audio event), not when text appears.

        Returns:
            Milliseconds from last outbound to first audio response, or None if data missing
        """
        # Use last_outbound for VAD-aware latency calculation
        outbound_ref = self.last_outbound_ms if self.last_outbound_ms is not None else self.first_outbound_ms

        # Use first audio response (what user hears), not first text response
        first_response = self.first_audio_response_ms if self.first_audio_response_ms is not None else self.first_response_ms

        if outbound_ref is None or first_response is None:
            return None
        return first_response - outbound_ref

    @property
    def text_latency_ms(self) -> Optional[int]:
        """Calculate latency to first TEXT response (for comparison).

        This shows when text appears, which may be before audio in some services.
        """
        outbound_ref = self.last_outbound_ms if self.last_outbound_ms is not None else self.first_outbound_ms

        if outbound_ref is None or self.first_text_response_ms is None:
            return None
        return self.first_text_response_ms - outbound_ref

    @property
    def first_chunk_latency_ms(self) -> Optional[int]:
        """Calculate latency from FIRST outbound audio to first response.

        This represents the total time including speaking + processing.
        Useful for comparison with VAD-aware latency.

        Returns:
            Milliseconds from first outbound to first response, or None if data missing
        """
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
        timestamp_ms: Optional[int] = None,
    ) -> None:
        """Associate an outbound message with a turn.

        Args:
            turn_id: ID of the turn
            message: The outbound message
            participant_id: Optional participant ID
            timestamp_ms: Optional explicit timestamp (scenario timeline).
                If not provided, uses current wall-clock time.
                For audio, should be the send_at time from scenario timeline.
        """
        turn = self.get_turn(turn_id)
        if participant_id:
            self._participant_turn[participant_id] = turn_id

        # Use provided timestamp (scenario timeline) or fall back to wall-clock
        if timestamp_ms is None:
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

    def log_turns_summary(self) -> None:
        """Log summary of all conversation turns with their IDs and translated text."""
        logger.info(f"Conversation turns to evaluate: {len(self._turns)}")

        for i, turn in enumerate(self._turns):
            translation = turn.translation_text()

            # Calculate timing metrics
            latency = turn.latency_ms  # VAD-aware audio latency: last_outbound → first_audio
            text_latency = turn.text_latency_ms  # Text latency for comparison
            first_chunk_latency = turn.first_chunk_latency_ms  # Total: from first audio chunk
            audio_duration = (turn.last_outbound_ms - turn.first_outbound_ms) if turn.last_outbound_ms and turn.first_outbound_ms else None
            audio_events = [e for e in turn.inbound_events if e.event_type == "translated_audio"]
            text_events = [e for e in turn.inbound_events if e.event_type == "translated_delta"]

            logger.info(
                f"  Turn '{turn.turn_id}' ({turn.turn_start_ms}ms): {translation}"
            )

            if latency is not None:
                logger.info(
                    f"    ⏱️  Audio latency (VAD-aware): {latency}ms "
                    f"(last_outbound={turn.last_outbound_ms}ms → "
                    f"first_audio={turn.first_audio_response_ms}ms)"
                )

                # Show text latency if different from audio latency
                if text_latency is not None and text_latency != latency:
                    diff = latency - text_latency
                    logger.info(
                        f"    ⏱️  Text latency: {text_latency}ms "
                        f"(audio arrives {diff}ms after text)"
                    )

                if first_chunk_latency is not None and audio_duration is not None:
                    logger.info(
                        f"    ⏱️  Total latency: {first_chunk_latency}ms "
                        f"(includes {audio_duration}ms speaking + {latency}ms processing)"
                    )

            if audio_events:
                first_audio = min(e.timestamp_ms for e in audio_events)
                last_audio = max(e.timestamp_ms for e in audio_events)
                logger.info(
                    f"    🔊 Audio: {len(audio_events)} events, "
                    f"first={first_audio}ms, last={last_audio}ms, "
                    f"duration={last_audio - first_audio}ms"
                )

            if text_events:
                first_text = min(e.timestamp_ms for e in text_events)
                last_text = max(e.timestamp_ms for e in text_events)
                logger.info(
                    f"    📝 Text: {len(text_events)} events, "
                    f"first={first_text}ms, last={last_text}ms"
                )

            # Calculate gap from previous turn
            if i > 0:
                prev_turn = self._turns[i - 1]
                prev_audio_events = [e for e in prev_turn.inbound_events if e.event_type == "translated_audio"]

                if prev_audio_events and audio_events:
                    prev_last_audio = max(e.timestamp_ms for e in prev_audio_events)
                    curr_first_audio = min(e.timestamp_ms for e in audio_events)
                    gap = curr_first_audio - prev_last_audio

                    logger.info(
                        f"    ⏸️  Gap from previous turn: {gap}ms "
                        f"(prev ended at {prev_last_audio}ms, current started at {curr_first_audio}ms)"
                    )

                    if gap > 5000:
                        logger.warning(
                            f"    ⚠️  Long gap detected: {gap}ms - "
                            f"This may indicate high service latency or timing issues"
                        )


__all__ = ["ConversationManager", "TurnSummary"]

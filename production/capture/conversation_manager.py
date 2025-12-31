"""Conversation management utilities for organizing ACS messages by turn."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from production.capture.collector import CollectedEvent
from production.utils.time_utils import Clock


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioTimelineEvent:
    start_scn_ms: float
    pcm_bytes: bytes
    direction: str
    participant_id: Optional[str] = None


@dataclass
class TurnSummary:
    """Aggregated view of ACS activity for a single scenario event (turn)."""

    turn_id: str
    metadata: Optional[dict] = None
    turn_start_scn_ms: Optional[int] = None
    turn_start_wall_ms: Optional[int] = None
    turn_end_scn_ms: Optional[int] = None
    turn_end_wall_ms: Optional[int] = None
    outbound_messages: List[dict] = field(default_factory=list)
    outbound_audio_events: List[AudioTimelineEvent] = field(default_factory=list)
    inbound_events: List[CollectedEvent] = field(default_factory=list)
    inbound_audio_events: List[AudioTimelineEvent] = field(default_factory=list)
    inbound_audio_playhead_scn_ms: float = 0.0
    first_outbound_scn_ms: Optional[int] = None
    last_outbound_scn_ms: Optional[int] = None

    def record_outgoing(
        self,
        message: dict,
        *,
        timestamp_scn_ms: float,
        participant_id: str | None = None,
        audio_payload: bytes | None = None,
    ) -> None:
        """Record an outbound ACS message for this turn."""
        outbound_entry = {"message": message, "timestamp_scn_ms": timestamp_scn_ms}
        if self.first_outbound_scn_ms is None:
            self.first_outbound_scn_ms = timestamp_scn_ms
        self.last_outbound_scn_ms = timestamp_scn_ms
        if participant_id:
            outbound_entry["participant_id"] = participant_id
        if audio_payload:
            self.outbound_audio_events.append(
                AudioTimelineEvent(
                    start_scn_ms=timestamp_scn_ms,
                    pcm_bytes=audio_payload,
                    direction="outbound",
                    participant_id=participant_id,
                )
            )
        self.outbound_messages.append(outbound_entry)

    def record_incoming(self, event: CollectedEvent) -> None:
        """Record an inbound ACS event for this turn."""
        self.inbound_events.append(event)
        if event.event_type == "translated_audio" and event.audio_payload:
            self.inbound_audio_events.append(
                AudioTimelineEvent(
                    start_scn_ms=event.timestamp_scn_ms,
                    pcm_bytes=event.audio_payload,
                    direction="inbound",
                    participant_id=event.participant_id,
                )
            )

    @property
    def translated_text_events(self) -> List[CollectedEvent]:
        return [event for event in self.inbound_events if event.event_type == "translated_delta"]

    def translation_text(self) -> str | None:
        """Return the complete translated text for this turn."""
        events = self.translated_text_events
        if not events:
            return None
        return "".join(event.text for event in events if event.text)

    @property
    def first_response_scn_ms(self) -> Optional[int]:
        """Get timestamp of first inbound event (any type)."""
        if not self.inbound_events:
            return None
        return int(min(event.timestamp_scn_ms for event in self.inbound_events))

    @property
    def first_audio_response_scn_ms(self) -> Optional[int]:
        """Get timestamp of first audio event."""
        audio_events = [e for e in self.inbound_events if e.event_type == "translated_audio"]
        if not audio_events:
            return None
        return int(min(e.timestamp_scn_ms for e in audio_events))

    @property
    def first_text_response_scn_ms(self) -> Optional[int]:
        """Get timestamp of first text event (for comparison with audio)."""
        text_events = [e for e in self.inbound_events if e.event_type in ("translated_delta", "translated_text")]
        if not text_events:
            return None
        return int(min(e.timestamp_scn_ms for e in text_events))

    @property
    def completion_scn_ms(self) -> Optional[int]:
        if not self.inbound_events:
            return None
        return int(max(event.timestamp_scn_ms for event in self.inbound_events))

    @property
    def latency_ms(self) -> Optional[int]:
        """Calculate latency from last outbound audio to first AUDIO response."""
        outbound_ref = self.last_outbound_scn_ms if self.last_outbound_scn_ms is not None else self.first_outbound_scn_ms
        first_response = (
            self.first_audio_response_scn_ms
            if self.first_audio_response_scn_ms is not None
            else self.first_response_scn_ms
        )
        if outbound_ref is None or first_response is None:
            return None
        latency = int(first_response - outbound_ref)
        if latency < 0:
            logger.info(
                "Inbound audio overlapped with outbound media",
                extra={
                    "turn_id": self.turn_id,
                    "first_audio_response_scn_ms": first_response,
                    "last_outbound_scn_ms": outbound_ref,
                    "latency_ms": latency,
                },
            )
        return latency

    @property
    def text_latency_ms(self) -> Optional[int]:
        """Calculate latency to first TEXT response (for comparison)."""
        outbound_ref = self.last_outbound_scn_ms if self.last_outbound_scn_ms is not None else self.first_outbound_scn_ms
        if outbound_ref is None or self.first_text_response_scn_ms is None:
            return None
        return int(self.first_text_response_scn_ms - outbound_ref)

    @property
    def first_chunk_latency_ms(self) -> Optional[int]:
        """Calculate latency from FIRST outbound audio to first response."""
        if self.first_outbound_scn_ms is None or self.first_response_scn_ms is None:
            return None
        return int(self.first_response_scn_ms - self.first_outbound_scn_ms)

    @property
    def overlap_ms(self) -> Optional[int]:
        """Return overlap amount when inbound audio precedes outbound completion."""
        outbound_ref = self.last_outbound_scn_ms if self.last_outbound_scn_ms is not None else self.first_outbound_scn_ms
        first_response = self.first_audio_response_scn_ms
        if outbound_ref is None or first_response is None:
            return None
        return max(0, int(outbound_ref - first_response))


class ConversationManager:
    """Groups inbound/outbound ACS messages by scenario event (turn)."""

    def __init__(self, *, clock: Clock, scenario_start_wall_ms: int, sample_rate: int = 16000, channels: int = 1) -> None:
        self._turns: List[TurnSummary] = []
        self._turn_lookup: Dict[str, TurnSummary] = {}
        self._participant_turn: Dict[str, str] = {}
        self.clock = clock
        self.scenario_start_wall_ms = scenario_start_wall_ms
        self.sample_rate = sample_rate
        self.channels = channels
        self._last_outgoing_turn_id: Optional[str] = None
        self.latest_outgoing_media_scn_ms: float = 0.0

    def now_relative_scn_ms(self) -> int:
        return max(0, self._to_scenario_ms(self.clock.now_ms()))

    def _to_scenario_ms(self, wall_ms: float) -> float:
        return float(max(0.0, wall_ms - self.scenario_start_wall_ms))

    def wall_to_scenario_ms(self, wall_ms: float) -> float:
        """Convert a wall-clock timestamp to scenario time."""
        return self._to_scenario_ms(wall_ms)

    def start_turn(self, turn_id: str, metadata: dict, *, turn_start_scn_ms: int, turn_start_wall_ms: Optional[int] = None) -> TurnSummary:
        """Create a turn record before execution begins."""
        if metadata is None:
            raise ValueError("metadata is required when starting a turn")
        if turn_id in self._turn_lookup:
            raise ValueError("Starting the same turn multiple times is not allowed")
        wall_start_ms = float(turn_start_wall_ms if turn_start_wall_ms is not None else self.clock.now_ms())
        summary = TurnSummary(
            turn_id=turn_id,
            metadata=metadata,
            turn_start_scn_ms=turn_start_scn_ms,
            turn_start_wall_ms=wall_start_ms,
            inbound_audio_playhead_scn_ms=float(turn_start_scn_ms),
        )
        if self._turns:
            self._turns[-1].turn_end_scn_ms = turn_start_scn_ms
            self._turns[-1].turn_end_wall_ms = wall_start_ms

        self._turns.append(summary)
        self._turn_lookup[turn_id] = summary

        logger.info(
            "Turn created",
            extra={
                "turn_id": turn_id,
                "turn_start_scn_ms": turn_start_scn_ms,
                "turn_start_wall_ms": wall_start_ms,
                "turn_type": metadata.get("type", "unknown"),
            },
        )

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
        timestamp_scn_ms: Optional[float] = None,
        timestamp_wall_ms: Optional[float] = None,
        audio_payload: bytes | None = None,
    ) -> None:
        """Associate an outbound message with a turn."""
        turn = self.get_turn(turn_id)
        if participant_id:
            self._participant_turn[participant_id] = turn_id

        scenario_timestamp = self._coalesce_timestamp(timestamp_scn_ms, timestamp_wall_ms)
        turn.record_outgoing(
            message,
            timestamp_scn_ms=scenario_timestamp,
            participant_id=participant_id,
            audio_payload=audio_payload,
        )
        self.register_outgoing_media(scenario_timestamp)
        self._last_outgoing_turn_id = turn_id

    def register_incoming(self, event: CollectedEvent) -> str:
        """Assign an inbound event to the appropriate turn using wall-clock arrival."""
        arrival_wall_ms = float(event.arrival_wall_ms if event.arrival_wall_ms is not None else self.clock.now_ms())
        turn = self._resolve_turn_by_wall(arrival_wall_ms)
        if turn is None:
            raise ValueError("Missing turn for inbound event")

        scenario_timestamp = self._scenario_timestamp_for_turn(turn, arrival_wall_ms)
        if event.event_type == "translated_audio" and event.audio_payload:
            scenario_timestamp = self._schedule_inbound_audio(turn, scenario_timestamp, event.audio_payload)
        event.timestamp_scn_ms = scenario_timestamp
        turn.record_incoming(event)
        return turn.turn_id

    def _coalesce_timestamp(self, timestamp_scn_ms: Optional[float], timestamp_wall_ms: Optional[float]) -> float:
        if timestamp_scn_ms is not None:
            return float(timestamp_scn_ms)
        wall_value = timestamp_wall_ms if timestamp_wall_ms is not None else self.clock.now_ms()
        return self._to_scenario_ms(float(wall_value))

    def _scenario_timestamp_for_turn(self, turn: TurnSummary, arrival_wall_ms: float) -> float:
        offset_from_turn_wall = max(0.0, arrival_wall_ms - float(turn.turn_start_wall_ms or 0.0))
        return float(turn.turn_start_scn_ms or 0.0) + offset_from_turn_wall

    def _schedule_inbound_audio(self, turn: TurnSummary, candidate_start_scn_ms: float, pcm_bytes: bytes) -> float:
        duration_ms = self._pcm_duration_ms(pcm_bytes)
        start_ms = max(candidate_start_scn_ms, turn.inbound_audio_playhead_scn_ms)
        turn.inbound_audio_playhead_scn_ms = start_ms + duration_ms
        return start_ms

    def _resolve_turn_by_wall(self, arrival_wall_ms: float) -> Optional[TurnSummary]:
        candidate: Optional[TurnSummary] = None
        for turn in self._turns:
            start_wall_ms = float(turn.turn_start_wall_ms or 0.0)
            end_wall_ms = turn.turn_end_wall_ms
            if arrival_wall_ms >= start_wall_ms and (end_wall_ms is None or arrival_wall_ms < end_wall_ms):
                return turn
            if arrival_wall_ms >= start_wall_ms:
                candidate = turn
        return candidate or (self._turns[-1] if self._turns else None)

    def get_turn_summary(self, turn_id: str) -> Optional[TurnSummary]:
        return self._turn_lookup.get(turn_id)

    def iter_turns(self) -> Iterable[TurnSummary]:
        return list(self._turns)

    def inbound_events(self) -> List[CollectedEvent]:
        events: List[CollectedEvent] = []
        for turn in self._turns:
            events.extend(turn.inbound_events)
        return events

    def iter_audio_events(self) -> List[AudioTimelineEvent]:
        events: List[AudioTimelineEvent] = []
        for turn in self._turns:
            events.extend(turn.outbound_audio_events)
            events.extend(turn.inbound_audio_events)
        return sorted(events, key=lambda event: (event.start_scn_ms, event.direction, event.participant_id or ""))

    def register_outgoing_media(self, timestamp_scn_ms: float) -> None:
        """Advance the media clock based on an outbound media timestamp."""
        self.latest_outgoing_media_scn_ms = max(self.latest_outgoing_media_scn_ms, float(timestamp_scn_ms))

    def _pcm_duration_ms(self, pcm_bytes: bytes) -> float:
        frame_bytes = self.channels * 2
        trimmed_len = len(pcm_bytes) - (len(pcm_bytes) % frame_bytes)
        if trimmed_len <= 0:
            return 0.0
        return trimmed_len / (self.sample_rate * frame_bytes) * 1000.0

    def pcm_duration_ms(self, pcm_bytes: bytes) -> float:
        """Public helper for computing PCM duration using configured sample rate and channels."""
        return self._pcm_duration_ms(pcm_bytes)

    def log_turns_summary(self) -> None:
        """Log summary of all conversation turns with their IDs and translated text."""
        logger.info(f"Conversation turns to evaluate: {len(self._turns)}")

        for i, turn in enumerate(self._turns):
            translation = turn.translation_text()

            latency = turn.latency_ms
            text_latency = turn.text_latency_ms
            first_chunk_latency = turn.first_chunk_latency_ms
            audio_duration = (
                turn.last_outbound_scn_ms - turn.first_outbound_scn_ms
                if turn.last_outbound_scn_ms is not None and turn.first_outbound_scn_ms is not None
                else None
            )
            audio_events = [e for e in turn.inbound_events if e.event_type == "translated_audio"]
            text_events = [e for e in turn.inbound_events if e.event_type == "translated_delta"]

            logger.info(f"  Turn '{turn.turn_id}' ({turn.turn_start_scn_ms}ms): {translation}")

            if latency is not None:
                logger.info(
                    f"    ⏱️  Audio latency (VAD-aware): {latency}ms "
                    f"(last_outbound={turn.last_outbound_scn_ms}ms → "
                    f"first_audio={turn.first_audio_response_scn_ms}ms)"
                )

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
                first_audio = min(e.timestamp_scn_ms for e in audio_events)
                last_audio = max(e.timestamp_scn_ms for e in audio_events)
                logger.info(
                    f"    🔊 Audio: {len(audio_events)} events, "
                    f"first={first_audio}ms, last={last_audio}ms, "
                    f"duration={last_audio - first_audio}ms"
                )

            if text_events:
                first_text = min(e.timestamp_scn_ms for e in text_events)
                last_text = max(e.timestamp_scn_ms for e in text_events)
                logger.info(
                    f"    📝 Text: {len(text_events)} events, "
                    f"first={first_text}ms, last={last_text}ms"
                )

            if i > 0:
                prev_turn = self._turns[i - 1]
                prev_audio_events = [e for e in prev_turn.inbound_events if e.event_type == "translated_audio"]

                if prev_audio_events and audio_events:
                    prev_last_audio = max(e.timestamp_scn_ms for e in prev_audio_events)
                    curr_first_audio = min(e.timestamp_scn_ms for e in audio_events)
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


__all__ = ["ConversationManager", "TurnSummary", "AudioTimelineEvent"]

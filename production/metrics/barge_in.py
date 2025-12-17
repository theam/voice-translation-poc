"""Barge-in handling metric for evaluating translation interruption quality.

Evaluates how well the translation system handles scenarios where a speaker
interrupts their own ongoing translation to correct or add information.

**IMPORTANT**: This metric measures AUDIO stream timing, not text timing.
What matters is when the translated audio that the user hears stops playing,
not when text deltas stop arriving.

Scoring criteria:
- Audio from previous turn stops quickly after barge-in (60% weight)
- No audio mixing between turns (30% weight)
- Quick audio response to new turn (10% weight)

Measured via `translated_audio` events, which represent the actual audio
stream delivered to the user.

Example scenario:
    Turn 1: Patient describes symptoms (0-14s)
    Turn 2: Patient interrupts with correction (16s, barge_in=True)

    Good handling:
    - Turn 1 audio stops within 500ms of Turn 2 starting
    - No mixed audio between turns
    - Turn 2 audio starts promptly
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from production.capture.conversation_manager import ConversationManager, TurnSummary
from production.scenario_engine.models import Scenario, ScenarioTurn

from .base import Metric, MetricResult

logger = logging.getLogger(__name__)


class BargeInMetric(Metric):
    """Evaluate barge-in handling quality.

    Measures how effectively the system handles speaker interruptions
    by analyzing translation cutoff timing, content mixing, and responsiveness.

    The metric identifies turns marked with barge_in=True and evaluates:
    1. How quickly the previous turn's translation stopped
    2. Whether translations from different turns got mixed
    3. How quickly the system responded to the new turn
    """

    name = "barge_in"

    def __init__(
        self,
        scenario: Scenario,
        conversation_manager: ConversationManager,
        threshold: float = 70.0
    ) -> None:
        """Initialize barge-in metric.

        Args:
            scenario: Scenario with barge_in flags on turns
            conversation_manager: Conversation manager with timing data
            threshold: Minimum acceptable score (default: 70.0)
        """
        self.scenario = scenario
        self.conversation_manager = conversation_manager
        self.threshold = threshold

    def run(self) -> MetricResult:
        """Evaluate barge-in handling for all barge-in turns.

        Returns:
            MetricResult with barge-in handling scores per turn and overall
        """
        barge_in_pairs = self._find_barge_in_turns()

        if not barge_in_pairs:
            logger.info("No barge-in turns found in scenario")
            return MetricResult(
                metric_name=self.name,
                score=None,
                reason="No barge-in turns found in scenario",
                details={"turns": []}
            )

        # Log event types for debugging
        self._log_event_types_debug()

        evaluations = []
        total_score = 0.0

        for prev_turn, barge_in_turn in barge_in_pairs:
            # Get turn summaries
            prev_summary = self.conversation_manager.get_turn_summary(prev_turn.id)
            barge_in_summary = self.conversation_manager.get_turn_summary(barge_in_turn.id)

            if not prev_summary or not barge_in_summary:
                logger.warning(
                    f"Missing turn summary for barge-in pair: {prev_turn.id}, {barge_in_turn.id}"
                )
                continue

            # Calculate metrics
            cutoff_latency = self._calculate_cutoff_latency(prev_summary, barge_in_summary)
            mixing_result = self._detect_content_mixing(prev_summary, barge_in_summary)
            response_time = barge_in_summary.latency_ms

            # Calculate score
            score = self._calculate_barge_in_score(
                cutoff_latency if cutoff_latency is not None else 10000,
                mixing_result["score"],
                response_time
            )

            logger.info(
                f"Barge-in evaluation: {barge_in_turn.id} - "
                f"Score: {score:.1f}, Cutoff: {cutoff_latency}ms, "
                f"Mixing: {mixing_result['mixed']}, Response: {response_time}ms"
            )

            evaluation = {
                "turn_id": barge_in_turn.id,
                "previous_turn_id": prev_turn.id,
                "barge_in_start_ms": barge_in_summary.turn_start_ms,
                "score": round(score, 2),
                "cutoff_latency_ms": cutoff_latency,
                "mixing_detected": mixing_result["mixed"],
                "response_time_ms": response_time,
                "interpretation": self._interpret_score(score),
                "details": {
                    "cutoff_score": round(self._score_cutoff_latency(
                        cutoff_latency if cutoff_latency is not None else 10000
                    ), 2),
                    "mixing_score": round(mixing_result["score"], 2),
                    "response_score": round(self._score_response_time(response_time), 2)
                }
            }

            evaluations.append(evaluation)
            total_score += score

        # Calculate average score
        avg_score = total_score / len(evaluations) if evaluations else 0.0

        return MetricResult(
            metric_name=self.name,
            score=round(avg_score, 2),
            reason=None,
            details={
                "threshold": self.threshold,
                "barge_in_count": len(evaluations),
                "turns": evaluations,
                "overall_interpretation": self._interpret_score(avg_score)
            }
        )

    def _find_barge_in_turns(self) -> List[Tuple[ScenarioTurn, ScenarioTurn]]:
        """Find pairs of (previous_turn, barge_in_turn).

        Returns:
            List of tuples where second element has barge_in=True
        """
        barge_in_pairs = []
        turns = self.scenario.turns

        for i, turn in enumerate(turns):
            if turn.barge_in and i > 0:
                previous_turn = turns[i - 1]
                barge_in_pairs.append((previous_turn, turn))
                logger.info(
                    f"Found barge-in pair: {previous_turn.id} -> {turn.id} "
                    f"(barge-in at {turn.start_at_ms}ms)"
                )

        return barge_in_pairs

    def _calculate_cutoff_latency(
        self,
        previous_turn: TurnSummary,
        barge_in_turn: TurnSummary
    ) -> Optional[int]:
        """Calculate time from barge-in start until last previous audio event.

        This measures when the AUDIO stream from the previous turn actually stopped,
        not when text stopped arriving. Audio is what the user hears.

        Args:
            previous_turn: Summary of the turn being interrupted
            barge_in_turn: Summary of the interrupting turn

        Returns:
            Milliseconds from barge-in start to last previous turn audio event,
            or 0 if no audio after barge-in, or None if no previous audio
        """
        barge_in_start_ms = barge_in_turn.turn_start_ms

        # Find AUDIO events from previous turn after barge-in started
        # Audio is what actually plays to the user, not text deltas
        late_audio_events = [
            event for event in previous_turn.inbound_events
            if event.event_type == "translated_audio"
            and event.timestamp_ms > barge_in_start_ms
        ]

        if not late_audio_events:
            # Perfect! No audio after barge-in
            logger.debug(
                f"No late audio from {previous_turn.turn_id} after barge-in at {barge_in_start_ms}ms"
            )
            return 0

        # Find the last audio event from previous turn
        last_audio_ms = max(event.timestamp_ms for event in late_audio_events)
        cutoff_latency_ms = last_audio_ms - barge_in_start_ms

        logger.debug(
            f"Audio cutoff latency: {cutoff_latency_ms}ms "
            f"({len(late_audio_events)} audio events after barge-in)"
        )

        return cutoff_latency_ms

    def _detect_content_mixing(
        self,
        previous_turn_summary: TurnSummary,
        barge_in_turn_summary: TurnSummary
    ) -> dict:
        """Detect if audio from both turns got mixed together.

        Audio mixing occurs when audio streams from different turns overlap,
        causing the user to hear confused/mixed output.

        Args:
            previous_turn_summary: Summary of the interrupted turn
            barge_in_turn_summary: Summary of the interrupting turn

        Returns:
            Dictionary with mixing detection results and score
        """
        barge_in_start = barge_in_turn_summary.turn_start_ms

        # Get AUDIO events for barge-in turn
        barge_in_audio_events = [
            event for event in barge_in_turn_summary.inbound_events
            if event.event_type == "translated_audio"
        ]

        # Get AUDIO events for previous turn
        previous_audio_events = [
            event for event in previous_turn_summary.inbound_events
            if event.event_type == "translated_audio"
        ]

        if not previous_audio_events:
            # No previous audio to mix with
            return {
                "mixed": False,
                "score": 100.0,
                "reason": "No previous audio to mix with",
                "overlap_ms": 0,
                "overlapping_events": 0
            }

        # Find the last audio event from previous turn
        previous_last_audio_ms = max(
            event.timestamp_ms for event in previous_audio_events
        )

        # Count barge-in audio events that arrived while previous audio was still playing
        early_barge_in_audio = [
            event for event in barge_in_audio_events
            if event.timestamp_ms < previous_last_audio_ms
        ]

        # Mixing is detected if:
        # 1. Previous turn audio was still arriving after barge-in started
        # 2. New turn audio arrived during this overlap
        mixing_detected = (
            len(early_barge_in_audio) > 0
            and previous_last_audio_ms > barge_in_start
        )

        overlap_ms = max(0, previous_last_audio_ms - barge_in_start) if previous_last_audio_ms > barge_in_start else 0

        if mixing_detected:
            logger.warning(
                f"Audio mixing detected: {len(early_barge_in_audio)} barge-in audio events "
                f"arrived before previous turn audio completed (overlap: {overlap_ms}ms)"
            )

        return {
            "mixed": mixing_detected,
            "score": 0.0 if mixing_detected else 100.0,
            "reason": "Audio mixing detected" if mixing_detected else "No audio mixing detected",
            "overlap_ms": overlap_ms,
            "overlapping_events": len(early_barge_in_audio)
        }

    def _score_cutoff_latency(self, cutoff_latency_ms: int) -> float:
        """Score cutoff latency on 0-100 scale.

        Args:
            cutoff_latency_ms: Milliseconds until translation stopped

        Returns:
            Score from 0-100
        """
        if cutoff_latency_ms == 0:
            return 100.0
        elif cutoff_latency_ms <= 500:
            return 90.0 + (500 - cutoff_latency_ms) / 500 * 10
        elif cutoff_latency_ms <= 1000:
            return 70.0 + (1000 - cutoff_latency_ms) / 500 * 20
        elif cutoff_latency_ms <= 2000:
            return 40.0 + (2000 - cutoff_latency_ms) / 1000 * 30
        elif cutoff_latency_ms <= 5000:
            return 10.0 + (5000 - cutoff_latency_ms) / 3000 * 30
        else:
            return max(0.0, 10.0 - (cutoff_latency_ms - 5000) / 1000)

    def _score_response_time(self, response_time_ms: Optional[int]) -> float:
        """Score response time on 0-100 scale.

        Args:
            response_time_ms: Milliseconds from audio to first translation

        Returns:
            Score from 0-100
        """
        if response_time_ms is None:
            return 0.0
        elif response_time_ms <= 1000:
            return 100.0
        elif response_time_ms <= 2000:
            return 80.0 + (2000 - response_time_ms) / 1000 * 20
        elif response_time_ms <= 3000:
            return 60.0 + (3000 - response_time_ms) / 1000 * 20
        elif response_time_ms <= 5000:
            return 30.0 + (5000 - response_time_ms) / 2000 * 30
        else:
            return max(0.0, 30.0 - (response_time_ms - 5000) / 1000)

    def _calculate_barge_in_score(
        self,
        cutoff_latency_ms: int,
        mixing_score: float,
        response_time_ms: Optional[int]
    ) -> float:
        """Calculate overall barge-in handling score.

        Weighting:
            - Cutoff latency: 60% (most important - did it stop?)
            - Content mixing: 30% (critical - was output correct?)
            - Response time: 10% (nice to have - was it fast?)

        Args:
            cutoff_latency_ms: Time to stop previous translation
            mixing_score: Score for content mixing (0 or 100)
            response_time_ms: Time to respond to new turn

        Returns:
            Overall score from 0-100
        """
        cutoff_score = self._score_cutoff_latency(cutoff_latency_ms)
        response_score = self._score_response_time(response_time_ms)

        # Weighted average
        total_score = (
            cutoff_score * 0.60 +
            mixing_score * 0.30 +
            response_score * 0.10
        )

        return total_score

    def _interpret_score(self, score: float) -> str:
        """Provide human-readable interpretation of score.

        Args:
            score: Barge-in handling score (0-100)

        Returns:
            Human-readable interpretation
        """
        if score >= 90:
            return "Excellent barge-in handling"
        elif score >= 70:
            return "Good barge-in handling"
        elif score >= 50:
            return "Acceptable barge-in handling"
        elif score >= 30:
            return "Poor barge-in handling"
        else:
            return "Very poor barge-in handling"

    def _log_event_types_debug(self) -> None:
        """Log event types found in conversation for debugging.

        Helps identify if audio events are present vs only text events.
        """
        all_event_types = set()
        for turn in self.conversation_manager.iter_turns():
            for event in turn.inbound_events:
                all_event_types.add(event.event_type)

        logger.info(
            f"Event types in conversation: {sorted(all_event_types)}"
        )

        # Specifically check for audio events
        has_audio = "translated_audio" in all_event_types
        if not has_audio:
            logger.warning(
                "No 'translated_audio' events found! Barge-in metric measures audio timing. "
                "If only text events exist, the metric may not accurately reflect audio behavior."
            )


__all__ = ["BargeInMetric"]

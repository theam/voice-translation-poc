"""Audio Overlap Metric for detecting inbound audio arriving during outbound transmission.

This metric detects when the system's audio response arrives while the user is still
sending audio, which can indicate interruption handling or system responsiveness issues.

Scoring:
- No overlap: 100% (ideal - clean turn-taking)
- 0-2000ms overlap: 50-100% (linear scale, some overlap acceptable)
- >2000ms overlap: 0% (severe overlap indicates poor turn-taking)

Overall score: 0% if any turn scores 0%, otherwise average of all turn scores.
"""
from __future__ import annotations

import logging
from typing import List

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Scenario

from .base import Metric, MetricResult


logger = logging.getLogger(__name__)


def _calculate_overlap_score(overlap_ms: int) -> float:
    """Calculate score based on overlap duration.

    Args:
        overlap_ms: Milliseconds of overlap (can be negative for no overlap)

    Returns:
        Score from 0.0 to 100.0
    """
    if overlap_ms <= 0:
        # No overlap - perfect score
        return 100.0
    elif overlap_ms <= 2000:
        # Linear scale: 100% at 0ms, 50% at 2000ms
        # Formula: 100 - (overlap_ms / 2000) * 50
        return 100.0 - (overlap_ms / 2000.0) * 50.0
    else:
        # Severe overlap - zero score
        return 0.0


class OverlapMetric(Metric):
    """Detect and score audio overlap during transmission.

    This metric checks if inbound audio (translation response) arrives while
    outbound audio is still being sent. Overlap indicates:
    - Streaming/real-time processing (may be intentional)
    - Turn-taking issues (user interrupted before finishing)
    - System responsiveness characteristics

    The metric examines each turn's timing data:
    - first_audio_response_ms: When translation audio starts arriving
    - last_outbound_ms: When user finishes sending audio

    If first_audio_response_ms < last_outbound_ms, overlap is detected.

    Example:
        Turn sends audio from 0ms to 5000ms (5 seconds)
        Translation arrives at 4000ms (1 second before sending completes)
        → Overlap = 1000ms → Score = 75%
    """

    name = "overlap"

    def __init__(
        self,
        scenario: Scenario,
        conversation_manager: ConversationManager,
    ) -> None:
        """Initialize overlap metric.

        Args:
            scenario: Scenario with turns to evaluate
            conversation_manager: Conversation manager with timing data
        """
        self.scenario = scenario
        self.conversation_manager = conversation_manager

    def run(self) -> MetricResult:
        """Calculate overlap scores for all turns.

        Returns:
            MetricResult with per-turn and overall overlap scores
        """
        turns_to_evaluate = self.scenario.turns_to_evaluate()

        if not turns_to_evaluate:
            return MetricResult(
                metric_name=self.name,
                score=100.0,
                reason="No turns to evaluate",
                details={"turns": []}
            )

        turn_results = []
        has_critical_overlap = False
        total_score = 0.0
        evaluated_count = 0

        for turn in turns_to_evaluate:
            turn_summary = self.conversation_manager.get_turn_summary(turn.id)

            if not turn_summary:
                logger.warning(f"No turn summary found for {turn.id}")
                continue

            # Get timing data
            last_outbound_ms = turn_summary.last_outbound_ms
            first_audio_response_ms = turn_summary.first_audio_response_ms

            # Check if we have the necessary timing data
            if last_outbound_ms is None or first_audio_response_ms is None:
                turn_results.append({
                    "turn_id": turn.id,
                    "score": None,
                    "status": "skipped",
                    "reason": "Missing timing data",
                    "last_outbound_ms": last_outbound_ms,
                    "first_audio_response_ms": first_audio_response_ms
                })
                continue

            # Calculate overlap
            # Overlap occurs if response arrives before we finish sending
            overlap_ms = last_outbound_ms - first_audio_response_ms

            # Calculate score
            score = _calculate_overlap_score(overlap_ms)

            # Track if any turn has critical overlap (0% score)
            if score == 0.0:
                has_critical_overlap = True

            total_score += score
            evaluated_count += 1

            # Determine status and reason
            if overlap_ms <= 0:
                status = "pass"
                reason = "No overlap detected"
            elif overlap_ms <= 2000:
                status = "pass"
                reason = f"Minor overlap: {overlap_ms}ms (acceptable)"
            else:
                status = "fail"
                reason = f"Critical overlap: {overlap_ms}ms (exceeds 2000ms threshold)"

            logger.info(
                f"Overlap [{turn.id}]: "
                f"last_outbound={last_outbound_ms}ms, "
                f"first_audio_response={first_audio_response_ms}ms, "
                f"overlap={overlap_ms}ms, "
                f"score={score:.1f}%"
            )

            turn_results.append({
                "turn_id": turn.id,
                "score": score,
                "status": status,
                "reason": reason,
                "overlap_ms": overlap_ms,
                "last_outbound_ms": last_outbound_ms,
                "first_audio_response_ms": first_audio_response_ms
            })

        # Calculate overall score
        if evaluated_count == 0:
            overall_score = 100.0
            overall_reason = "No turns with timing data to evaluate"
        elif has_critical_overlap:
            # If any turn has critical overlap (0%), overall is 0%
            overall_score = 0.0
            overall_reason = "One or more turns have critical overlap (>2000ms)"
        else:
            # Average of all turn scores
            overall_score = total_score / evaluated_count
            overall_reason = None

        return MetricResult(
            metric_name=self.name,
            score=overall_score,
            reason=overall_reason,
            details={
                "evaluations": evaluated_count,
                "turns": turn_results,
                "has_critical_overlap": has_critical_overlap,
                "scoring": {
                    "no_overlap": "100%",
                    "0_2000ms": "50-100% (linear)",
                    "over_2000ms": "0%"
                }
            }
        )


__all__ = ["OverlapMetric"]

"""Garbled turn-based score calculator.

Calculates test score based on conversational quality metrics.
Flags turns as "garbled" if any quality dimension is low (≤ 40 on 0-100 scale).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from production.metrics.base import MetricResult

from .base import ScoreCalculator, TestScore


logger = logging.getLogger(__name__)


class GarbledTurnScoreCalculator(ScoreCalculator):
    """Calculate test score based on garbled turn rate.

    Aggregates intelligibility, segmentation, and context scores to:
    1. Flag each turn as "garbled" if ANY score ≤ garbled_score_threshold (default 40)
    2. Calculate garbled_turn_rate = garbled_turns / total_turns
    3. Score = (1 - garbled_turn_rate) * 100

    Score calculation:
    - score = (1 - garbled_turn_rate) * 100

    Example:
        20 turns total, 3 are garbled
        → garbled_turn_rate = 15%
        → score = 85.0

    Garbled detection rule:
        garbled = (intelligibility ≤ 40) OR (segmentation ≤ 40) OR (context ≤ 40)
    """

    name = "garbled_turn"

    def __init__(
        self,
        garbled_threshold: float = 10.0,
        garbled_score_threshold: float = 40.0
    ):
        """Initialize calculator.

        Args:
            garbled_threshold: Maximum acceptable garbled turn rate (percent, default: 10)
            garbled_score_threshold: Score threshold for flagging as garbled (default: 40)
        """
        self.garbled_threshold = garbled_threshold
        self.garbled_score_threshold = garbled_score_threshold

    def calculate(self, metric_results: List[MetricResult]) -> TestScore:
        """Calculate garbled turn-based test score.

        Args:
            metric_results: List of metric results from test execution

        Returns:
            TestScore with score, status, and per-turn garbled flags
        """
        # Extract the 3 conversational quality metrics
        intelligibility_result = self._find_metric("intelligibility", metric_results)
        segmentation_result = self._find_metric("segmentation", metric_results)
        context_result = self._find_metric("context", metric_results)

        # Check if all required metrics are present
        if not all([intelligibility_result, segmentation_result, context_result]):
            missing = []
            if not intelligibility_result:
                missing.append("intelligibility")
            if not segmentation_result:
                missing.append("segmentation")
            if not context_result:
                missing.append("context")

            logger.warning(
                f"Garbled turn calculator requires intelligibility, segmentation, and context metrics. "
                f"Missing: {', '.join(missing)}"
            )

            return TestScore(
                score=0.0,
                score_method=self.name,
                details={
                    "error": f"Missing required metrics: {', '.join(missing)}",
                    "required_metrics": ["intelligibility", "segmentation", "context"]
                }
            )

        # Combine per-event scores and flag garbled turns
        event_scores = self._combine_event_scores(
            intelligibility_result,
            segmentation_result,
            context_result
        )

        if not event_scores:
            logger.warning("No event scores found in metric results")
            return TestScore(
                score=0.0,
                score_method=self.name,
                details={"error": "No events to evaluate"}
            )

        # Calculate garbled turn rate
        total_turns = len(event_scores)
        garbled_turns = sum(1 for e in event_scores if e["garbled"])
        garbled_turn_rate = garbled_turns / total_turns
        garbled_turn_rate_percent = garbled_turn_rate * 100.0

        # Calculate score (inverse of garbled rate) on 0-100 scale
        score = 100.0 - garbled_turn_rate_percent
        score = round(score, 2)

        # Build details
        details = {
            "garbled_turn_rate": f"{garbled_turn_rate_percent:.2f}%",
            "garbled_rate_threshold": f"{self.garbled_threshold:.2f}%",
            "garbled_score_threshold": self.garbled_score_threshold,
            "total_turns": total_turns,
            "garbled_turns": garbled_turns,
            "clean_turns": total_turns - garbled_turns,
            "exceeds_threshold": garbled_turn_rate_percent > self.garbled_threshold,
            "event_scores": event_scores,
            # Session-level averages
            "avg_intelligibility": self._calculate_avg_score(event_scores, "intelligibility_score"),
            "avg_segmentation": self._calculate_avg_score(event_scores, "segmentation_score"),
            "avg_context": self._calculate_avg_score(event_scores, "context_score"),
        }

        logger.info(
            f"Garbled turn score calculated: {score:.2f} "
            f"(garbled_turn_rate: {garbled_turn_rate_percent:.1f}%, "
            f"{garbled_turns}/{total_turns} garbled)"
        )

        return TestScore(
            score=score,
            score_method=self.name,
            details=details
        )

    def _find_metric(self, metric_name: str, results: List[MetricResult]) -> Optional[MetricResult]:
        """Find metric result by name.

        Args:
            metric_name: Name of metric to find
            results: List of metric results

        Returns:
            MetricResult if found, None otherwise
        """
        for result in results:
            if result.metric_name == metric_name:
                return result
        return None

    def _combine_event_scores(
        self,
        intelligibility: MetricResult,
        segmentation: MetricResult,
        context: MetricResult
    ) -> List[Dict[str, Any]]:
        """Combine per-turn scores from the 3 metrics.

        Matches turns by turn_id and combines their scores.
        Flags as garbled if ANY score ≤ garbled_score_threshold (default 40 on 0-100 scale).

        Args:
            intelligibility: Intelligibility metric result
            segmentation: Segmentation metric result
            context: Context metric result

        Returns:
            List of turn score dictionaries with garbled flags
        """
        # Extract per-turn results from metric details
        intell_turns = self._extract_turn_results(intelligibility)
        segment_turns = self._extract_turn_results(segmentation)
        context_turns = self._extract_turn_results(context)

        # Build turn score map (keyed by turn_id)
        turn_map: Dict[str, Dict[str, Any]] = {}

        for turn in intell_turns:
            turn_id = turn.get("turn_id")
            if not turn_id:
                continue
            turn_map[turn_id] = {
                "turn_id": turn_id,
                "intelligibility_score": turn.get("score", 0.0),
            }

        for turn in segment_turns:
            turn_id = turn.get("turn_id")
            if turn_id and turn_id in turn_map:
                turn_map[turn_id]["segmentation_score"] = turn.get("score", 0.0)

        for turn in context_turns:
            turn_id = turn.get("turn_id")
            if turn_id and turn_id in turn_map:
                turn_map[turn_id]["context_score"] = turn.get("score", 0.0)

        # Calculate garbled flags
        turn_scores = []
        for turn_id, scores in turn_map.items():
            # Check if all three scores are present
            if not all(
                key in scores
                for key in ["intelligibility_score", "segmentation_score", "context_score"]
            ):
                logger.warning(f"Turn {turn_id} missing some quality scores, skipping")
                continue

            intell = scores["intelligibility_score"]
            segment = scores["segmentation_score"]
            ctx = scores["context_score"]

            # Garbled if ANY score ≤ threshold
            is_garbled = any(
                score <= self.garbled_score_threshold
                for score in [intell, segment, ctx]
            )

            # Determine reason
            reason = None
            if is_garbled:
                low_scores = []
                if intell <= self.garbled_score_threshold:
                    low_scores.append(f"intelligibility ({intell:.2f})")
                if segment <= self.garbled_score_threshold:
                    low_scores.append(f"segmentation ({segment:.2f})")
                if ctx <= self.garbled_score_threshold:
                    low_scores.append(f"context ({ctx:.2f})")
                reason = f"Low scores: {', '.join(low_scores)}"

            turn_scores.append({
                "turn_id": turn_id,
                "intelligibility_score": round(intell, 4),
                "segmentation_score": round(segment, 4),
                "context_score": round(ctx, 4),
                "garbled": is_garbled,
                "reason": reason
            })

        return turn_scores

    def _extract_turn_results(self, metric_result: MetricResult) -> List[Dict[str, Any]]:
        """Extract per-turn results from metric details.

        Args:
            metric_result: Metric result with details

        Returns:
            List of per-turn result dictionaries
        """
        if not metric_result.details:
            return []

        # Handle single turn (context metric with "last_turn")
        if "last_turn" in metric_result.details:
            turn = metric_result.details["last_turn"]
            if turn and turn.get("status") == "evaluated":
                return [turn]
            return []

        # Handle multiple turns (segmentation/intelligibility with "results")
        results = metric_result.details.get("results", [])
        if not isinstance(results, list):
            return []

        # Filter to only "evaluated" status
        return [r for r in results if r.get("status") == "evaluated"]

    def _calculate_avg_score(self, turn_scores: List[Dict[str, Any]], score_key: str) -> float:
        """Calculate average score across turns.

        Args:
            turn_scores: List of turn score dictionaries
            score_key: Key to extract (e.g., "intelligibility_score")

        Returns:
            Average score (0-100 scale)
        """
        if not turn_scores:
            return 0.0

        total = sum(t.get(score_key, 0) for t in turn_scores)
        return round(total / len(turn_scores), 2)


__all__ = ["GarbledTurnScoreCalculator"]

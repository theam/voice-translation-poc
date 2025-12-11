"""Garbled turn-based score calculator.

Calculates test score based on conversational quality metrics.
Flags turns as "garbled" if any quality dimension is low (≤ 2 out of 5).
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
    1. Flag each turn as "garbled" if ANY score ≤ 2 (out of 5)
    2. Calculate garbled_turn_rate = garbled_turns / total_turns
    3. Determine status based on rate threshold (default 10%)

    Score calculation:
    - score = (1 - garbled_turn_rate) * 100
    - status = "garbled" if rate > threshold, "success" otherwise

    Example:
        20 turns total, 3 are garbled
        → garbled_turn_rate = 15%
        → score = 85.0
        → status = "garbled" (exceeds 10% threshold)

    Garbled detection rule:
        garbled = (intelligibility ≤ 2) OR (segmentation ≤ 2) OR (context ≤ 2)

    Thresholds:
        - Score ≤ 2 on 1-5 scale = score_normalized ≤ 0.25 on 0-1 scale
    """

    name = "garbled_turn"

    def __init__(self, garbled_threshold: float = 0.10):
        """Initialize calculator.

        Args:
            garbled_threshold: Maximum acceptable garbled turn rate (default: 0.10 = 10%)
        """
        self.garbled_threshold = garbled_threshold

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
                score_status="error",
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
                score_status="error",
                details={"error": "No events to evaluate"}
            )

        # Calculate garbled turn rate
        total_turns = len(event_scores)
        garbled_turns = sum(1 for e in event_scores if e["garbled"])
        garbled_turn_rate = garbled_turns / total_turns

        # Calculate score (inverse of garbled rate)
        score = (1 - garbled_turn_rate) * 100.0
        score = round(score, 2)

        # Determine status
        status = "garbled" if garbled_turn_rate > self.garbled_threshold else "success"

        # Build details
        details = {
            "garbled_turn_rate": f"{garbled_turn_rate * 100:.2f}%",
            "threshold": f"{self.garbled_threshold * 100:.2f}%",
            "total_turns": total_turns,
            "garbled_turns": garbled_turns,
            "clean_turns": total_turns - garbled_turns,
            "event_scores": event_scores,
            # Session-level averages
            "avg_intelligibility": self._calculate_avg_score(event_scores, "intelligibility_score"),
            "avg_segmentation": self._calculate_avg_score(event_scores, "segmentation_score"),
            "avg_context": self._calculate_avg_score(event_scores, "context_score"),
        }

        logger.info(
            f"Garbled turn score calculated: {score:.2f} "
            f"(garbled_turn_rate: {garbled_turn_rate * 100:.1f}%, "
            f"{garbled_turns}/{total_turns} garbled) - {status.upper()}"
        )

        return TestScore(
            score=score,
            score_method=self.name,
            score_status=status,
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
        """Combine per-event scores from the 3 metrics.

        Matches events by event_id and combines their scores.
        Flags as garbled if ANY score ≤ 2 (on 1-5 scale, ≤ 0.25 on 0-1 scale).

        Args:
            intelligibility: Intelligibility metric result
            segmentation: Segmentation metric result
            context: Context metric result

        Returns:
            List of event score dictionaries with garbled flags
        """
        # Extract per-event results from metric details
        intell_events = self._extract_event_results(intelligibility)
        segment_events = self._extract_event_results(segmentation)
        context_events = self._extract_event_results(context)

        # Build event score map (keyed by event_id)
        event_map: Dict[str, Dict[str, Any]] = {}

        for event in intell_events:
            event_id = event.get("event_id")
            if not event_id:
                continue
            event_map[event_id] = {
                "event_id": event_id,
                "intelligibility_score": event.get("score_1_5", 1),
                "intelligibility_normalized": event.get("score_normalized", 0.0),
            }

        for event in segment_events:
            event_id = event.get("event_id")
            if event_id and event_id in event_map:
                event_map[event_id]["segmentation_score"] = event.get("score_1_5", 1)
                event_map[event_id]["segmentation_normalized"] = event.get("score_normalized", 0.0)

        for event in context_events:
            event_id = event.get("event_id")
            if event_id and event_id in event_map:
                event_map[event_id]["context_score"] = event.get("score_1_5", 1)
                event_map[event_id]["context_normalized"] = event.get("score_normalized", 0.0)

        # Calculate garbled flags
        event_scores = []
        for event_id, scores in event_map.items():
            # Check if all three scores are present
            if not all(
                key in scores
                for key in ["intelligibility_score", "segmentation_score", "context_score"]
            ):
                logger.warning(f"Event {event_id} missing some quality scores, skipping")
                continue

            intell = scores["intelligibility_score"]
            segment = scores["segmentation_score"]
            ctx = scores["context_score"]

            # Garbled if ANY score ≤ 2
            is_garbled = any(score <= 2 for score in [intell, segment, ctx])

            # Determine reason
            reason = None
            if is_garbled:
                low_scores = []
                if intell <= 2:
                    low_scores.append(f"intelligibility ({intell}/5)")
                if segment <= 2:
                    low_scores.append(f"segmentation ({segment}/5)")
                if ctx <= 2:
                    low_scores.append(f"context ({ctx}/5)")
                reason = f"Low scores: {', '.join(low_scores)}"

            event_scores.append({
                "event_id": event_id,
                "intelligibility_score": intell,
                "segmentation_score": segment,
                "context_score": ctx,
                "garbled": is_garbled,
                "reason": reason
            })

        return event_scores

    def _extract_event_results(self, metric_result: MetricResult) -> List[Dict[str, Any]]:
        """Extract per-event results from metric details.

        Args:
            metric_result: Metric result with details.results[]

        Returns:
            List of per-event result dictionaries
        """
        if not metric_result.details:
            return []

        results = metric_result.details.get("results", [])
        if not isinstance(results, list):
            return []

        # Filter to only "evaluated" status
        return [r for r in results if r.get("status") == "evaluated"]

    def _calculate_avg_score(self, event_scores: List[Dict[str, Any]], score_key: str) -> float:
        """Calculate average score across events.

        Args:
            event_scores: List of event score dictionaries
            score_key: Key to extract (e.g., "intelligibility_score")

        Returns:
            Average score (1-5 scale)
        """
        if not event_scores:
            return 0.0

        total = sum(e.get(score_key, 0) for e in event_scores)
        return round(total / len(event_scores), 2)


__all__ = ["GarbledTurnScoreCalculator"]

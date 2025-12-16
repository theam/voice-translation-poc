"""Average-based score calculator.

Calculates test score as percentage of metric scores.
This is the default calculator and matches the original behavior.
"""
from __future__ import annotations

import logging
from typing import List

from production.metrics.base import MetricResult

from .base import ScoreCalculator, TestScore


logger = logging.getLogger(__name__)


class AverageScoreCalculator(ScoreCalculator):
    """Calculate test score based on average of metric scores.

    Score calculation:
    - score = (sum of metric scores / total metrics) * 100
    - Metrics with None score are excluded from calculation

    This is the default scoring method.

    Example:
        Metrics with scores [0.8, 0.9, 0.75, 1.0]
        → average = 0.8625
        → score = 86.25
    """

    name = "average"

    def calculate(self, metric_results: List[MetricResult]) -> TestScore:
        """Calculate average-based test score.

        Args:
            metric_results: List of metric results from test execution

        Returns:
            TestScore with score (0-100)
        """
        if not metric_results:
            logger.warning("No metric results provided for scoring")
            return TestScore(
                score=0.0,
                score_method=self.name,
                details={"reason": "No metrics executed"}
            )

        # Collect metric scores (exclude None values)
        scores = [result.score for result in metric_results if result.score is not None]

        if not scores:
            logger.warning("No valid metric scores found")
            return TestScore(
                score=0.0,
                score_method=self.name,
                details={"reason": "No valid metric scores"}
            )

        # Calculate average score (already 0-100 inputs)
        average_score = sum(scores) / len(scores)
        score = average_score
        score = round(score, 2)

        # Build details
        details = {
            "total_metrics": len(metric_results),
            "scored_metrics": len(scores),
            "average_metric_score": round(average_score, 2),
            "individual_scores": [round(s, 2) for s in scores]
        }

        logger.info(
            f"Average score calculated: {score:.2f} "
            f"(average of {len(scores)} metric scores: {average_score:.2f})"
        )

        return TestScore(
            score=score,
            score_method=self.name,
            details=details
        )


__all__ = ["AverageScoreCalculator"]

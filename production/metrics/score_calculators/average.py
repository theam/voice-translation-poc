"""Average-based score calculator.

Calculates test score as percentage of passed metrics.
This is the default calculator and matches the original behavior.
"""
from __future__ import annotations

import logging
from typing import List

from production.metrics.base import MetricResult

from .base import ScoreCalculator, TestScore


logger = logging.getLogger(__name__)


class AverageScoreCalculator(ScoreCalculator):
    """Calculate test score based on percentage of passed metrics.

    Score calculation:
    - score = (passed_metrics / total_metrics) * 100
    - status = "success" if all metrics passed, "failed" otherwise

    This is the original/default scoring method.

    Example:
        8 metrics passed out of 10 total
        → score = 80.0
        → status = "failed" (not all passed)
    """

    name = "average"

    def calculate(self, metric_results: List[MetricResult]) -> TestScore:
        """Calculate average-based test score.

        Args:
            metric_results: List of metric results from test execution

        Returns:
            TestScore with score (0-100) and status ("success" or "failed")
        """
        if not metric_results:
            logger.warning("No metric results provided for scoring")
            return TestScore(
                score=0.0,
                score_method=self.name,
                score_status="failed",
                details={"reason": "No metrics executed"}
            )

        # Count passed metrics
        passed_count = sum(1 for result in metric_results if result.passed)
        total_count = len(metric_results)

        # Calculate percentage score
        score = (passed_count / total_count) * 100.0
        score = round(score, 2)

        # Determine status
        all_passed = (passed_count == total_count)
        status = "success" if all_passed else "failed"

        # Build details
        details = {
            "total_metrics": total_count,
            "passed_metrics": passed_count,
            "failed_metrics": total_count - passed_count,
            "all_passed": all_passed
        }

        logger.info(
            f"Average score calculated: {score:.2f} "
            f"({passed_count}/{total_count} metrics passed) - {status.upper()}"
        )

        return TestScore(
            score=score,
            score_method=self.name,
            score_status=status,
            details=details
        )


__all__ = ["AverageScoreCalculator"]

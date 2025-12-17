"""Calibration validation logic for comparing expected vs actual metric scores."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from production.storage.models import MetricData, Turn
from .models import CalibrationResult, CalibrationSummary

logger = logging.getLogger(__name__)


class CalibrationValidator:
    """Validates metric scores against expected values for calibration scenarios.

    Compares actual metric results against expected values defined in scenario
    YAML files to validate that metrics are working correctly.
    """

    def __init__(self, tolerance: float = 10.0):
        """Initialize validator.

        Args:
            tolerance: Default tolerance for metric validation (0-100 scale).
                      E.g., 10.0 = ±10 points. Comes from FrameworkConfig.calibration_tolerance
                      or can be overridden per-scenario via Scenario.tolerance.
        """
        self.tolerance = tolerance

    def validate_turn(
        self,
        turn: Turn,
        actual_metrics: Dict[str, MetricData],
        tolerance: Optional[float] = None,
    ) -> List[CalibrationResult]:
        """Validate turn-level metric expectations.

        Args:
            turn: Turn with metric expectations
            actual_metrics: Dictionary of actual metric results {metric_name: MetricData}
            tolerance: Optional custom tolerance override

        Returns:
            List of CalibrationResult for each expected metric
        """
        if not turn.metric_expectations:
            return []

        tol = tolerance if tolerance is not None else self.tolerance
        results = []

        for metric_name, expected_value in turn.metric_expectations.items():
            actual_metric = actual_metrics.get(metric_name)
            actual_value = actual_metric.score if actual_metric else None

            if actual_value is None:
                # Metric was not run or returned no value
                results.append(CalibrationResult(
                    metric_name=metric_name,
                    turn_id=turn.turn_id,
                    expected=expected_value,
                    actual=None,
                    delta=None,
                    within_tolerance=False,
                    tolerance=tol,
                    validation_level="turn",
                ))
                continue

            delta = actual_value - expected_value
            within_tolerance = abs(delta) <= tol

            results.append(CalibrationResult(
                metric_name=metric_name,
                turn_id=turn.turn_id,
                expected=expected_value,
                actual=actual_value,
                delta=delta,
                within_tolerance=within_tolerance,
                tolerance=tol,
                validation_level="turn",
            ))

        return results

    def validate_scenario(
        self,
        expected_score: Optional[float],
        actual_score: float,
        tolerance: Optional[float] = None,
    ) -> tuple[bool, Optional[float]]:
        """Validate overall scenario score.

        Args:
            expected_score: Expected overall test score (0-100 scale)
            actual_score: Actual test score (0-100 scale)
            tolerance: Optional custom tolerance override (0-100 scale).
                      If not provided, uses same tolerance as metrics.

        Returns:
            Tuple of (within_tolerance, delta)
        """
        if expected_score is None:
            return True, None

        # Use provided tolerance or same as metrics
        tol = tolerance if tolerance is not None else self.tolerance
        delta = actual_score - expected_score
        within_tolerance = abs(delta) <= tol

        return within_tolerance, delta

    def validate_test_run(
        self,
        test_id: str,
        turns: List[Turn],
        metrics_by_turn: Dict[str, Dict[str, MetricData]],
        conversation_metrics: Dict[str, MetricData] | None = None,
        expected_score: Optional[float] = None,
        actual_score: Optional[float] = None,
        metric_tolerance: Optional[float] = None,
        score_tolerance: Optional[float] = None,
    ) -> CalibrationSummary:
        """Validate an entire test run with all turns.

        Args:
            test_id: Test scenario ID
            turns: List of turns with expectations
            metrics_by_turn: Nested dict {turn_id: {metric_name: MetricData}}
            conversation_metrics: Dict of conversation-level metrics {metric_name: MetricData}
            expected_score: Expected overall test score (optional)
            actual_score: Actual overall test score (optional)
            metric_tolerance: Tolerance for individual metrics
            score_tolerance: Tolerance for overall score

        Returns:
            CalibrationSummary with all validation results
        """
        tol = metric_tolerance if metric_tolerance is not None else self.tolerance
        turn_results: List[CalibrationResult] = []
        conversation_result: CalibrationResult | None = None

        # Validate turn-level metric expectations
        for turn in turns:
            if not turn.metric_expectations:
                continue

            turn_metrics = metrics_by_turn.get(turn.turn_id, {})
            turn_results.extend(self.validate_turn(turn, turn_metrics, tol))

        # Validate conversation-level expectation using the same expected_score as scenario
        if expected_score is not None and conversation_metrics:
            conversation_result = self.validate_conversation_metrics(
                expected_score=expected_score,
                conversation_metrics=conversation_metrics,
                tolerance=tol,
            )

        # Validate scenario-level score expectation
        score_within_tolerance = True
        score_delta = None

        if expected_score is not None and actual_score is not None:
            score_within_tolerance, score_delta = self.validate_scenario(
                expected_score, actual_score, score_tolerance
            )

        return CalibrationSummary(
            test_id=test_id,
            turns=turn_results or [],
            conversation=conversation_result,
            expected_score=expected_score,
            actual_score=actual_score,
            score_delta=score_delta,
            score_within_tolerance=score_within_tolerance,
            score_tolerance=score_tolerance,
        )

    def validate_conversation_metrics(
        self,
        expected_score: float,
        conversation_metrics: Dict[str, MetricData],
        tolerance: Optional[float] = None,
    ) -> CalibrationResult | None:
        """Validate conversation-level metrics against expected score.

        Conversation-level metrics evaluate the entire conversation context
        rather than individual turns (e.g., context metric).

        Args:
            expected_score: Expected score (0-100 scale)
            conversation_metrics: Dict of conversation-level metrics
            tolerance: Optional tolerance override (0-100 scale)

        Returns:
            CalibrationResult with validation_level="conversation" or None
        """
        if not conversation_metrics:
            return None

        tol = tolerance if tolerance is not None else self.tolerance

        # Use the first available conversation metric deterministically
        for metric_name in sorted(conversation_metrics.keys()):
            metric_data = conversation_metrics[metric_name]
            conv_block = getattr(metric_data, "conversation", None)
            actual_value = conv_block.score if conv_block is not None else getattr(metric_data, "score", None)

            if actual_value is None:
                return CalibrationResult(
                    metric_name=metric_name,
                    turn_id=None,
                    expected=expected_score,
                    actual=None,
                    delta=None,
                    within_tolerance=False,
                    tolerance=tol,
                    validation_level="conversation",
                )

            delta = actual_value - expected_score
            within_tolerance = abs(delta) <= tol
            return CalibrationResult(
                metric_name=metric_name,
                turn_id=None,
                expected=expected_score,
                actual=actual_value,
                delta=delta,
                within_tolerance=within_tolerance,
                tolerance=tol,
                validation_level="conversation",
            )

        return None


__all__ = ["CalibrationValidator", "CalibrationResult", "CalibrationSummary"]

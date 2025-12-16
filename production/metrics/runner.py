"""Metrics runner for executing and reporting metrics results."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from bson import ObjectId

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Scenario

from .base import Metric, MetricResult

if TYPE_CHECKING:
    from production.storage.service import MetricsStorageService

logger = logging.getLogger(__name__)


@dataclass
class MetricsSummary:
    """Aggregated metrics results for a scenario."""

    status: str
    results: List[MetricResult] = field(default_factory=list)
    score: Optional[float] = None  # Overall test score (0-100)
    score_method: Optional[str] = None  # Calculator used


class MetricsRunner:
    """Executes metrics and logs execution progress.

    Provides centralized metrics execution with:
    - Execution logging (start/complete for each metric)
    - Result logging (pass/fail with scores)
    - Summary generation
    - Error handling

    Example:
        >>> runner = MetricsRunner(expectations, events)
        >>> summary = runner.run()
        >>> print(f"Status: {summary.status}")
    """

    def __init__(
        self,
        scenario: Scenario,
        conversation_manager: ConversationManager,
        metrics: Optional[List[Metric]] = None,
        storage_service: Optional[MetricsStorageService] = None,
        evaluation_run_id: Optional[ObjectId] = None,
        test_id: Optional[str] = None,
        test_name: Optional[str] = None,
        started_at: Optional[datetime] = None,
        score_method: str = "average",
        tolerance: Optional[float] = None,
    ) -> None:
        """Initialize metrics runner.

        Args:
            scenario: Scenario with turns and expectations
            conversation_manager: Conversation manager with collected events
            metrics: List of metrics to run (if None, uses get_metrics())
            storage_service: Optional storage service for persistence
            evaluation_run_id: Optional evaluation run ID for test result linkage
            test_id: Optional test identifier (scenario.id)
            test_name: Optional test name (scenario.description)
            started_at: Optional test start timestamp
            score_method: Score calculator method ("average" or "garbled_turn")
        """
        self.scenario = scenario
        self.conversation_manager = conversation_manager
        self._metrics = metrics
        self.storage_service = storage_service
        self.evaluation_run_id = evaluation_run_id
        self.test_id = test_id
        self.test_name = test_name
        self.started_at = started_at or datetime.utcnow()
        self.score_method = score_method
        self.finished_at: Optional[datetime] = None
        self.metric_tolerance = tolerance

    @property
    def metrics(self) -> List[Metric]:
        """Get metrics to run (lazy-loads if not provided)."""
        if self._metrics is None:
            # Import here to avoid circular dependency
            from . import get_metrics
            self._metrics = get_metrics(self.scenario, self.conversation_manager)
        return self._metrics

    def run(self) -> MetricsSummary:
        """Execute all metrics with logging and error handling.

        Returns:
            MetricsSummary with aggregated results
        """
        logger.info(f"Starting metrics execution ({len(self.metrics)} metrics)")
        # Log conversation summary
        self.conversation_manager.log_turns_summary()

        results = []

        for metric in self.metrics:
            result = self._run_single_metric(metric)
            results.append(result)

        # Log overall summary
        total_count = len(results)
        scored_count = sum(1 for r in results if r.score is not None)

        if scored_count > 0:
            avg_score = sum(r.score for r in results if r.score is not None) / scored_count
            logger.info(
                f"Metrics execution complete: {total_count} metrics, "
                f"{scored_count} scored (average: {avg_score:.2f})"
            )
            status = "completed"
        else:
            logger.warning("Metrics execution complete: No metrics scored")
            status = "no_scores"

        # Calculate overall test score using configured calculator
        from production.metrics.score_calculators import get_score_calculator

        calculator = get_score_calculator(self.score_method)
        test_score = calculator.calculate(results)
        logger.info(
            f"Test score calculated: {test_score.score:.2f} "
            f"(method: {test_score.score_method})"
        )

        self.finished_at = datetime.utcnow()
        summary = MetricsSummary(
            status=status,
            results=results,
            score=test_score.score,
            score_method=test_score.score_method,
        )

        return summary

    async def run_and_persist(
        self,
        tags: Optional[List[str]] = None,
        participants: Optional[List[str]] = None
    ) -> MetricsSummary:
        """Execute metrics and persist to storage if configured.

        Runs all metrics synchronously, then persists the results to MongoDB
        if storage service is configured. Falls back to run() if storage is
        not configured.

        Args:
            tags: Test tags for metadata (from scenario.tags)
            participants: Participant names for metadata (from scenario.participants)

        Returns:
            MetricsSummary with aggregated results

        Example:
            >>> from production.storage import MongoDBClient, MetricsStorageService
            >>> client = MongoDBClient("mongodb://localhost:27017", "metrics")
            >>> service = MetricsStorageService(client)
            >>> evaluation_id = ObjectId()
            >>>
            >>> runner = MetricsRunner(
            ...     expectations,
            ...     events,
            ...     storage_service=service,
            ...     evaluation_run_id=evaluation_id,
            ...     test_id="test-001",
            ...     test_name="Test 1",
            ...     started_at=datetime.utcnow()
            ... )
            >>> summary = await runner.run_and_persist(tags=["medical"], participants=["doctor"])
        """
        # Run metrics (existing synchronous logic)
        summary = self.run()

        # Persist if storage is configured
        if self.storage_service and self.evaluation_run_id and self.test_id:
            await self._persist_test_result(summary, tags or [], participants or [])
        else:
            if self.storage_service:
                logger.debug("Storage service configured but missing evaluation_run_id or test_id")

        return summary

    async def _persist_test_result(
        self,
        summary: MetricsSummary,
        tags: List[str],
        participants: List[str]
    ) -> None:
        """Persist test run to storage.

        Converts MetricsSummary to TestRun model and saves to MongoDB.

        Args:
            summary: Metrics summary to persist
            tags: Test tags for metadata
            participants: Participant names for metadata
        """
        from production.storage.models import MetricData, TestRun, Turn
        from production.storage.utils import generate_test_run_id

        finished_at = self.finished_at or datetime.utcnow()
        duration_ms = int((finished_at - self.started_at).total_seconds() * 1000)

        # Generate test_run_id
        # We don't have access to evaluation_run_id string here, only ObjectId
        # So we'll generate without it for now
        test_run_id = generate_test_run_id(
            timestamp=self.started_at,
            test_id=self.test_id
        )

        # Convert MetricResults to MetricData
        metrics_dict = {}
        for result in summary.results:
            # Map expected scores per turn for this metric from scenario expectations
            expected_scores_by_turn = {
                turn.id: turn.metric_expectations[result.metric_name]
                for turn in self.scenario.turns
                if result.metric_name in turn.metric_expectations
            }
            metrics_dict[result.metric_name] = MetricData.from_metric_result(
                result,
                expected_scores_by_turn=expected_scores_by_turn or None,
            )

        # Convert conversation turns to storage format with scenario expectations
        turns = []
        # Create a lookup for scenario turns by ID
        scenario_turns_by_id = {turn.id: turn for turn in self.scenario.turns}

        for turn_summary in self.conversation_manager.iter_turns():
            # Get corresponding scenario turn for expected values
            scenario_turn = scenario_turns_by_id.get(turn_summary.turn_id)

            turn = Turn(
                turn_id=turn_summary.turn_id,
                start_ms=turn_summary.turn_start_ms or 0,
                end_ms=turn_summary.turn_end_ms,
                source_text=scenario_turn.source_text if scenario_turn else None,
                translated_text=turn_summary.translation_text(),
                # Add expected values from scenario
                expected_text=scenario_turn.expected_text if scenario_turn else None,
                source_language=scenario_turn.source_language if scenario_turn else None,
                expected_language=scenario_turn.expected_language if scenario_turn else None,
                # Add metric expectations for calibration validation
                metric_expectations=scenario_turn.metric_expectations if scenario_turn else {},
            )
            turns.append(turn)

        # Create TestRun
        test_run = TestRun(
            evaluation_run_id=self.evaluation_run_id,
            test_run_id=test_run_id,
            test_id=self.test_id,
            test_name=self.test_name or self.test_id,
            started_at=self.started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            metrics=metrics_dict,
            turns=turns,
            score=summary.score or 0.0,
            score_method=summary.score_method or self.score_method,
            tags=tags,
            participants=participants,
            scenario_metrics=self.scenario.metrics,
            expected_score=self.scenario.expected_score,
            tolerance=self.metric_tolerance,
        )

        # Persist to MongoDB
        await self.storage_service.create_test_run(test_run)

    def _run_single_metric(self, metric: Metric) -> MetricResult:
        """Run a single metric with logging and error handling.

        Args:
            metric: Metric to execute

        Returns:
            MetricResult from metric execution
        """
        metric_name = metric.name

        # Log execution start
        logger.info(f"Executing metric: {metric_name}")

        try:
            # Run metric
            result = metric.run()

            # Log completion with result
            self._log_metric_result(metric_name, result)

            return result

        except Exception as e:
            # Handle unexpected errors
            logger.error(f"Metric {metric_name} failed with error: {e}", exc_info=True)

            return MetricResult(
                metric_name=metric_name,
                score=0.0,
                details={"error": str(e), "error_type": type(e).__name__}
            )

    def _calculate_test_score(self, summary: MetricsSummary) -> float:
        """Calculate overall test score from metrics.

        Uses average of metric scores (already on 0-100 scale):
        - Averages all metric scores (0-100)
        - Excludes metrics with None scores

        Args:
            summary: MetricsSummary containing all metric results

        Returns:
            Score from 0-100 (average of metric scores)

        Note:
            This is now handled by score calculators. This method is
            deprecated but kept for compatibility.
        """
        if not summary.results:
            return 0.0

        # Collect metric scores (exclude None values)
        scores = [result.score for result in summary.results if result.score is not None]

        if not scores:
            return 0.0

        # Calculate average score (scores already 0-100)
        average_score = sum(scores) / len(scores)
        score = average_score

        return round(score, 2)

    def _log_metric_result(self, metric_name: str, result: MetricResult) -> None:
        """Log metric result with detailed information.

        Args:
            metric_name: Name of the metric
            result: Metric result to log
        """
        # Build result message
        if result.score is not None:
            # Metrics with numeric scores (0-100)
            score_str = f"{result.score:.2f}"
            message = f"Metric completed: {metric_name} (score: {score_str})"
        else:
            # Metrics without scores
            message = f"Metric completed: {metric_name} (no score)"

        # Log the result
        logger.info(message)


__all__ = ["MetricsRunner", "MetricsSummary"]

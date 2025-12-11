"""Metrics runner for executing and reporting metrics results."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from bson import ObjectId

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Expectations

from .base import Metric, MetricResult

if TYPE_CHECKING:
    from production.storage.service import MetricsStorageService

logger = logging.getLogger(__name__)


@dataclass
class MetricsSummary:
    """Aggregated metrics results for a scenario."""

    status: str
    results: List[MetricResult] = field(default_factory=list)


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
        expectations: Expectations,
        conversation_manager: ConversationManager,
        metrics: List[Metric] | None = None,
        storage_service: Optional[MetricsStorageService] = None,
        evaluation_run_id: Optional[ObjectId] = None,
        test_id: Optional[str] = None,
        test_name: Optional[str] = None,
        started_at: Optional[datetime] = None,
        score_method: str = "average"
    ) -> None:
        """Initialize metrics runner.

        Args:
            expectations: Scenario expectations
            events: Collected events from scenario execution
            metrics: List of metrics to run (if None, uses get_metrics())
            storage_service: Optional storage service for persistence
            evaluation_run_id: Optional evaluation run ID for test result linkage
            test_id: Optional test identifier (scenario.id)
            test_name: Optional test name (scenario.description)
            started_at: Optional test start timestamp
            score_method: Score calculator method ("average" or "garbled_turn")
        """
        self.expectations = expectations
        self.conversation_manager = conversation_manager
        self._metrics = metrics
        self.storage_service = storage_service
        self.evaluation_run_id = evaluation_run_id
        self.test_id = test_id
        self.test_name = test_name
        self.started_at = started_at or datetime.utcnow()
        self.score_method = score_method

    @property
    def metrics(self) -> List[Metric]:
        """Get metrics to run (lazy-loads if not provided)."""
        if self._metrics is None:
            # Import here to avoid circular dependency
            from . import get_metrics
            self._metrics = get_metrics(self.expectations, self.conversation_manager)
        return self._metrics

    def run(self) -> MetricsSummary:
        """Execute all metrics with logging and error handling.

        Returns:
            MetricsSummary with aggregated results
        """
        logger.info(f"Starting metrics execution ({len(self.metrics)} metrics)")
        # Log conversation summary
        turns_summary = self.conversation_manager.get_turns_summary()
        logger.info(f"Conversation turns to evaluate: {len(turns_summary)}")
        for turn_info in turns_summary:
            logger.info(f"  Turn '{turn_info['turn_id']}'({turn_info['start_ms']}): {turn_info['translation_text']}")

        results = []
        all_passed = True

        for metric in self.metrics:
            result = self._run_single_metric(metric)
            results.append(result)

            if not result.passed:
                all_passed = False

        # Log overall summary
        status = "passed" if all_passed else "failed"
        passed_count = sum(1 for r in results if r.passed)
        total_count = len(results)

        logger.info(
            f"Metrics execution complete: {status.upper()} "
            f"({passed_count}/{total_count} passed)"
        )

        return MetricsSummary(status=status, results=results)

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
        from production.metrics.score_calculators import get_score_calculator
        from production.storage.models import MetricData, TestRun
        from production.storage.utils import generate_test_run_id

        finished_at = datetime.utcnow()
        duration_ms = int((finished_at - self.started_at).total_seconds() * 1000)

        # Generate test_run_id
        # We don't have access to evaluation_run_id string here, only ObjectId
        # So we'll generate without it for now
        test_run_id = generate_test_run_id(
            timestamp=self.started_at,
            test_id=self.test_id
        )

        # Convert MetricResults to MetricData
        metrics_dict = {
            result.metric_name: MetricData.from_metric_result(result)
            for result in summary.results
        }

        # Calculate overall test score using configured calculator
        calculator = get_score_calculator(self.score_method)
        test_score = calculator.calculate(summary.results)

        logger.info(
            f"Test score calculated: {test_score.score:.2f} "
            f"(method: {test_score.score_method}, status: {test_score.score_status})"
        )

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
            score=test_score.score,
            score_method=test_score.score_method,
            score_status=test_score.score_status,
            tags=tags,
            participants=participants
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
                passed=False,
                value=0.0,
                reason=f"Metric execution failed: {str(e)}",
                details={"error": str(e), "error_type": type(e).__name__}
            )

    def _calculate_test_score(self, summary: MetricsSummary) -> float:
        """Calculate overall test score from metrics.

        Currently uses a simple percentage-based calculation:
        - Counts the number of passed metrics
        - Returns percentage as a score from 0-100

        Args:
            summary: MetricsSummary containing all metric results

        Returns:
            Score from 0-100 (0 = all failed, 100 = all passed)

        Note:
            This is a basic implementation. The scoring algorithm can be
            enhanced to use weighted averages, metric values, or other
            sophisticated calculations based on business requirements.
        """
        if not summary.results:
            return 0.0

        # Count passed metrics
        passed_count = sum(1 for result in summary.results if result.passed)
        total_count = len(summary.results)

        # Calculate percentage score
        score = (passed_count / total_count) * 100.0

        return round(score, 2)

    def _log_metric_result(self, metric_name: str, result: MetricResult) -> None:
        """Log metric result with detailed information.

        Args:
            metric_name: Name of the metric
            result: Metric result to log
        """
        status = "PASSED" if result.passed else "FAILED"

        # Build result message
        if result.value is not None:
            # Metrics with numeric scores
            score_str = f"{result.value:.2%}" if 0 <= result.value <= 1 else f"{result.value:.2f}"
            message = f"Metric completed: {metric_name} - {status} (score: {score_str})"
        else:
            # Metrics without scores (e.g., sequence validation)
            message = f"Metric completed: {metric_name} - {status}"

        # Add failure reason if present
        if not result.passed and result.reason:
            message += f" - {result.reason}"

        # Log at appropriate level
        if result.passed:
            logger.info(message)
        else:
            logger.warning(message)


__all__ = ["MetricsRunner", "MetricsSummary"]

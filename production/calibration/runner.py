"""Calibration runner for executing metrics on calibration cases."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from production.capture.collector import CollectedEvent
from production.metrics import get_metrics
from production.metrics.base import Metric, MetricResult
from production.scenario_engine.models import Expectations, TranscriptExpectation
from production.services.llm_service import LLMService
from production.storage.models import CalibrationCaseResult, CalibrationRun

from .models import (
    CalibrationCase,
    CalibrationConfig,
    CalibrationResult,
    CalibrationSummary,
)


logger = logging.getLogger(__name__)


class CalibrationRunner:
    """Execute metrics on calibration cases and compare with expected scores.

    Converts calibration cases to mock events/expectations, runs metrics,
    and compares actual vs expected scores within tolerance.

    Example:
        >>> runner = CalibrationRunner(tolerance=0.5)
        >>> summary = runner.run_calibration(config)
        >>> print(f"Accuracy: {summary.accuracy:.1%}")
    """

    def __init__(
        self,
        tolerance: float = 0.5,
        llm_config: Optional[Dict] = None
    ):
        """Initialize calibration runner.

        Args:
            tolerance: Acceptable score difference (default: 0.5 on 1-5 scale)
            llm_config: Optional LLM configuration override
        """
        self.tolerance = tolerance
        self.llm_config = llm_config

    def run_calibration(
        self,
        config: CalibrationConfig
    ) -> CalibrationSummary:
        """Run calibration for all cases in config.

        Args:
            config: Calibration configuration with test cases

        Returns:
            CalibrationSummary with results for all cases
        """
        logger.info(
            f"Starting calibration: {config.id} ({len(config.calibration_cases)} cases)"
        )

        if not config.calibration_cases:
            logger.warning(f"No calibration cases in {config.id}")
            return CalibrationSummary(
                config_id=config.id,
                config_description=config.description,
                metric_name=config.metric,
                total_cases=0,
                passed_cases=0,
                failed_cases=0,
                avg_score_diff=0.0,
                max_score_diff=0.0,
                accuracy=0.0,
                results=[],
                timestamp=datetime.utcnow(),
                tolerance=self.tolerance
            )

        # Use config's LLM settings if provided, otherwise use runner's
        llm_config = config.llm_config or self.llm_config

        results = []
        for case in config.calibration_cases:
            try:
                result = self._run_single_case(case, config.metric, llm_config)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to run case {case.id}: {e}", exc_info=True)
                # Create failure result
                results.append(
                    CalibrationResult(
                        case_id=case.id,
                        case_description=case.description,
                        metric_name=config.metric,
                        actual_score=0.0,
                        expected_score=0.0,
                        score_diff=0.0,
                        score_diff_percentage=0.0,
                        passed=False,
                        actual_reasoning=f"Error: {str(e)}",
                        expected_reasoning=case.expected_reasoning,
                        tolerance=self.tolerance,
                        text_evaluated=case.text
                    )
                )

        # Calculate summary statistics
        passed_cases = sum(1 for r in results if r.passed)
        failed_cases = len(results) - passed_cases
        avg_score_diff = sum(r.score_diff for r in results) / len(results) if results else 0.0
        max_score_diff = max((r.score_diff for r in results), default=0.0)
        accuracy = passed_cases / len(results) if results else 0.0

        # Extract LLM model from first result (if available)
        llm_model = None
        for r in results:
            if r.actual_reasoning:
                # Try to extract from llm_config or use default
                llm_model = (llm_config or {}).get("model", "gpt-4o-mini")
                break

        summary = CalibrationSummary(
            config_id=config.id,
            config_description=config.description,
            metric_name=config.metric,
            total_cases=len(results),
            passed_cases=passed_cases,
            failed_cases=failed_cases,
            avg_score_diff=round(avg_score_diff, 3),
            max_score_diff=round(max_score_diff, 3),
            accuracy=accuracy,
            results=results,
            timestamp=datetime.utcnow(),
            llm_model=llm_model,
            tolerance=self.tolerance
        )

        logger.info(
            f"Calibration complete: {config.id} - "
            f"{passed_cases}/{len(results)} passed ({accuracy:.1%})"
        )

        return summary

    def _run_single_case(
        self,
        case: CalibrationCase,
        metric_name: str,
        llm_config: Optional[Dict]
    ) -> CalibrationResult:
        """Execute metric on single calibration case.

        Args:
            case: Calibration case to evaluate
            metric_name: Name of metric to run
            llm_config: Optional LLM configuration

        Returns:
            CalibrationResult with comparison
        """
        logger.debug(f"Running case: {case.id}")

        # Convert case to events and expectations
        events = self._create_mock_events(case)
        expectations = self._create_expectations(case)

        # Get metric instance
        metric = self._get_metric_instance(metric_name, expectations, events, llm_config)

        # Run metric
        metric_result = metric.run()

        # Extract actual score
        actual_score, actual_reasoning = self._extract_score_from_result(
            metric_result,
            metric_name
        )

        # Get expected score (try normalized first, fallback to 1-5)
        expected_score = self._get_expected_score(case, metric_name)

        # Calculate difference
        score_diff = abs(actual_score - expected_score)

        # Calculate percentage difference (based on scale)
        if metric_name in ["intelligibility", "segmentation", "context"]:
            # 1-5 scale converted to 0-1: max diff is 1.0
            score_diff_percentage = score_diff * 100.0
        else:
            # 0-1 scale: already percentage
            score_diff_percentage = score_diff * 100.0

        # Determine if passed (within tolerance)
        passed = score_diff <= self.tolerance

        return CalibrationResult(
            case_id=case.id,
            case_description=case.description,
            metric_name=metric_name,
            actual_score=round(actual_score, 3),
            expected_score=round(expected_score, 3),
            score_diff=round(score_diff, 3),
            score_diff_percentage=round(score_diff_percentage, 1),
            passed=passed,
            actual_reasoning=actual_reasoning,
            expected_reasoning=case.expected_reasoning,
            tolerance=self.tolerance,
            text_evaluated=case.text
        )

    def _create_mock_events(self, case: CalibrationCase) -> List[CollectedEvent]:
        """Convert calibration case to CollectedEvents.

        Args:
            case: Calibration case

        Returns:
            List of mock CollectedEvent objects
        """
        events = []

        # Add conversation history events (for context metric)
        for turn in case.conversation_history:
            events.append(
                CollectedEvent(
                    event_type="translated_text",
                    timestamp_ms=turn.timestamp_ms,
                    participant_id=turn.participant_id,
                    source_language=turn.source_language,
                    target_language=turn.target_language,
                    text=turn.text,
                    raw={"event_id": turn.participant_id}
                )
            )

        # Add current turn event
        events.append(
            CollectedEvent(
                event_type="translated_text",
                timestamp_ms=case.metadata.get("timestamp_ms", 1000),
                participant_id=case.metadata.get("participant_id", "test"),
                source_language=case.metadata.get("source_language"),
                target_language=case.metadata.get("target_language"),
                text=case.text,
                raw={"event_id": case.metadata.get("participant_id", "test")}
            )
        )

        return events

    def _create_expectations(self, case: CalibrationCase) -> Expectations:
        """Create Expectations from calibration case.

        Args:
            case: Calibration case

        Returns:
            Expectations object
        """
        expectation = TranscriptExpectation(
            id=case.id,
            event_id=case.metadata.get("participant_id", "test"),
            source_language=case.metadata.get("source_language", "en-US"),
            target_language=case.metadata.get("target_language", "es-ES"),
            expected_text=case.expected_text  # May be None
        )

        return Expectations(transcripts=[expectation])

    def _get_metric_instance(
        self,
        metric_name: str,
        expectations: Expectations,
        events: List[CollectedEvent],
        llm_config: Optional[Dict]
    ) -> Metric:
        """Get metric instance by name.

        Args:
            metric_name: Name of metric
            expectations: Expectations object
            events: List of events
            llm_config: Optional LLM configuration

        Returns:
            Metric instance
        """
        # Import metric classes
        from production.metrics import (
            ContextMetric,
            IntelligibilityMetric,
            SegmentationMetric,
            WERMetric,
            TechnicalTermsMetric,
            CompletenessMetric,
            IntentPreservationMetric,
            LanguageCorrectnessMetric,
        )

        # Map metric name to class
        metric_map = {
            "intelligibility": IntelligibilityMetric,
            "segmentation": SegmentationMetric,
            "context": ContextMetric,
            "wer": WERMetric,
            "technical_terms": TechnicalTermsMetric,
            "completeness": CompletenessMetric,
            "intent_preservation": IntentPreservationMetric,
            "language_correctness": LanguageCorrectnessMetric,
        }

        metric_class = metric_map.get(metric_name)
        if not metric_class:
            raise ValueError(f"Unknown metric: {metric_name}")

        # Instantiate with optional model override
        kwargs = {"expectations": expectations, "events": events}
        if llm_config and hasattr(metric_class, "__init__"):
            # Add model parameter if metric supports it
            if "model" in llm_config:
                kwargs["model"] = llm_config["model"]

        return metric_class(**kwargs)

    def _extract_score_from_result(
        self,
        metric_result: MetricResult,
        metric_name: str
    ) -> tuple[float, Optional[str]]:
        """Extract score and reasoning from metric result.

        Args:
            metric_result: Result from metric execution
            metric_name: Name of metric

        Returns:
            Tuple of (score, reasoning)
        """
        # For most metrics, the value field contains the normalized score (0-1)
        score = metric_result.value if metric_result.value is not None else 0.0

        # Extract reasoning from details if available
        reasoning = None
        if metric_result.details and "results" in metric_result.details:
            results = metric_result.details["results"]
            if results and len(results) > 0:
                first_result = results[0]
                reasoning = first_result.get("reasoning")

        return score, reasoning

    def _get_expected_score(self, case: CalibrationCase, metric_name: str) -> float:
        """Get expected score from calibration case.

        Args:
            case: Calibration case
            metric_name: Name of metric

        Returns:
            Expected score (normalized 0-1)
        """
        # Try normalized score first
        normalized_key = f"{metric_name}_normalized"
        if normalized_key in case.expected_scores:
            return case.expected_scores[normalized_key]

        # Try 1-5 scale and convert
        scale_1_5_key = f"{metric_name}_1_5"
        if scale_1_5_key in case.expected_scores:
            score_1_5 = case.expected_scores[scale_1_5_key]
            return (score_1_5 - 1) / 4  # Convert to 0-1

        # Try metric name directly
        if metric_name in case.expected_scores:
            return case.expected_scores[metric_name]

        # Fallback
        logger.warning(
            f"No expected score found for {metric_name} in case {case.id}. "
            f"Available keys: {list(case.expected_scores.keys())}"
        )
        return 0.0

    @staticmethod
    def create_calibration_run(
        summary: CalibrationSummary,
        config: CalibrationConfig,
        started_at: datetime,
        finished_at: datetime,
        git_commit: Optional[str] = None,
        git_branch: Optional[str] = None
    ) -> CalibrationRun:
        """Convert CalibrationSummary to CalibrationRun for storage.

        Args:
            summary: Calibration summary from run_calibration()
            config: Original calibration config
            started_at: Run start timestamp
            finished_at: Run finish timestamp
            git_commit: Git commit hash
            git_branch: Git branch name

        Returns:
            CalibrationRun ready for MongoDB storage
        """
        # Convert CalibrationResults to CalibrationCaseResults
        case_results = []
        for result in summary.results:
            case_results.append(
                CalibrationCaseResult(
                    case_id=result.case_id,
                    case_description=result.case_description,
                    text=result.text_evaluated,
                    expected_score=result.expected_score,
                    actual_score=result.actual_score,
                    difference=result.score_diff,
                    passed=result.passed,
                    reasoning=result.actual_reasoning,
                    metadata={}
                )
            )

        # Calculate duration in milliseconds
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        # Generate run ID
        calibration_run_id = f"{started_at.strftime('%Y-%m-%dT%H-%M-%SZ')}-{config.metric}"

        return CalibrationRun(
            calibration_run_id=calibration_run_id,
            config_id=config.id,
            metric=config.metric,
            version=config.version,
            description=config.description,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            tolerance=summary.tolerance,
            accuracy=summary.accuracy,
            total_cases=summary.total_cases,
            passed_cases=summary.passed_cases,
            failed_cases=summary.failed_cases,
            results=case_results,
            git_commit=git_commit,
            git_branch=git_branch,
            model=summary.llm_model
        )


__all__ = ["CalibrationRunner"]

"""Reporting service for generating PDF reports from database data."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from bson import ObjectId

from production.storage import MetricsStorageService
from production.storage.models import MetricData, Turn
from production.calibration import CalibrationResult, CalibrationSummary, CalibrationValidator

from .models import EvaluationRunData, TestReportData
from .calibration_pdf_generator import CalibrationReportPdfGenerator
from .evaluation_pdf_generator import EvaluationReportPdfGenerator

if TYPE_CHECKING:
    from production.storage.models import EvaluationRun, TestRun

logger = logging.getLogger(__name__)


class ReportingService:
    """Service for generating PDF reports from database data.

    Provides a clean API to generate evaluation run reports by fetching
    all necessary data from MongoDB and generating comprehensive PDF reports.
    """

    def __init__(
        self,
        storage_service: MetricsStorageService,
        output_dir: Optional[Path] = None,
    ) -> None:
        """Initialize reporting service.

        Args:
            storage_service: MongoDB storage service for data access
            output_dir: Optional custom output directory for PDF reports
        """
        self.storage_service = storage_service
        self.evaluation_pdf_generator = EvaluationReportPdfGenerator(output_dir=output_dir)
        self.calibration_pdf_generator = CalibrationReportPdfGenerator(output_dir=output_dir)

    async def generate_evaluation_report(
        self,
        evaluation_run_id: ObjectId,
    ) -> Path:
        """Generate PDF report for an evaluation run.

        Fetches all data from MongoDB and generates a comprehensive PDF report
        including evaluation summary and all test results.

        Args:
            evaluation_run_id: MongoDB ObjectId of the evaluation run

        Returns:
            Path to the generated PDF file

        Raises:
            ValueError: If evaluation run not found
            RuntimeError: If report generation fails
        """
        logger.info(f"Generating report for evaluation run: {evaluation_run_id}")

        # Fetch evaluation run data
        eval_run = await self.storage_service.get_evaluation_run_by_object_id(
            evaluation_run_id
        )
        if not eval_run:
            raise ValueError(f"Evaluation run not found: {evaluation_run_id}")

        # Detect if this is a calibration run
        is_calibration = eval_run.is_calibration()

        # Fetch all test runs for this evaluation
        test_runs = await self.storage_service.get_test_runs_for_evaluation(
            evaluation_run_id
        )

        # Build evaluation run data model
        evaluation_data = self._build_evaluation_data(
            eval_run, evaluation_run_id
        )

        # Build test report data models
        test_reports = [
            self._build_test_report_data(test_run) for test_run in test_runs
        ]

        # Generate PDF
        try:
            if is_calibration:
                report_path = self.calibration_pdf_generator.generate(
                    evaluation_data, test_reports
                )
            else:
                report_path = self.evaluation_pdf_generator.generate(
                    evaluation_data, test_reports
                )
            logger.info(f"Report generated successfully: {report_path}")
            return report_path
        except Exception as e:
            logger.error(f"Failed to generate PDF report: {e}", exc_info=True)
            raise RuntimeError(f"Report generation failed: {e}") from e

    async def generate_report(self, evaluation_run_id: ObjectId) -> Path:
        """Generate a report for an evaluation run (evaluation or calibration).

        Args:
            evaluation_run_id: MongoDB ObjectId of the evaluation run

        Returns:
            Path to the generated PDF file
        """
        # Reuse the existing flow to fetch data and choose the right generator
        eval_run = await self.storage_service.get_evaluation_run_by_object_id(
            evaluation_run_id
        )
        if not eval_run:
            raise ValueError(f"Evaluation run not found: {evaluation_run_id}")

        # Decide which generator to use based on calibration flag
        is_calibration = eval_run.is_calibration()

        test_runs = await self.storage_service.get_test_runs_for_evaluation(
            evaluation_run_id
        )

        evaluation_data = self._build_evaluation_data(
            eval_run, evaluation_run_id
        )
        test_reports = [
            self._build_test_report_data(test_run) for test_run in test_runs
        ]

        generator = (
            CalibrationReportPdfGenerator(output_dir=self.calibration_pdf_generator.output_dir)
            if is_calibration
            else EvaluationReportPdfGenerator(output_dir=self.evaluation_pdf_generator.output_dir)
        )
        try:
            report_path = generator.generate(evaluation_data, test_reports)
            logger.info(f"Report generated successfully. Calibration: {is_calibration} path: {report_path}")
            return report_path
        except Exception as e:
            logger.error(f"Failed to generate PDF report: {e}", exc_info=True)
            raise RuntimeError(f"Report generation failed: {e}") from e

    def _build_evaluation_data(
        self, eval_run: "EvaluationRun", evaluation_run_id: ObjectId
    ) -> EvaluationRunData:
        """Build EvaluationRunData from EvaluationRun model."""
        return EvaluationRunData(
            evaluation_run_id=eval_run.evaluation_run_id,
            started_at=eval_run.started_at,
            finished_at=eval_run.finished_at,
            git_commit=eval_run.git_commit,
            git_branch=eval_run.git_branch,
            environment=eval_run.environment,
            target_system=eval_run.target_system,
            score=eval_run.score,
            num_tests=eval_run.num_tests,
            aggregated_metrics=eval_run.metrics,
            system_info_hash=eval_run.system_info_hash,
            experiment_tags=eval_run.experiment_tags,
            calibration_status=eval_run.calibration_status,
        )

    def _build_test_report_data(self, test_run: "TestRun") -> TestReportData:
        """Build TestReportData from TestRun model."""
        # Compute or load calibration summary if this is a calibration test
        calibration_summary = None
        tolerance = getattr(test_run, "tolerance", None)
        if test_run.calibration_summary:
            calibration_summary = self._calibration_summary_from_dict(test_run.calibration_summary)
        elif test_run.expected_score is not None or any(turn.metric_expectations for turn in test_run.turns):
            calibration_summary = self._compute_calibration_summary(
                test_run.test_id,
                test_run.turns,
                test_run.metrics,
                test_run.expected_score,
                test_run.score,
                tolerance=tolerance,
            )

        return TestReportData(
            test_id=test_run.test_id,
            test_name=test_run.test_name,
            test_run_id=test_run.test_run_id,
            started_at=test_run.started_at,
            finished_at=test_run.finished_at,
            duration_ms=test_run.duration_ms,
            score=test_run.score,
            score_method=test_run.score_method,
            metrics=test_run.metrics,
            turns=test_run.turns,
            scenario_metrics=test_run.scenario_metrics,
            expected_score=test_run.expected_score,
            tolerance=tolerance,
            calibration_summary=calibration_summary,
        )

    def _compute_calibration_summary(
        self,
        test_id: str,
        turns: list[Turn],
        metrics: dict[str, MetricData],
        expected_score: Optional[float],
        actual_score: float,
        tolerance: Optional[float] = None,
    ):
        """Compute calibration validation summary from stored test data.

        Args:
            test_id: Test scenario ID
            turns: List of turns with metric expectations
            metrics: Dictionary of metric results {metric_name: MetricData}
            expected_score: Expected overall score (if defined)
            actual_score: Actual test score

        Returns:
            CalibrationSummary with validation results
        """
        tol = tolerance if tolerance is not None else 0.1
        score_tol = self._score_tolerance_from_metric_tol(tol)
        validator = CalibrationValidator(tolerance=tol)

        # Build metrics_by_turn structure needed by validator
        # For now, we'll apply all metrics to each turn that has expectations
        # This is a simplification - in reality, metrics may be turn-specific
        metrics_by_turn: Dict[str, Dict[str, MetricData]] = {}
        for turn in turns:
            if turn.metric_expectations:
                # Assign all available metrics to this turn
                # (validator will filter based on expectations)
                metrics_by_turn[turn.turn_id] = metrics

        return validator.validate_test_run(
            test_id=test_id,
            turns=turns,
            metrics_by_turn=metrics_by_turn,
            conversation_metrics=metrics,
            expected_score=expected_score,
            actual_score=actual_score,
            metric_tolerance=tol,  # ± tolerance for metrics
            score_tolerance=score_tol,
        )

    @staticmethod
    def _score_tolerance_from_metric_tol(metric_tol: Optional[float]) -> float:
        """Derive score tolerance (0-100 scale) from metric tolerance (0-1 scale)."""
        if metric_tol is None:
            return 10.0
        # If already on 0-100 scale, return as-is; otherwise scale up.
        return metric_tol if metric_tol > 1 else metric_tol * 100.0

    def _calibration_summary_from_dict(self, data: Dict[str, Any]) -> "CalibrationSummary":
        """Rehydrate CalibrationSummary from stored dict."""
        turns = [
            CalibrationResult(
                metric_name=r["metric_name"],
                turn_id=r["turn_id"],
                expected=r["expected"],
                actual=r.get("actual"),
                delta=r.get("delta"),
                within_tolerance=r.get("within_tolerance", False),
                tolerance=r.get("tolerance", 0.0),
            )
            for r in data.get("turns", [])
        ]

        conversation_data = data.get("conversation")
        conversation = (
            CalibrationResult(
                metric_name=conversation_data["metric_name"],
                turn_id=conversation_data.get("turn_id"),
                expected=conversation_data["expected"],
                actual=conversation_data.get("actual"),
                delta=conversation_data.get("delta"),
                within_tolerance=conversation_data.get("within_tolerance", False),
                tolerance=conversation_data.get("tolerance", 0.0),
            )
            if conversation_data
            else None
        )

        return CalibrationSummary(
            test_id=data.get("test_id", ""),
            turns=turns,
            conversation=conversation,
            expected_score=data.get("expected_score"),
            actual_score=data.get("actual_score"),
            score_delta=data.get("score_delta"),
            score_within_tolerance=data.get("score_within_tolerance", True),
            score_tolerance=data.get("score_tolerance"),
        )


__all__ = ["ReportingService"]

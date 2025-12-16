"""Calibration command that runs calibration scenarios as regular tests."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import typer
from bson import ObjectId

from production.calibration import CalibrationValidator, CalibrationSummary
from production.metrics import MetricsSummary
from production.reporting import ReportingService
from production.scenario_engine.engine import ScenarioEngine
from production.scenarios.loader import ScenarioLoader
from production.storage import MongoDBClient, MetricsStorageService
from production.storage.utils import generate_test_run_id
from production.utils.config import load_config
from production.utils.debug import setup_remote_debugging
from production.utils.logging_setup import configure_logging

from .shared import setup_storage, create_evaluation_run, finalize_evaluation_run

logger = logging.getLogger(__name__)


async def calibrate_async(
    file: Optional[Path],
    directory: Path,
    pattern: str,
    metric: Optional[str],
    log_level: str,
    store: bool = False,
) -> None:
    """Run calibration scenarios under ``tests/calibration`` using the standard engine."""
    configure_logging(log_level)
    config = load_config()
    setup_remote_debugging(config)

    # Toggle storage when explicitly requested even if env disabled
    if store and not config.storage_enabled:
        logger.info("Enabling storage for calibration run (--store)")
        config.storage_enabled = True

    storage_tuple = await setup_storage(config) if config.storage_enabled else None
    client: Optional[MongoDBClient] = None
    storage_service: Optional[MetricsStorageService] = None
    evaluation_run_id: Optional[ObjectId] = None

    # CALIBRATION OVERRIDES
    # NO NEED TO WAIT FOR RESPONSES ALL SENT
    config.tail_silence_ms = 0
    if storage_tuple:
        client, storage_service = storage_tuple
        # Override target_system for calibration runs
        config.target_system = "calibration"
        evaluation_run_id = await create_evaluation_run(storage_service, config)

    try:
        scenario_root, scenario_paths = _discover_scenarios(file, directory, pattern)
        loader = ScenarioLoader(base_path=scenario_root)

        loaded: List[Tuple[Path, object]] = []
        for scenario_path in scenario_paths:
            try:
                scenario = loader.load(scenario_path)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to load scenario %s: %s", scenario_path, exc, exc_info=True)
                raise typer.Exit(code=1) from exc

            if metric and metric not in scenario.tags and metric not in scenario_path.parts:
                continue
            loaded.append((scenario_path, scenario))

        if not loaded:
            logger.error(
                "No calibration scenarios found (directory=%s, metric=%s, pattern=%s)",
                directory,
                metric,
                pattern,
            )
            raise typer.Exit(code=1)

        logger.info("Running %d calibration scenario(s)", len(loaded))

        test_results: List[Tuple[str, MetricsSummary]] = []
        calibration_results: List[Tuple[str, CalibrationSummary]] = []

        for scenario_path, scenario in loaded:
            tolerance = scenario.tolerance if scenario.tolerance is not None else config.calibration_tolerance
            calibration_validator = CalibrationValidator(tolerance=tolerance)
            engine = ScenarioEngine(config, storage_service, evaluation_run_id)
            started_at = datetime.utcnow()
            summary, conversation_manager = await engine.run(
                scenario, started_at=started_at
            )
            finished_at = datetime.utcnow()

            test_results.append((scenario.id, summary))

            # Perform calibration validation for this scenario if expectations are defined
            if scenario.expected_score is not None or any(
                turn.metric_expectations for turn in scenario.turns
            ):
                calibration_summary = _validate_calibration(
                    scenario,
                    summary,
                    conversation_manager,
                    calibration_validator,
                    score_tolerance=_score_tolerance_from_metric_tol(tolerance),
                )
                calibration_results.append((scenario.id, calibration_summary))

                # Persist calibration summary on the stored test_run if storage is enabled
                if storage_service and evaluation_run_id:
                    test_run_id = generate_test_run_id(timestamp=started_at, test_id=scenario.id)
                    await storage_service.update_test_run(
                        test_run_id,
                        {"calibration_summary": _calibration_summary_to_dict(calibration_summary)},
                    )

        if storage_service and evaluation_run_id:
            # Calculate calibration status based on all test results
            calibration_status = _calculate_calibration_status(calibration_results)

            await finalize_evaluation_run(
                storage_service,
                evaluation_run_id,
                test_results,
                calibration_status=calibration_status
            )

            # Generate calibration report from database
            try:
                reporting_service = ReportingService(storage_service)
                report_path = await reporting_service.generate_evaluation_report(
                    evaluation_run_id
                )
                logger.info("Calibration report generated: %s", report_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to generate calibration report: %s", exc)

        # Report calibration summary
        if calibration_results:
            calibration_status = _calculate_calibration_status(calibration_results)
            _print_calibration_summary(calibration_results, calibration_status)

    finally:
        if client:
            await client.close()


def _discover_scenarios(
    file: Optional[Path],
    directory: Path,
    pattern: str,
) -> tuple[Path, List[Path]]:
    """Collect scenario files to run."""
    if file:
        scenario_path = Path(file)
        if not scenario_path.exists():
            logger.error("Calibration file not found: %s", scenario_path)
            raise typer.Exit(code=1)
        return scenario_path.parent, [scenario_path]

    scenario_root = Path(directory)
    if not scenario_root.exists():
        logger.error("Calibration directory not found: %s", scenario_root)
        raise typer.Exit(code=1)

    paths = sorted(scenario_root.glob(pattern))
    return scenario_root, paths


def _validate_calibration(scenario, summary, conversation_manager, validator, score_tolerance: Optional[float] = None):
    """Validate calibration expectations against actual results."""
    from production.scenario_engine.models import Scenario
    from production.metrics import MetricsSummary
    from production.capture.conversation_manager import ConversationManager
    from production.storage.models import Turn, MetricData

    # Build turns with metric expectations from scenario
    turns = []
    scenario_turns_by_id = {turn.id: turn for turn in scenario.turns}

    for turn_summary in conversation_manager.iter_turns():
        scenario_turn = scenario_turns_by_id.get(turn_summary.turn_id)
        if scenario_turn and scenario_turn.metric_expectations:
            turn = Turn(
                turn_id=turn_summary.turn_id,
                start_ms=turn_summary.turn_start_ms or 0,
                metric_expectations=scenario_turn.metric_expectations,
            )
            turns.append(turn)

    # Build metrics by turn from summary
    # IMPORTANT: A metric is EITHER per-turn OR conversation-level, never both!
    metrics_by_turn = {}
    conversation_metrics = {}

    for result in summary.results:
        metric_data = MetricData.from_metric_result(result)

        # Check if this is a per-turn metric (has details.turns)
        if result.details and "turns" in result.details:
            # Per-turn metric: Add to each turn that has metric expectations
            turn_results = result.details["turns"]
            for turn_result in turn_results:
                turn_id = turn_result.get("turn_id")
                if not turn_id:
                    continue

                # Only add to turns that have expectations for this metric
                for turn in turns:
                    if turn.turn_id == turn_id and result.metric_name in turn.metric_expectations:
                        if turn.turn_id not in metrics_by_turn:
                            metrics_by_turn[turn.turn_id] = {}
                        metrics_by_turn[turn.turn_id][result.metric_name] = metric_data
                        break

        # Check if this is a conversation-level metric (has details.conversation)
        elif result.details and "conversation" in result.details:
            # Conversation-level metric: Add to conversation_metrics
            conversation_metrics[result.metric_name] = metric_data

    # Calculate actual score from summary
    actual_score = _calculate_test_score(summary)

    # Validate
    return validator.validate_test_run(
        test_id=scenario.id,
        turns=turns,
        metrics_by_turn=metrics_by_turn,
        conversation_metrics=conversation_metrics,
        expected_score=scenario.expected_score,
        actual_score=actual_score,
        score_tolerance=score_tolerance,
    )


def _calculate_test_score(summary) -> float:
    """Calculate test score from metrics summary."""
    if summary.score is not None:
        return summary.score

    if not summary.results:
        return 0.0

    # Fallback: average metric scores (converted to 0-100)
    scores = [result.score for result in summary.results if result.score is not None]
    if scores:
        return round(sum(scores) / len(scores) * 100.0, 2)
    return 0.0


def _print_calibration_summary(calibration_results: List[Tuple[str, CalibrationSummary]], calibration_status: str):
    """Print calibration summary table to console."""
    total_tests = len(calibration_results)
    passed_tests = sum(1 for _, cal_summary in calibration_results if cal_summary.overall_passed)
    failed_tests = total_tests - passed_tests

    status_symbol = "✓" if calibration_status == "passed" else "✗"
    status_display = calibration_status.upper()

    logger.info("")
    logger.info("=" * 80)
    logger.info("CALIBRATION SUMMARY")
    logger.info("=" * 80)
    logger.info("")
    logger.info(f"  Calibration Status:  {status_symbol} {status_display}")
    logger.info(f"  Tests Passed:        {passed_tests}")
    logger.info(f"  Tests Failed:        {failed_tests}")
    logger.info(f"  Total:               {total_tests}")
    logger.info("")
    logger.info("=" * 80)


def _calibration_summary_to_dict(cal_summary: CalibrationSummary) -> dict:
    """Serialize CalibrationSummary to a dictionary for storage."""
    return {
        "test_id": cal_summary.test_id,
        "expected_score": cal_summary.expected_score,
        "actual_score": cal_summary.actual_score,
        "score_delta": cal_summary.score_delta,
        "score_within_tolerance": cal_summary.score_within_tolerance,
        "score_tolerance": cal_summary.score_tolerance,
        "overall_passed": cal_summary.overall_passed,  # Include property for metrics exporter
        "num_checks": cal_summary.num_checks,
        "num_passed": cal_summary.num_passed,
        "num_failed": cal_summary.num_failed,
        "turns": [
            {
                "metric_name": result.metric_name,
                "turn_id": result.turn_id,
                "expected": result.expected,
                "actual": result.actual,
                "delta": result.delta,
                "within_tolerance": result.within_tolerance,
                "tolerance": result.tolerance,
                "validation_level": result.validation_level,
            }
            for result in cal_summary.turns or []
        ],
        "conversation": (
            {
                "metric_name": cal_summary.conversation.metric_name,
                "turn_id": cal_summary.conversation.turn_id,
                "expected": cal_summary.conversation.expected,
                "actual": cal_summary.conversation.actual,
                "delta": cal_summary.conversation.delta,
                "within_tolerance": cal_summary.conversation.within_tolerance,
                "tolerance": cal_summary.conversation.tolerance,
                "validation_level": cal_summary.conversation.validation_level,
            }
            if cal_summary.conversation
            else None
        ),
    }


def _calculate_calibration_status(calibration_results: List[Tuple[str, CalibrationSummary]]) -> str:
    """Calculate overall calibration status from test results.

    Args:
        calibration_results: List of (test_id, CalibrationSummary) tuples

    Returns:
        "passed" if all tests passed, "failed" if any test failed
    """
    if not calibration_results:
        return "passed"  # No calibration checks = passed

    # Check if ALL tests passed
    all_passed = all(cal_summary.overall_passed for _, cal_summary in calibration_results)

    return "passed" if all_passed else "failed"


def _score_tolerance_from_metric_tol(metric_tol: Optional[float]) -> float:
    """Get score tolerance (0-100 scale) for overall score validation.

    Uses metric tolerance as baseline but can be different if needed.
    For now, uses same tolerance value (0-100 scale).

    Args:
        metric_tol: Metric tolerance (0-100 scale), e.g., 10.0 = ±10 points

    Returns:
        Score tolerance (0-100 scale)
    """
    if metric_tol is None:
        return 10.0  # Default: ±10 points
    return metric_tol


__all__ = ["calibrate_async"]

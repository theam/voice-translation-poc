"""Shared utilities for CLI commands."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from bson import ObjectId

from production.metrics import MetricsSummary
from production.services.system_information import collect_system_information
from production.storage import (
    MongoDBClient,
    MetricsStorageService,
    EvaluationRun,
)
from production.storage.utils import compute_config_hash, generate_evaluation_run_id, get_git_info
from production.utils.config import FrameworkConfig

logger = logging.getLogger(__name__)


async def setup_storage(config: FrameworkConfig) -> Optional[Tuple[MongoDBClient, MetricsStorageService]]:
    """Setup MongoDB storage if enabled.

    Args:
        config: Framework configuration

    Returns:
        Tuple of (client, service) or None if storage disabled
    """
    if not config.storage_enabled:
        logger.info("Storage disabled (MONGODB_ENABLED=false)")
        return None

    try:
        client = MongoDBClient(
            connection_string=config.storage_connection_string,
            database=config.storage_database
        )

        # Verify connection
        if not await client.ping():
            logger.error("Failed to connect to MongoDB")
            return None

        # Ensure indexes exist
        await client.create_indexes()

        service = MetricsStorageService(client)
        logger.info(f"Storage enabled: {config.storage_database} ({config.environment})")
        return client, service

    except Exception as e:
        logger.error(f"Failed to setup storage: {e}", exc_info=True)
        return None


async def create_evaluation_run(
    storage_service: MetricsStorageService,
    config: FrameworkConfig
) -> ObjectId:
    """Create a new evaluation run document.

    Args:
        storage_service: Storage service
        config: Framework configuration

    Returns:
        ObjectId of created evaluation run
    """
    started_at = datetime.utcnow()
    git_commit, git_branch = get_git_info()

    # Collect comprehensive system information
    system_info = await collect_system_information(config)

    evaluation_run = EvaluationRun(
        evaluation_run_id=generate_evaluation_run_id(started_at, git_commit, git_branch),
        environment=config.environment,
        target_system=config.target_system,
        started_at=started_at,
        git_commit=git_commit,
        git_branch=git_branch,
        framework_version="0.1.0",
        experiment_tags=config.storage_experiment_tags,
        system_information=system_info,
        system_info_hash=compute_config_hash(system_info),
        status="running"
    )

    evaluation_id = await storage_service.create_evaluation_run(evaluation_run)
    logger.info(f"Evaluation run created: {evaluation_run.evaluation_run_id}")
    return evaluation_id


async def finalize_evaluation_run(
    storage_service: MetricsStorageService,
    evaluation_run_id: ObjectId,
    test_results: List[Tuple[str, MetricsSummary]]
) -> None:
    """Finalize evaluation run with aggregated metrics.

    Args:
        storage_service: Storage service
        evaluation_run_id: Evaluation run ObjectId
        test_results: List of (test_id, MetricsSummary) tuples
    """
    finished_at = datetime.utcnow()

    # Aggregate metrics across all tests
    num_tests = len(test_results)
    num_passed = sum(1 for _, summary in test_results if summary.status == "passed")
    num_failed = num_tests - num_passed

    # Compute average metrics (WER, completeness, etc.)
    aggregated_metrics = compute_aggregated_metrics(test_results)

    # Compute average score across all tests
    evaluation_score = compute_evaluation_score(test_results)

    await storage_service.finalize_evaluation_run(
        evaluation_run_id=evaluation_run_id,
        finished_at=finished_at,
        aggregated_metrics=aggregated_metrics,
        num_tests=num_tests,
        num_passed=num_passed,
        num_failed=num_failed,
        score=evaluation_score
    )

    logger.info(
        f"Evaluation run finalized: {num_passed}/{num_tests} passed "
        f"(score: {evaluation_score:.2f}, average_wer: {aggregated_metrics.get('average_wer', 'N/A')})"
    )


def compute_aggregated_metrics(
    test_results: List[Tuple[str, MetricsSummary]]
) -> Dict[str, float]:
    """Compute suite-level aggregated metrics.

    Calculates averages for numeric metrics across all tests.

    Args:
        test_results: List of (test_id, MetricsSummary) tuples

    Returns:
        Dictionary of aggregated metrics (e.g., average_wer, average_completeness)
    """
    metric_values: Dict[str, List[float]] = defaultdict(list)

    # Collect all metric values
    for _, summary in test_results:
        for result in summary.results:
            if result.value is not None:
                metric_values[result.metric_name].append(result.value)

    # Compute averages
    aggregated = {}
    for metric_name, values in metric_values.items():
        if values:
            aggregated[f"average_{metric_name}"] = sum(values) / len(values)

    return aggregated


def compute_evaluation_score(
    test_results: List[Tuple[str, MetricsSummary]]
) -> float:
    """Compute overall evaluation score from test results.

    Calculates the average score across all tests. Each test's score is
    computed as the percentage of passed metrics (0-100).

    Args:
        test_results: List of (test_id, MetricsSummary) tuples

    Returns:
        Average score from 0-100 (0 = all tests failed all metrics, 100 = all tests passed all metrics)
    """
    if not test_results:
        return 0.0

    test_scores = []
    for _, summary in test_results:
        if not summary.results:
            test_scores.append(0.0)
            continue

        # Calculate test score: percentage of passed metrics
        passed_count = sum(1 for result in summary.results if result.passed)
        total_count = len(summary.results)
        test_score = (passed_count / total_count) * 100.0
        test_scores.append(test_score)

    # Return average of all test scores
    return round(sum(test_scores) / len(test_scores), 2)


__all__ = [
    "setup_storage",
    "create_evaluation_run",
    "finalize_evaluation_run",
    "compute_aggregated_metrics",
    "compute_evaluation_score",
]

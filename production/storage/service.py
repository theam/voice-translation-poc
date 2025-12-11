"""Storage service for persisting test metrics to MongoDB."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from .client import MongoDBClient
from .models import CalibrationRun, EvaluationRun, TestRun

logger = logging.getLogger(__name__)


class MetricsStorageService:
    """Service for persisting test metrics to MongoDB.

    Provides high-level operations for creating, updating, and querying
    evaluation runs and test results.

    Example:
        >>> client = MongoDBClient("mongodb://localhost:27017", "vt_metrics")
        >>> service = MetricsStorageService(client)
        >>>
        >>> # Create evaluation run
        >>> evaluation_run = EvaluationRun(
        ...     evaluation_run_id="2025-12-05-abc",
        ...     environment="dev",
        ...     target_system="voice_live",
        ...     started_at=datetime.utcnow()
        ... )
        >>> evaluation_id = await service.create_evaluation_run(evaluation_run)
        >>>
        >>> # Create test run
        >>> test_run = TestRun(
        ...     evaluation_run_id=evaluation_id,
        ...     test_run_id="2025-12-05T10-30-00Z-test-001",
        ...     test_id="test-001",
        ...     test_name="Test 1",
        ...     started_at=datetime.utcnow(),
        ...     finished_at=datetime.utcnow(),
        ...     duration_ms=1000,
        ...     metrics={},
        ...     status="success",
        ...     passed=True
        ... )
        >>> await service.create_test_run(test_run)
        >>>
        >>> # Finalize evaluation run
        >>> await service.finalize_evaluation_run(
        ...     evaluation_id,
        ...     finished_at=datetime.utcnow(),
        ...     aggregated_metrics={"average_wer": 0.25},
        ...     num_tests=1,
        ...     num_passed=1,
        ...     num_failed=0
        ... )
    """

    def __init__(self, client: MongoDBClient) -> None:
        """Initialize storage service.

        Args:
            client: MongoDB client for database access
        """
        self.client = client

    async def create_evaluation_run(self, evaluation_run: EvaluationRun) -> ObjectId:
        """Create a new evaluation run document.

        Args:
            evaluation_run: EvaluationRun object to persist

        Returns:
            ObjectId of inserted document
        """
        result = await self.client.evaluation_runs.insert_one(evaluation_run.to_document())
        logger.info(
            f"Created evaluation run: {evaluation_run.evaluation_run_id} "
            f"(ID: {result.inserted_id}, environment: {evaluation_run.environment})"
        )
        return result.inserted_id

    async def update_evaluation_run(
        self,
        evaluation_run_id: ObjectId,
        updates: Dict[str, Any]
    ) -> None:
        """Update an existing evaluation run.

        Use this to update fields like finished_at, metrics, status, etc.
        after the evaluation run has been created.

        Args:
            evaluation_run_id: MongoDB ObjectId of evaluation run
            updates: Dictionary of fields to update
        """
        await self.client.evaluation_runs.update_one(
            {"_id": evaluation_run_id},
            {"$set": updates}
        )
        logger.debug(f"Updated evaluation run {evaluation_run_id} with fields: {list(updates.keys())}")

    async def finalize_evaluation_run(
        self,
        evaluation_run_id: ObjectId,
        finished_at: datetime,
        aggregated_metrics: Dict[str, float],
        num_tests: int,
        num_passed: int,
        num_failed: int,
        score: Optional[float] = None
    ) -> None:
        """Finalize evaluation run with aggregated metrics and status.

        Called after all tests in the evaluation have completed. Updates the
        evaluation run document with final metrics, counts, and status.

        Args:
            evaluation_run_id: MongoDB ObjectId of evaluation run
            finished_at: Completion timestamp
            aggregated_metrics: Evaluation-level metrics (averages, totals)
            num_tests: Total test count
            num_passed: Passed test count
            num_failed: Failed test count
            score: Overall evaluation score (0-100), averaged from test scores
        """
        status = "completed" if num_failed == 0 else "failed"

        await self.update_evaluation_run(evaluation_run_id, {
            "finished_at": finished_at,
            "status": status,
            "metrics": aggregated_metrics,
            "num_tests": num_tests,
            "num_passed": num_passed,
            "num_failed": num_failed,
            "score": score
        })

        logger.info(
            f"Finalized evaluation run {evaluation_run_id}: {status.upper()} "
            f"({num_passed}/{num_tests} passed)"
        )

    async def create_test_run(self, test_run: TestRun) -> ObjectId:
        """Create a new test run document.

        Args:
            test_run: TestRun object to persist

        Returns:
            ObjectId of inserted document
        """
        result = await self.client.test_runs.insert_one(test_run.to_document())
        logger.info(
            f"Created test run: {test_run.test_run_id} "
            f"(test_id: {test_run.test_id}, evaluation: {test_run.evaluation_run_id}, "
            f"score: {test_run.score:.1f}, method: {test_run.score_method}, "
            f"status: {test_run.score_status})"
        )
        return result.inserted_id

    async def get_evaluation_run_by_id(self, evaluation_run_id: str) -> Optional[Dict[str, Any]]:
        """Fetch evaluation run by evaluation_run_id.

        Args:
            evaluation_run_id: Human-readable evaluation run ID (e.g., "2025-12-05T10-30Z-abc")

        Returns:
            Evaluation run document or None if not found
        """
        return await self.client.evaluation_runs.find_one({"evaluation_run_id": evaluation_run_id})

    async def get_evaluation_run_by_object_id(self, object_id: ObjectId) -> Optional[Dict[str, Any]]:
        """Fetch evaluation run by MongoDB ObjectId.

        Args:
            object_id: MongoDB ObjectId

        Returns:
            Evaluation run document or None if not found
        """
        return await self.client.evaluation_runs.find_one({"_id": object_id})

    async def get_test_runs_for_evaluation(
        self,
        evaluation_run_id: ObjectId
    ) -> List[Dict[str, Any]]:
        """Fetch all test runs for a given evaluation run.

        Args:
            evaluation_run_id: MongoDB ObjectId of evaluation run

        Returns:
            List of test run documents, sorted by started_at
        """
        cursor = self.client.test_runs.find(
            {"evaluation_run_id": evaluation_run_id}
        ).sort("started_at", 1)

        return await cursor.to_list(length=None)

    async def get_test_history(
        self,
        test_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Fetch historical results for a specific test.

        Useful for tracking how a specific test's metrics evolve over time
        across multiple evaluation runs.

        Args:
            test_id: Test identifier (from scenario.id)
            limit: Maximum number of results to return

        Returns:
            List of test run documents, most recent first
        """
        cursor = self.client.test_runs.find(
            {"test_id": test_id}
        ).sort("finished_at", -1).limit(limit)

        return await cursor.to_list(length=limit)

    async def get_recent_evaluation_runs(
        self,
        limit: int = 20,
        environment: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetch recent evaluation runs.

        Args:
            limit: Maximum number of evaluation runs to return
            environment: Optional environment filter (dev/stage/prod)

        Returns:
            List of evaluation run documents, most recent first
        """
        query = {}
        if environment:
            query["environment"] = environment

        cursor = self.client.evaluation_runs.find(query).sort("started_at", -1).limit(limit)

        return await cursor.to_list(length=limit)

    async def get_evaluation_runs_by_system_info_hash(
        self,
        system_info_hash: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Fetch evaluation runs with matching system information hash.

        Useful for comparing results across different runs with the
        same configuration to measure consistency/reliability.

        Args:
            system_info_hash: System information hash to match
            limit: Maximum number of results

        Returns:
            List of evaluation run documents, most recent first
        """
        cursor = self.client.evaluation_runs.find(
            {"system_info_hash": system_info_hash}
        ).sort("started_at", -1).limit(limit)

        return await cursor.to_list(length=limit)

    async def get_evaluation_runs_by_tags(
        self,
        tags: List[str],
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Fetch evaluation runs matching experiment tags.

        Args:
            tags: List of experiment tags to match (OR logic)
            limit: Maximum number of results

        Returns:
            List of evaluation run documents, most recent first
        """
        cursor = self.client.evaluation_runs.find(
            {"experiment_tags": {"$in": tags}}
        ).sort("started_at", -1).limit(limit)

        return await cursor.to_list(length=limit)

    async def reset_database(self) -> None:
        """Reset the database by dropping all collections and recreating indexes.

        WARNING: This permanently deletes all evaluation runs and test results.
        Use with caution, typically only in development/testing environments
        when schema changes require a clean slate.
        """
        await self.client.reset_database()
        await self.client.create_indexes()
        logger.info("Database reset and indexes recreated successfully")

    # =========================================================================
    # Calibration Run Methods
    # =========================================================================

    async def create_calibration_run(self, calibration_run: CalibrationRun) -> ObjectId:
        """Create a new calibration run document.

        Args:
            calibration_run: CalibrationRun object to persist

        Returns:
            ObjectId of inserted document
        """
        result = await self.client.calibration_runs.insert_one(calibration_run.to_document())
        logger.info(
            f"Created calibration run: {calibration_run.calibration_run_id} "
            f"(ID: {result.inserted_id}, metric: {calibration_run.metric}, "
            f"accuracy: {calibration_run.accuracy:.1%})"
        )
        return result.inserted_id

    async def get_calibration_run_by_id(
        self,
        calibration_run_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch calibration run by calibration_run_id.

        Args:
            calibration_run_id: Human-readable calibration run ID

        Returns:
            Calibration run document or None if not found
        """
        return await self.client.calibration_runs.find_one(
            {"calibration_run_id": calibration_run_id}
        )

    async def get_calibration_runs(
        self,
        metric: Optional[str] = None,
        config_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        min_accuracy: Optional[float] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Fetch calibration runs with optional filters.

        Args:
            metric: Filter by metric name
            config_id: Filter by calibration config ID
            start_date: Filter by runs started after this date
            end_date: Filter by runs started before this date
            min_accuracy: Filter by minimum accuracy (0.0-1.0)
            limit: Maximum number of results to return

        Returns:
            List of calibration run documents, most recent first
        """
        query: Dict[str, Any] = {}

        if metric:
            query["metric"] = metric
        if config_id:
            query["config_id"] = config_id
        if start_date:
            query["started_at"] = {"$gte": start_date}
        if end_date:
            query.setdefault("started_at", {})["$lte"] = end_date
        if min_accuracy is not None:
            query["accuracy"] = {"$gte": min_accuracy}

        cursor = self.client.calibration_runs.find(query).sort("started_at", -1).limit(limit)

        return await cursor.to_list(length=limit)

    async def get_calibration_history(
        self,
        metric: str,
        days: int = 30,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Fetch historical calibration results for drift detection.

        Returns recent calibration runs for a specific metric to track
        how metric behavior changes over time (e.g., after LLM model updates).

        Args:
            metric: Metric name to query
            days: Number of days of history to fetch
            limit: Maximum number of results

        Returns:
            List of calibration run documents, most recent first
        """
        from datetime import timedelta

        cutoff_date = datetime.utcnow() - timedelta(days=days)

        cursor = self.client.calibration_runs.find({
            "metric": metric,
            "started_at": {"$gte": cutoff_date}
        }).sort("started_at", -1).limit(limit)

        return await cursor.to_list(length=limit)

    async def get_recent_calibration_runs(
        self,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Fetch recent calibration runs across all metrics.

        Args:
            limit: Maximum number of calibration runs to return

        Returns:
            List of calibration run documents, most recent first
        """
        cursor = self.client.calibration_runs.find({}).sort("started_at", -1).limit(limit)

        return await cursor.to_list(length=limit)


__all__ = ["MetricsStorageService"]

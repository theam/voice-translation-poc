"""Storage service for persisting test metrics to MongoDB."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from .client import MongoDBClient
from .models import EvaluationRun, TestRun

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
        ...     score=92.5,
        ...     score_method="average"
        ... )
        >>> await service.create_test_run(test_run)
        >>>
        >>> # Finalize evaluation run
        >>> await service.finalize_evaluation_run(
        ...     evaluation_id,
        ...     finished_at=datetime.utcnow(),
        ...     aggregated_metrics={"average_wer": 25.0},
        ...     num_tests=1,
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
        score: Optional[float] = None,
        calibration_status: Optional[str] = None
    ) -> None:
        """Finalize evaluation run with aggregated metrics and status.

        Called after all tests in the evaluation have completed. Updates the
        evaluation run document with final metrics, counts, and status.

        Args:
            evaluation_run_id: MongoDB ObjectId of evaluation run
            finished_at: Completion timestamp
            aggregated_metrics: Evaluation-level metrics (averages, totals)
            num_tests: Total test count
            score: Overall evaluation score (0-100), averaged from test scores
            calibration_status: "passed" or "failed" for calibration runs, None otherwise
        """
        update_fields = {
            "finished_at": finished_at,
            "status": "completed",
            "metrics": aggregated_metrics,
            "num_tests": num_tests,
            "score": score,
            "calibration_status": calibration_status,
        }

        await self.update_evaluation_run(evaluation_run_id, update_fields)

        logger.info(
            f"Finalized evaluation run {evaluation_run_id}: COMPLETED ({num_tests} tests)"
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
            f"score: {test_run.score:.1f}, method: {test_run.score_method})"
        )
        return result.inserted_id

    async def update_test_run(self, test_run_id: str, updates: Dict[str, Any]) -> None:
        """Update an existing test run by test_run_id."""
        await self.client.test_runs.update_one(
            {"test_run_id": test_run_id},
            {"$set": updates}
        )

    async def get_evaluation_run_by_id(self, evaluation_run_id: str) -> Optional[EvaluationRun]:
        """Fetch evaluation run by evaluation_run_id.

        Args:
            evaluation_run_id: Human-readable evaluation run ID (e.g., "2025-12-05T10-30Z-abc")

        Returns:
            EvaluationRun instance or None if not found
        """
        doc = await self.client.evaluation_runs.find_one({"evaluation_run_id": evaluation_run_id})
        return EvaluationRun.from_document(doc) if doc else None

    async def get_evaluation_run_by_object_id(self, object_id: ObjectId) -> Optional[EvaluationRun]:
        """Fetch evaluation run by MongoDB ObjectId.

        Args:
            object_id: MongoDB ObjectId

        Returns:
            EvaluationRun instance or None if not found
        """
        doc = await self.client.evaluation_runs.find_one({"_id": object_id})
        return EvaluationRun.from_document(doc) if doc else None

    async def get_test_runs_for_evaluation(
        self,
        evaluation_run_id: ObjectId
    ) -> List[TestRun]:
        """Fetch all test runs for a given evaluation run.

        Args:
            evaluation_run_id: MongoDB ObjectId of evaluation run

        Returns:
            List of TestRun instances, sorted by started_at
        """
        cursor = self.client.test_runs.find(
            {"evaluation_run_id": evaluation_run_id}
        ).sort("started_at", 1)

        docs = await cursor.to_list(length=None)
        return [TestRun.from_document(doc) for doc in docs]

    async def get_test_history(
        self,
        test_id: str,
        limit: int = 50
    ) -> List[TestRun]:
        """Fetch historical results for a specific test.

        Useful for tracking how a specific test's metrics evolve over time
        across multiple evaluation runs.

        Args:
            test_id: Test identifier (from scenario.id)
            limit: Maximum number of results to return

        Returns:
            List of TestRun instances, most recent first
        """
        cursor = self.client.test_runs.find(
            {"test_id": test_id}
        ).sort("finished_at", -1).limit(limit)

        docs = await cursor.to_list(length=limit)
        return [TestRun.from_document(doc) for doc in docs]

    async def get_recent_evaluation_runs(
        self,
        limit: int = 20,
        environment: Optional[str] = None
    ) -> List[EvaluationRun]:
        """Fetch recent evaluation runs.

        Args:
            limit: Maximum number of evaluation runs to return
            environment: Optional environment filter (dev/stage/prod)

        Returns:
            List of EvaluationRun instances, most recent first
        """
        query = {}
        if environment:
            query["environment"] = environment

        cursor = self.client.evaluation_runs.find(query).sort("started_at", -1).limit(limit)

        docs = await cursor.to_list(length=limit)
        return [EvaluationRun.from_document(doc) for doc in docs]

    async def get_evaluation_runs_by_system_info_hash(
        self,
        system_info_hash: str,
        limit: int = 10
    ) -> List[EvaluationRun]:
        """Fetch evaluation runs with matching system information hash.

        Useful for comparing results across different runs with the
        same configuration to measure consistency/reliability.

        Args:
            system_info_hash: System information hash to match
            limit: Maximum number of results

        Returns:
            List of EvaluationRun instances, most recent first
        """
        cursor = self.client.evaluation_runs.find(
            {"system_info_hash": system_info_hash}
        ).sort("started_at", -1).limit(limit)

        docs = await cursor.to_list(length=limit)
        return [EvaluationRun.from_document(doc) for doc in docs]

    async def get_evaluation_runs_by_tags(
        self,
        tags: List[str],
        limit: int = 20
    ) -> List[EvaluationRun]:
        """Fetch evaluation runs matching experiment tags.

        Args:
            tags: List of experiment tags to match (OR logic)
            limit: Maximum number of results

        Returns:
            List of EvaluationRun instances, most recent first
        """
        cursor = self.client.evaluation_runs.find(
            {"experiment_tags": {"$in": tags}}
        ).sort("started_at", -1).limit(limit)

        docs = await cursor.to_list(length=limit)
        return [EvaluationRun.from_document(doc) for doc in docs]

    async def reset_database(self) -> None:
        """Reset the database by dropping all collections and recreating indexes.

        WARNING: This permanently deletes all evaluation runs and test results.
        Use with caution, typically only in development/testing environments
        when schema changes require a clean slate.
        """
        await self.client.reset_database()
        await self.client.create_indexes()
        logger.info("Database reset and indexes recreated successfully")



__all__ = ["MetricsStorageService"]

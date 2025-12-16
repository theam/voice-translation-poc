"""MongoDB client for async database operations."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.server_api import ServerApi

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


class MongoDBClient:
    """Async MongoDB client for metrics storage.

    Provides access to MongoDB collections with proper indexing
    for efficient queries on test metrics and evaluation runs.

    Example:
        >>> client = MongoDBClient(
        ...     connection_string="mongodb://localhost:27017",
        ...     database="vt_metrics"
        ... )
        >>> await client.create_indexes()
        >>> # Use client.evaluation_runs and client.test_runs
        >>> await client.close()
    """

    def __init__(self, connection_string: str, database: str) -> None:
        """Initialize MongoDB client.

        Args:
            connection_string: MongoDB connection string (e.g., mongodb://localhost:27017)
            database: Database name for metrics storage
        """
        self.connection_string = connection_string
        self.database_name = database

        # Initialize async client
        self.client: AsyncIOMotorClient = AsyncIOMotorClient(
            connection_string,
            server_api=ServerApi('1')
        )

        # Get database and collections
        self.db: AsyncIOMotorDatabase = self.client[database]
        self.evaluation_runs: AsyncIOMotorCollection = self.db["evaluation_runs"]
        self.test_runs: AsyncIOMotorCollection = self.db["test_runs"]

        logger.info(f"MongoDB client initialized for database: {database}")

    async def create_indexes(self) -> None:
        """Create required indexes for efficient queries.

        Indexes created:
        - evaluation_runs:
            - started_at: Time-series queries
            - evaluation_run_id: Unique identifier lookup
            - system_info_hash: Group by configuration
            - experiment_tags: Multi-key for tag filtering
            - score: For score-based queries and graphing

        - test_runs:
            - test_run_id: Unique identifier lookup
            - (test_id, finished_at): Compound index for test evolution
            - evaluation_run_id: Fetch all tests for an evaluation run
            - score: For score-based queries and graphing
        """
        logger.info("Creating MongoDB indexes...")

        # Evaluation runs indexes
        await self.evaluation_runs.create_index("started_at")
        await self.evaluation_runs.create_index("evaluation_run_id", unique=True)
        await self.evaluation_runs.create_index("system_info_hash")
        await self.evaluation_runs.create_index("experiment_tags")
        await self.evaluation_runs.create_index("score")

        # Test runs indexes
        await self.test_runs.create_index("test_run_id", unique=True)
        await self.test_runs.create_index([("test_id", 1), ("finished_at", -1)])
        await self.test_runs.create_index("evaluation_run_id")
        await self.test_runs.create_index("score")

        logger.info("MongoDB indexes created successfully")

    async def close(self) -> None:
        """Close MongoDB connection.

        Should be called when shutting down to properly release resources.
        """
        self.client.close()
        logger.info("MongoDB client closed")

    async def ping(self) -> bool:
        """Ping MongoDB to verify connection.

        Returns:
            True if connection is successful, False otherwise
        """
        try:
            await self.client.admin.command('ping')
            logger.info("MongoDB ping successful")
            return True
        except Exception as e:
            logger.error(f"MongoDB ping failed: {e}")
            return False

    async def reset_database(self) -> None:
        """Drop all collections in the database.

        WARNING: This permanently deletes all evaluation runs and test results.
        Use with caution, typically only in development/testing environments.
        """
        logger.warning(f"Resetting database: {self.database_name}")

        # Drop collections
        await self.evaluation_runs.drop()
        await self.test_runs.drop()

        logger.info(f"Database reset complete: {self.database_name}")
        logger.info("All collections dropped. Run create_indexes() to recreate schema.")


__all__ = ["MongoDBClient"]

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Iterable, List

from pymongo import MongoClient
from pymongo.read_preferences import ReadPreference

from .config import ExporterConfig

logger = logging.getLogger(__name__)


class MongoAccessor:
    """Read-only MongoDB accessor for evaluation and test runs."""

    def __init__(self, config: ExporterConfig):
        self._config = config
        self._client: MongoClient | None = None

    @property
    def client(self) -> MongoClient:
        if self._client is None:
            self._client = MongoClient(
                self._config.mongo_uri,
                appname="metrics_exporter",
                read_preference=ReadPreference.SECONDARY_PREFERRED,
            )
        return self._client

    def _db(self):
        return self.client[self._config.mongo_db_name]

    def fetch_evaluation_runs(self, cutoff: datetime) -> List[Dict]:
        """Fetch evaluation runs that started after the cutoff."""
        try:
            cursor = (
                self._db()[self._config.evaluation_collection]
                .find({"started_at": {"$gte": cutoff}})
                .sort("started_at", -1)
            )
            return list(cursor)
        except Exception:
            logger.exception("Failed to fetch evaluation runs from MongoDB")
            return []

    def fetch_test_runs(self, evaluation_ids: Iterable) -> List[Dict]:
        """Fetch test runs for the provided evaluation ObjectIds."""
        ids = list(evaluation_ids)
        if not ids:
            return []

        try:
            cursor = self._db()[self._config.test_runs_collection].find({"evaluation_run_id": {"$in": ids}})
            return list(cursor)
        except Exception:
            logger.exception("Failed to fetch test runs from MongoDB")
            return []

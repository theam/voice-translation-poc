"""Run test suite command implementation."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import typer
from bson import ObjectId
from rich.console import Console

from production.metrics import MetricsSummary
from production.reporting import ReportingService
from production.scenario_engine.engine import ScenarioEngine
from production.scenarios.loader import ScenarioLoader
from production.storage import MongoDBClient, MetricsStorageService
from production.utils.config import load_config
from production.utils.debug import setup_remote_debugging
from production.utils.logging_setup import configure_logging

from .shared import setup_storage, create_evaluation_run, finalize_evaluation_run

console = Console()

logger = logging.getLogger(__name__)


async def run_suite_async(folder: Path, pattern: str, log_level: str) -> None:
    """Run all scenarios within a folder with optional storage.

    Args:
        folder: Folder containing scenario files
        pattern: Glob pattern for scenario files
        log_level: Logging level
    """
    configure_logging(log_level)
    config = load_config()
    setup_remote_debugging(config)

    logger.info(f"Running test suite: folder={folder}, pattern={pattern}, log_level={log_level}")

    # Setup storage
    storage_tuple = await setup_storage(config)
    client: Optional[MongoDBClient] = None
    storage_service: Optional[MetricsStorageService] = None
    evaluation_run_id: Optional[ObjectId] = None

    if storage_tuple:
        client, storage_service = storage_tuple

        # Create evaluation run
        evaluation_run_id = await create_evaluation_run(storage_service, config)

    try:
        loader = ScenarioLoader(base_path=folder)
        test_results: List[Tuple[str, MetricsSummary]] = []

        # Run all scenarios
        for path in sorted(folder.glob(pattern)):
            scenario = loader.load(path)
            engine = ScenarioEngine(config, storage_service, evaluation_run_id)

            test_started_at = datetime.utcnow()
            summary, conversation_manager = await engine.run(scenario, started_at=test_started_at)
            test_finished_at = datetime.utcnow()

            test_results.append((scenario.id, summary))

        # Finalize evaluation run
        if storage_service and evaluation_run_id:
            await finalize_evaluation_run(storage_service, evaluation_run_id, test_results)

            # Generate suite report from database
            try:
                reporting_service = ReportingService(storage_service)
                report_path = await reporting_service.generate_evaluation_report(
                    evaluation_run_id
                )
                console.print(f"[green]Suite report generated:[/green] {report_path}")
            except Exception as e:
                logger.warning(f"Failed to generate suite report: {e}")

        logger.info(f"Suite completed ({len(test_results)} test(s))")

    finally:
        if client:
            await client.close()


__all__ = ["run_suite_async"]

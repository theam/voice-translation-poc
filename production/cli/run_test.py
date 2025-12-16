"""Run single test command implementation."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from bson import ObjectId

from production.reporting import ReportingService
from production.scenario_engine.engine import ScenarioEngine
from production.scenarios.loader import ScenarioLoader
from production.storage import MongoDBClient, MetricsStorageService
from production.utils.config import load_config
from production.utils.debug import setup_remote_debugging
from production.utils.logging_setup import configure_logging

from .shared import setup_storage, create_evaluation_run, finalize_evaluation_run

logger = logging.getLogger(__name__)


async def run_test_async(scenario_path: Path, log_level: str) -> None:
    """Run a single scenario file with optional storage.

    Args:
        scenario_path: Path to scenario YAML file
        log_level: Logging level
    """
    configure_logging(log_level)
    config = load_config()
    setup_remote_debugging(config)

    logger.info(f"Running single test: scenario_path={scenario_path}, log_level={log_level}")

    # Setup storage
    storage_tuple = await setup_storage(config)
    client: Optional[MongoDBClient] = None
    storage_service: Optional[MetricsStorageService] = None
    evaluation_run_id: Optional[ObjectId] = None

    if storage_tuple:
        client, storage_service = storage_tuple

        # Create evaluation run for single test
        evaluation_run_id = await create_evaluation_run(storage_service, config)

    try:
        # Load and run scenario
        scenario = ScenarioLoader(base_path=scenario_path.parent).load(scenario_path)
        engine = ScenarioEngine(config, storage_service, evaluation_run_id)

        test_started_at = datetime.utcnow()
        summary, conversation_manager = await engine.run(
            scenario, started_at=test_started_at
        )
        test_finished_at = datetime.utcnow()

        # Finalize evaluation run
        if storage_service and evaluation_run_id:
            await finalize_evaluation_run(
                storage_service,
                evaluation_run_id,
                [(scenario.id, summary)]
            )

            # Generate PDF report from database
            try:
                reporting_service = ReportingService(storage_service)
                report_path = await reporting_service.generate_evaluation_report(
                    evaluation_run_id
                )
                logger.info("Test report generated: %s", report_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to generate test report: %s", exc)

    # No pass/fail gate; exit code always 0 on completion

    finally:
        if client:
            await client.close()


__all__ = ["run_test_async"]

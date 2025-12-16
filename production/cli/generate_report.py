"""Generate PDF report command for existing evaluation runs."""
from __future__ import annotations

import logging
from typing import Optional

import typer
from bson import ObjectId
from bson.errors import InvalidId

from production.reporting import ReportingService
from production.storage import MongoDBClient, MetricsStorageService
from production.utils.config import load_config
from production.utils.logging_setup import configure_logging

from .shared import setup_storage

logger = logging.getLogger(__name__)


async def generate_report_async(
    evaluation_run_id: str,
    log_level: str,
) -> None:
    """Generate PDF report for an existing evaluation run.

    Args:
        evaluation_run_id: MongoDB ObjectId of the evaluation run
        log_level: Logging level
    """
    configure_logging(log_level)
    config = load_config()

    # Validate ObjectId format
    try:
        eval_run_object_id = ObjectId(evaluation_run_id)
    except InvalidId:
        logger.error(f"Invalid evaluation run ID format: {evaluation_run_id}")
        logger.error("Expected a 24-character hexadecimal string (MongoDB ObjectId)")
        raise typer.Exit(code=1)

    # Setup storage (required for report generation)
    if not config.storage_enabled:
        logger.error("Storage is disabled. Cannot generate report without database access.")
        logger.error("Enable storage by setting STORAGE_ENABLED=true in .env")
        raise typer.Exit(code=1)

    storage_tuple = await setup_storage(config)
    if not storage_tuple:
        logger.error("Failed to connect to storage. Cannot generate report.")
        raise typer.Exit(code=1)

    client: MongoDBClient
    storage_service: MetricsStorageService
    client, storage_service = storage_tuple

    try:
        # Generate report
        logger.info("Generating PDF report...")
        reporting_service = ReportingService(storage_service)
        # Choose calibration or evaluation report automatically based on run type
        report_path = await reporting_service.generate_report(eval_run_object_id)

        logger.info(f"✓ Report generated successfully: {report_path}")
        print(f"\nReport: {report_path}")

    except Exception as exc:
        logger.error(f"Failed to generate report: {exc}", exc_info=True)
        raise typer.Exit(code=1)

    finally:
        if client:
            await client.close()


__all__ = ["generate_report_async"]

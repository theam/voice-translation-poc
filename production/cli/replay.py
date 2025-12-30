"""Wire log replay command that runs wire logs as scenarios."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from bson import ObjectId

from production.scenario_engine.engine import ScenarioEngine
from production.storage import MongoDBClient, MetricsStorageService
from production.utils.config import load_config
from production.utils.debug import setup_remote_debugging
from production.utils.logging_setup import configure_logging
from production.wire_log.loader import WireLogScenarioLoader

from .shared import setup_storage, create_evaluation_run, finalize_evaluation_run

logger = logging.getLogger(__name__)


async def replay_async(
    wire_log_path: Path,
    log_level: str,
    store: bool = False,
) -> None:
    """Replay a wire log file through the scenario engine.

    Loads wire log as a Scenario with a single turn at 0ms, ensuring
    no silence is added. The replay turn processor sends messages with
    exact timing from the wire log.

    Args:
        wire_log_path: Path to wire log JSONL file
        log_level: Logging level
        store: Force-enable MongoDB storage for this run
    """
    configure_logging(log_level)
    config = load_config()
    setup_remote_debugging(config)

    # Toggle storage when explicitly requested even if env disabled
    if store and not config.storage_enabled:
        logger.info("Enabling storage for replay run (--store)")
        config.storage_enabled = True

    storage_tuple = await setup_storage(config) if config.storage_enabled else None
    client: Optional[MongoDBClient] = None
    storage_service: Optional[MetricsStorageService] = None
    evaluation_run_id: Optional[ObjectId] = None

    if storage_tuple:
        client, storage_service = storage_tuple
        evaluation_run_id = await create_evaluation_run(storage_service, config)

    try:
        # Load wire log as scenario
        wire_log = Path(wire_log_path)
        if not wire_log.exists():
            logger.error("Wire log not found: %s", wire_log)
            raise typer.Exit(code=1)

        logger.info("Loading wire log: %s", wire_log.name)
        loader = WireLogScenarioLoader()
        scenario = loader.load(wire_log)

        logger.info("Scenario created:")
        logger.info("  ID: %s", scenario.id)
        logger.info("  Participants: %s", list(scenario.participants.keys()))
        logger.info("  Turns: %d", len(scenario.turns))

        # Run scenario through engine (storage and logging handled automatically)
        logger.info("Starting replay...")
        engine = ScenarioEngine(config, storage_service, evaluation_run_id)
        started_at = datetime.utcnow()
        summary, conversation_manager = await engine.run(
            scenario, started_at=started_at
        )

        # Storage service handles logging results
        # No need for custom printing - results are logged by engine

        if storage_service and evaluation_run_id:
            await finalize_evaluation_run(
                storage_service,
                evaluation_run_id,
                [(scenario.id, summary)]
            )

        logger.info("✅ Replay complete!")

    finally:
        if client:
            await client.close()


__all__ = ["replay_async"]

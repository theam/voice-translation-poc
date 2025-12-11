"""Reset database command implementation."""
from __future__ import annotations

import logging

import typer

from production.storage import MongoDBClient, MetricsStorageService
from production.utils.config import load_config
from production.utils.logging_setup import configure_logging

logger = logging.getLogger(__name__)


async def reset_db_async(log_level: str, confirm: bool) -> None:
    """Reset MongoDB database by dropping all collections and recreating indexes.

    Args:
        log_level: Logging level
        confirm: Whether to skip confirmation prompt
    """
    configure_logging(log_level)
    config = load_config()

    logger.info(f"Running database reset: log_level={log_level}, confirm={confirm}")

    if not config.storage_enabled:
        logger.error("Storage is disabled (MONGODB_ENABLED=false). Cannot reset database.")
        raise typer.Exit(code=1)

    # Confirmation prompt
    if not confirm:
        database_name = config.storage_database
        environment = config.environment

        typer.echo(f"\n⚠️  WARNING: This will permanently delete all data in database '{database_name}'")
        typer.echo(f"   Environment: {environment}")
        typer.echo(f"   Connection: {config.storage_connection_string}\n")

        proceed = typer.confirm("Are you sure you want to reset the database?", default=False)

        if not proceed:
            logger.info("Database reset cancelled by user")
            return

    try:
        client = MongoDBClient(
            connection_string=config.storage_connection_string,
            database=config.storage_database
        )

        # Verify connection
        if not await client.ping():
            logger.error("Failed to connect to MongoDB")
            raise typer.Exit(code=1)

        # Create service and reset
        service = MetricsStorageService(client)
        await service.reset_database()

        logger.info("✓ Database reset complete")
        logger.info(f"  Collections dropped and indexes recreated in: {config.storage_database}")

        await client.close()

    except Exception as e:
        logger.error(f"Failed to reset database: {e}", exc_info=True)
        raise typer.Exit(code=1)


__all__ = ["reset_db_async"]

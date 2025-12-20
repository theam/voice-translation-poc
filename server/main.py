"""Main entry point for ACS translation server."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .config import Config, DEFAULT_CONFIG
from .core import ACSServer

logger = logging.getLogger(__name__)


async def async_main(config_path: str | None = None, host: str = "0.0.0.0", port: int = 8080):
    """Start ACS translation server (async).

    Args:
        config_path: Optional path to YAML config file
        host: Host to listen on (default: 0.0.0.0)
        port: Port to listen on (default: 8080)
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Load config
    config = DEFAULT_CONFIG
    if config_path:
        config = Config.from_yaml(Path(config_path))
        logger.info(f"Loaded config from {config_path}")
    else:
        logger.info("Using default config")

    # Create and start server
    server = ACSServer(
        config=config,
        host=host,
        port=port
    )

    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt, shutting down...")
    finally:
        await server.shutdown()


def main():
    """Main entry point (synchronous wrapper for poetry script)."""
    parser = argparse.ArgumentParser(description="Run ACS translation server")
    parser.add_argument("--config", help="Path to YAML config", required=False)
    parser.add_argument("--host", help="Host to listen on", default="0.0.0.0")
    parser.add_argument("--port", help="Port to listen on", type=int, default=8080)
    args = parser.parse_args()

    asyncio.run(async_main(
        config_path=args.config,
        host=args.host,
        port=args.port
    ))


if __name__ == "__main__":
    main()

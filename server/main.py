"""Main entry point for ACS translation server."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .config import Config
from .core import ACSServer

logger = logging.getLogger(__name__)


async def async_main(config_paths: list[str] | None = None, host: str = "0.0.0.0", port: int = 8080):
    """Start ACS translation server (async).

    Args:
        config_paths: Optional list of paths to YAML config files (merged left-to-right)
        host: Host to listen on (default: 0.0.0.0)
        port: Port to listen on (default: 8080)
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Load config
    if config_paths:
        path_objects = [Path(p) for p in config_paths]
    else:
        # Default to .config.yml in the server directory
        default_config_path = Path(__file__).parent / ".config.yml"
        path_objects = [default_config_path]

    config = Config.from_yaml(path_objects)
    if config_paths:
        logger.info(f"Loaded and merged {len(config_paths)} config file(s): {', '.join(config_paths)}")

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
    parser.add_argument("--config", help="Path to YAML config (can be specified multiple times)", required=False, action="append")
    parser.add_argument("--host", help="Host to listen on", default="0.0.0.0")
    parser.add_argument("--port", help="Port to listen on", type=int, default=8080)
    args = parser.parse_args()

    asyncio.run(async_main(
        config_paths=args.config,
        host=args.host,
        port=args.port
    ))


if __name__ == "__main__":
    main()

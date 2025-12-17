"""Logging helpers for the production test framework."""
from __future__ import annotations

import logging
import sys
from typing import Iterable


def configure_logging(level: str = "INFO", extra_handlers: Iterable[logging.Handler] | None = None) -> None:
    """Configure application logging with standard Python logging."""

    logging_level = getattr(logging, level.upper(), logging.INFO)

    # Create standard console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging_level)

    # Set format
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(formatter)

    # Build handlers list
    handlers = [console_handler]
    if extra_handlers:
        handlers.extend(extra_handlers)

    # Configure root logger
    logging.basicConfig(
        level=logging_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True  # Force reconfiguration if already configured
    )


__all__ = ["configure_logging"]

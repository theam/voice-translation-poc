from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExporterConfig:
    mongo_uri: str
    mongo_db_name: str
    evaluation_collection: str = "evaluation_runs"
    test_runs_collection: str = "test_runs"
    port: int = 9100
    lookback_days: int = 7


class ConfigError(Exception):
    """Raised when exporter configuration is invalid."""


_def_env = os.environ


def _get_env(
    key: str, default: Optional[str] = None, *, required: bool = False, env: os._Environ[str] = _def_env
) -> str:
    value = env.get(key, default)
    if required and (value is None or value == ""):
        raise ConfigError(f"Missing required environment variable: {key}")
    return value  # type: ignore[return-value]


def load_config(env: os._Environ[str] = _def_env) -> ExporterConfig:
    """Load exporter configuration from environment variables."""

    mongo_uri = _get_env("MONGO_URI", required=True, env=env)
    mongo_db_name = _get_env("MONGO_DB_NAME", required=True, env=env)

    evaluation_collection = _get_env("MONGO_EVALUATION_RUNS_COLLECTION", "evaluation_runs", env=env)
    test_runs_collection = _get_env("MONGO_TEST_RUNS_COLLECTION", "test_runs", env=env)

    port_str = _get_env("EXPORTER_PORT", "9100", env=env)
    lookback_str = _get_env("LOOKBACK_DAYS", "7", env=env)

    try:
        port = int(port_str)
    except ValueError as exc:
        raise ConfigError(f"Invalid EXPORTER_PORT: {port_str}") from exc

    try:
        lookback_days = int(lookback_str)
    except ValueError as exc:
        raise ConfigError(f"Invalid LOOKBACK_DAYS: {lookback_str}") from exc

    return ExporterConfig(
        mongo_uri=mongo_uri,
        mongo_db_name=mongo_db_name,
        evaluation_collection=evaluation_collection,
        test_runs_collection=test_runs_collection,
        port=port,
        lookback_days=lookback_days,
    )

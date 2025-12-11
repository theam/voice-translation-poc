"""Configuration loading helpers for the production test framework."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv


@dataclass
class FrameworkConfig:
    """Runtime configuration for the test harness.

    Values are loaded from environment variables to keep the framework
    deployable across CI and local machines without code changes.
    """

    # WebSocket and framework configuration
    websocket_url: str = field(
        default_factory=lambda: os.getenv("TRANSLATION_WEBSOCKET_URL", "ws://localhost:8000/ws")
    )
    output_dir: Path = field(
        default_factory=lambda: Path(os.getenv("TRANSLATION_RESULTS_DIR", "reports"))
    )
    debug_wire: bool = field(default_factory=lambda: os.getenv("TRANSLATION_DEBUG_WIRE", "false").lower() == "true")
    time_acceleration: float = field(
        default_factory=lambda: float(os.getenv("TRANSLATION_TIME_ACCELERATION", "1.0"))
    )
    connect_timeout: float = field(
        default_factory=lambda: float(os.getenv("TRANSLATION_CONNECT_TIMEOUT", "10.0"))
    )
    auth_key: Optional[str] = field(default_factory=lambda: os.getenv("TRANSLATION_WS_AUTH"))
    tail_silence_ms: int = field(
        default_factory=lambda: int(os.getenv("TRANSLATION_TAIL_SILENCE_MS", "10000"))
    )

    # Remote debugging configuration
    remote_debug: bool = field(
        default_factory=lambda: os.getenv("TRANSLATION_REMOTE_DEBUG", "false").lower() == "true"
    )
    debug_host: str = field(default_factory=lambda: os.getenv("TRANSLATION_DEBUG_HOST", "localhost"))
    debug_port: int = field(default_factory=lambda: int(os.getenv("TRANSLATION_DEBUG_PORT", "5678")))
    debug_suspend: bool = field(
        default_factory=lambda: os.getenv("TRANSLATION_DEBUG_SUSPEND", "false").lower() == "true"
    )
    debug_stdout: bool = field(
        default_factory=lambda: os.getenv("TRANSLATION_DEBUG_STDOUT", "true").lower() == "true"
    )
    debug_stderr: bool = field(
        default_factory=lambda: os.getenv("TRANSLATION_DEBUG_STDERR", "true").lower() == "true"
    )

    # Environment classification
    environment: str = field(
        default_factory=lambda: os.getenv("ENVIRONMENT", "dev")
    )

    # Target system being tested (voice_live, live_interpreter, custom_llm, etc.)
    target_system: str = field(
        default_factory=lambda: os.getenv("TARGET_SYSTEM", "voice_live")
    )

    # Metrics storage configuration
    storage_enabled: bool = field(
        default_factory=lambda: os.getenv("MONGODB_ENABLED", "false").lower() == "true"
    )
    storage_connection_string: str = field(
        default_factory=lambda: os.getenv("MONGODB_CONNECTION_STRING", "mongodb://localhost:27017")
    )
    storage_database: str = field(
        default_factory=lambda: os.getenv("MONGODB_DATABASE", "vt_metrics")
    )
    storage_experiment_tags: List[str] = field(
        default_factory=lambda: _parse_tags(os.getenv("EXPERIMENT_TAGS", ""))
    )

    # LLM service configuration (for metrics evaluation)
    llm_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("AZURE_AI_FOUNDRY_KEY")
    )
    llm_base_url: Optional[str] = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL")
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini")
    )

    def ensure_output_dir(self) -> Path:
        """Create the output directory if it does not exist."""

        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir


def _parse_tags(tags_str: str) -> List[str]:
    """Parse comma-separated tags string.

    Args:
        tags_str: Comma-separated tags (e.g., "baseline,config-tweak")

    Returns:
        List of tag strings, empty list if tags_str is empty
    """
    if not tags_str:
        return []
    return [tag.strip() for tag in tags_str.split(",") if tag.strip()]


def load_config(env_path: Optional[Path] = None, override_existing: bool = False) -> FrameworkConfig:
    """Load framework configuration, optionally sourcing a ``.env`` file first.

    Args:
        env_path: Path to a ``.env`` file. If ``None``, ``load_dotenv`` will look
            for a file named ``.env`` in the current working directory and
            parent directories.
        override_existing: Whether values from the ``.env`` file should override
            already-set environment variables. Defaults to ``False`` to avoid
            surprising overrides when running in CI where env vars are
            explicit.
    """

    load_dotenv(dotenv_path=env_path, override=override_existing)
    return FrameworkConfig()

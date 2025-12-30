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
    playout_initial_buffer_ms: int = field(
        default_factory=lambda: int(os.getenv("TRANSLATION_PLAYOUT_INITIAL_BUFFER_MS", "80"))
    )
    calibration_tolerance: float = field(
        default_factory=lambda: float(os.getenv("CALIBRATION_TOLERANCE", "10"))
    )

    # Loopback config
    loopback_latency_ms: int = field(
        default_factory=lambda: int(os.getenv("LOOPBACK_LATENCY_MS", "100"))
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

    # Target system being tested (voice_live, speech_translator, custom_llm, etc.)
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


def load_config(
    base_env_path: Optional[Path] = None,
    override_existing: bool = False
) -> FrameworkConfig:
    """Load framework configuration using Base + Override strategy.

    Loading Strategy:
        1. Load base environment file (.env) with shared defaults
        2. Load environment-specific override file (.env.{APP_ENV}) if APP_ENV is set
        3. Environment-specific values always override base values
        4. Both files are optional - fail gracefully if missing

    Environment Selection:
        - APP_ENV determines which environment-specific file to load
        - Default: "local" if APP_ENV not set
        - Examples: local, dev, staging, prod

    Args:
        base_env_path: Path to the base .env file. If None, searches for .env
            in current directory and parent directories.
        override_existing: Whether base .env should override already-set
            environment variables. Defaults to False to preserve explicit
            env vars in CI/production contexts.

    Returns:
        FrameworkConfig instance with values from base + environment override

    Example:
        # Load .env, then .env.dev (if APP_ENV=dev)
        config = load_config()

        # Explicit base path
        config = load_config(base_env_path=Path("custom/.env"))
    """
    # Step 1: Load base environment (.env)
    # This provides shared defaults across all environments
    base_loaded = load_dotenv(dotenv_path=base_env_path, override=override_existing)

    # Step 2: Determine active environment
    # APP_ENV selector determines which override file to load
    app_env = os.getenv("APP_ENV", "local")

    # Step 3: Load environment-specific override (.env.{APP_ENV})
    # Environment-specific values always win over base values
    if base_env_path:
        # If explicit base path provided, look for override in same directory
        env_dir = base_env_path.parent
        env_override_path = env_dir / f".env.{app_env}"
    else:
        # Search for override file starting from current directory
        env_override_path = Path(f".env.{app_env}")

    if env_override_path.exists():
        # Override=True ensures environment-specific values take precedence
        load_dotenv(dotenv_path=env_override_path, override=True)

    return FrameworkConfig()

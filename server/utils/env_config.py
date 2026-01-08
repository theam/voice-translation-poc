"""Environment variable configuration utilities.

Provides utilities to override configuration values from environment variables.
Environment variables follow the pattern: VT_{PATH_TO_PROPERTY} where:
- VT_ is the prefix
- Path components are separated by underscores
- All characters are UPPERCASE

Examples:
    VT_SYSTEM_LOG_LEVEL=DEBUG
    VT_PROVIDERS_OPENAI_API_KEY=sk-123
    VT_DISPATCH_BATCHING_ENABLED=false
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class EnvConfigError(Exception):
    """Raised when environment variable configuration fails."""


def parse_env_value(value: str, existing_value: Any) -> Any:
    """Parse environment variable string to appropriate Python type.

    Infers the target type from the existing value in the config.

    Args:
        value: The environment variable string value
        existing_value: The current value in config (used for type inference)

    Returns:
        Parsed value with appropriate type

    Raises:
        EnvConfigError: If value cannot be parsed to the expected type

    Examples:
        >>> parse_env_value("true", False)
        True
        >>> parse_env_value("123", 0)
        123
        >>> parse_env_value("1.5", 0.0)
        1.5
        >>> parse_env_value("hello", "")
        'hello'
    """
    # Handle None/null values
    if value == "" or value.lower() in ("null", "none"):
        return None

    # Infer type from existing value
    target_type = type(existing_value) if existing_value is not None else str

    # Handle boolean type
    if target_type is bool:
        value_lower = value.lower()
        if value_lower in ("true", "yes", "1", "on"):
            return True
        elif value_lower in ("false", "no", "0", "off"):
            return False
        else:
            raise EnvConfigError(
                f"Cannot parse '{value}' as boolean. "
                f"Valid values: true/false, yes/no, 1/0, on/off (case-insensitive)"
            )

    # Handle integer type
    if target_type is int:
        try:
            return int(value)
        except ValueError as exc:
            raise EnvConfigError(f"Cannot parse '{value}' as integer") from exc

    # Handle float type
    if target_type is float:
        try:
            return float(value)
        except ValueError as exc:
            raise EnvConfigError(f"Cannot parse '{value}' as float") from exc

    # Handle dict/list types (JSON parsing)
    if target_type in (dict, list):
        try:
            parsed = json.loads(value)
            if not isinstance(parsed, target_type):
                raise EnvConfigError(
                    f"Expected JSON {target_type.__name__}, got {type(parsed).__name__}"
                )
            return parsed
        except json.JSONDecodeError as exc:
            raise EnvConfigError(
                f"Cannot parse '{value}' as JSON {target_type.__name__}"
            ) from exc

    # Default: return as string
    return value


def _build_env_var_name(path: List[str], prefix: str) -> str:
    """Build environment variable name from config path.

    Args:
        path: List of keys representing path in config dict
        prefix: Environment variable prefix (e.g., "VT")

    Returns:
        Environment variable name in UPPERCASE

    Examples:
        >>> _build_env_var_name(["system", "log_level"], "VT")
        'VT_SYSTEM_LOG_LEVEL'
        >>> _build_env_var_name(["providers", "openai", "api_key"], "VT")
        'VT_PROVIDERS_OPENAI_API_KEY'
    """
    parts = [prefix] + path
    return "_".join(part.upper() for part in parts)


def apply_env_overrides(
    config_dict: Dict[str, Any],
    prefix: str = "VT",
    path: List[str] | None = None,
) -> Dict[str, Any]:
    """Recursively apply environment variable overrides to config dict.

    Walks the configuration dictionary and checks for corresponding environment
    variables. If found, parses and overrides the value. Skips list values.

    Args:
        config_dict: Configuration dictionary to override
        prefix: Environment variable prefix (default: "VT")
        path: Current path in config (for recursion, default: None)

    Returns:
        Configuration dictionary with environment overrides applied

    Raises:
        EnvConfigError: If environment variable value cannot be parsed

    Examples:
        With environment: VT_SYSTEM_LOG_LEVEL=DEBUG
        >>> config = {"system": {"log_level": "INFO"}}
        >>> result = apply_env_overrides(config)
        >>> result["system"]["log_level"]
        'DEBUG'
    """
    if path is None:
        path = []

    result = dict(config_dict)

    for key, value in result.items():
        current_path = path + [key]

        # Skip lists (v1 design decision)
        if isinstance(value, list):
            continue

        # Always recurse into dicts to allow setting individual nested values
        if isinstance(value, dict):
            result[key] = apply_env_overrides(value, prefix, current_path)
            continue

        # Check if environment variable exists for this scalar value
        env_var_name = _build_env_var_name(current_path, prefix)
        env_value = os.environ.get(env_var_name)

        if env_value is not None:
            # Environment variable found - parse and override
            try:
                parsed_value = parse_env_value(env_value, value)
                result[key] = parsed_value
                logger.info(
                    "config_override_from_env var=%s value_type=%s path=%s",
                    env_var_name,
                    type(parsed_value).__name__,
                    ".".join(current_path),
                )
            except EnvConfigError as exc:
                raise EnvConfigError(
                    f"Failed to parse environment variable {env_var_name}: {exc}"
                ) from exc

    return result


__all__ = ["apply_env_overrides", "parse_env_value", "EnvConfigError"]

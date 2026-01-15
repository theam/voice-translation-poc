"""Unit tests for environment variable configuration utilities."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import pytest

from .env_config import EnvConfigError, apply_env_overrides, parse_env_value


class TestParseEnvValue:
    """Tests for parse_env_value function."""

    def test_parse_boolean_true_variants(self):
        """Test parsing various true boolean values."""
        true_values = ["true", "True", "TRUE", "yes", "YES", "1", "on", "ON"]
        for value in true_values:
            assert parse_env_value(value, False) is True, f"Failed for: {value}"

    def test_parse_boolean_false_variants(self):
        """Test parsing various false boolean values."""
        false_values = ["false", "False", "FALSE", "no", "NO", "0", "off", "OFF"]
        for value in false_values:
            assert parse_env_value(value, True) is False, f"Failed for: {value}"

    def test_parse_boolean_invalid(self):
        """Test that invalid boolean values raise error."""
        with pytest.raises(EnvConfigError, match="Cannot parse .* as boolean"):
            parse_env_value("invalid", False)

    def test_parse_integer_valid(self):
        """Test parsing valid integer values."""
        assert parse_env_value("123", 0) == 123
        assert parse_env_value("-456", 0) == -456
        assert parse_env_value("0", 0) == 0

    def test_parse_integer_invalid(self):
        """Test that invalid integer values raise error."""
        with pytest.raises(EnvConfigError, match="Cannot parse .* as integer"):
            parse_env_value("not_a_number", 0)

    def test_parse_float_valid(self):
        """Test parsing valid float values."""
        assert parse_env_value("1.5", 0.0) == 1.5
        assert parse_env_value("-2.75", 0.0) == -2.75
        assert parse_env_value("0.0", 0.0) == 0.0

    def test_parse_float_invalid(self):
        """Test that invalid float values raise error."""
        with pytest.raises(EnvConfigError, match="Cannot parse .* as float"):
            parse_env_value("not_a_float", 0.0)

    def test_parse_string(self):
        """Test parsing string values."""
        assert parse_env_value("hello", "") == "hello"
        assert parse_env_value("world", "default") == "world"
        assert parse_env_value("with spaces", "") == "with spaces"

    def test_parse_null_variants(self):
        """Test parsing null/none/empty values."""
        assert parse_env_value("", "something") is None
        assert parse_env_value("null", "something") is None
        assert parse_env_value("NULL", "something") is None
        assert parse_env_value("none", "something") is None
        assert parse_env_value("None", "something") is None

    def test_parse_dict_valid(self):
        """Test parsing valid JSON dict values."""
        json_str = '{"key": "value", "num": 123}'
        expected = {"key": "value", "num": 123}
        assert parse_env_value(json_str, {}) == expected

    def test_parse_dict_invalid_json(self):
        """Test that invalid JSON raises error."""
        with pytest.raises(EnvConfigError, match="Cannot parse .* as JSON dict"):
            parse_env_value("{invalid json}", {})

    def test_parse_dict_wrong_type(self):
        """Test that JSON list when expecting dict raises error."""
        with pytest.raises(EnvConfigError, match="Expected JSON dict, got list"):
            parse_env_value("[1, 2, 3]", {})

    def test_parse_list_valid(self):
        """Test parsing valid JSON list values."""
        json_str = '["a", "b", "c"]'
        expected = ["a", "b", "c"]
        assert parse_env_value(json_str, []) == expected

    def test_parse_list_invalid_json(self):
        """Test that invalid JSON list raises error."""
        with pytest.raises(EnvConfigError, match="Cannot parse .* as JSON list"):
            parse_env_value("[invalid]", [])

    def test_parse_list_wrong_type(self):
        """Test that JSON dict when expecting list raises error."""
        with pytest.raises(EnvConfigError, match="Expected JSON list, got dict"):
            parse_env_value('{"key": "value"}', [])

    def test_parse_with_none_existing_value(self):
        """Test parsing when existing value is None defaults to string."""
        assert parse_env_value("default_string", None) == "default_string"


class TestApplyEnvOverrides:
    """Tests for apply_env_overrides function."""

    def setup_method(self):
        """Clear environment variables before each test."""
        # Store original env
        self.original_env = dict(os.environ)
        # Clear VT_ prefixed vars
        for key in list(os.environ.keys()):
            if key.startswith("VT_"):
                del os.environ[key]

    def teardown_method(self):
        """Restore environment variables after each test."""
        # Clear VT_ prefixed vars
        for key in list(os.environ.keys()):
            if key.startswith("VT_"):
                del os.environ[key]
        # Restore any that were there originally
        for key, value in self.original_env.items():
            if key.startswith("VT_"):
                os.environ[key] = value

    def test_no_env_vars_no_changes(self):
        """Test that config is unchanged when no env vars are set."""
        config = {"system": {"log_level": "INFO"}}
        result = apply_env_overrides(config)
        assert result == config

    def test_simple_string_override(self):
        """Test overriding a simple string value."""
        os.environ["VT_SYSTEM_LOG_LEVEL"] = "DEBUG"
        config = {"system": {"log_level": "INFO"}}
        result = apply_env_overrides(config)
        assert result["system"]["log_level"] == "DEBUG"

    def test_boolean_override(self):
        """Test overriding a boolean value."""
        os.environ["VT_SYSTEM_LOG_WIRE"] = "true"
        config = {"system": {"log_wire": False}}
        result = apply_env_overrides(config)
        assert result["system"]["log_wire"] is True

    def test_integer_override(self):
        """Test overriding an integer value."""
        os.environ["VT_BUFFERING_INGRESS_QUEUE_MAX"] = "5000"
        config = {"buffering": {"ingress_queue_max": 2000}}
        result = apply_env_overrides(config)
        assert result["buffering"]["ingress_queue_max"] == 5000

    def test_nested_override(self):
        """Test overriding deeply nested values."""
        os.environ["VT_DISPATCH_BATCHING_ENABLED"] = "false"
        config = {"dispatch": {"batching": {"enabled": True}}}
        result = apply_env_overrides(config)
        assert result["dispatch"]["batching"]["enabled"] is False

    def test_multiple_overrides(self):
        """Test overriding multiple values at once."""
        os.environ["VT_SYSTEM_LOG_LEVEL"] = "DEBUG"
        os.environ["VT_BUFFERING_INGRESS_QUEUE_MAX"] = "5000"
        os.environ["VT_SYSTEM_DEFAULT_PROVIDER"] = "openai"

        config = {
            "system": {"log_level": "INFO", "default_provider": "mock"},
            "buffering": {"ingress_queue_max": 2000},
            "dispatch": {},
        }

        result = apply_env_overrides(config)

        assert result["system"]["log_level"] == "DEBUG"
        assert result["buffering"]["ingress_queue_max"] == 5000
        assert result["system"]["default_provider"] == "openai"

    def test_provider_override(self):
        """Test overriding provider-specific configuration."""
        os.environ["VT_PROVIDERS_OPENAI_API_KEY"] = "sk-test-123"
        os.environ["VT_PROVIDERS_OPENAI_ENDPOINT"] = "https://api.openai.com"

        config = {
            "providers": {
                "openai": {
                    "api_key": None,
                    "endpoint": "https://default.com",
                }
            }
        }

        result = apply_env_overrides(config)

        assert result["providers"]["openai"]["api_key"] == "sk-test-123"
        assert result["providers"]["openai"]["endpoint"] == "https://api.openai.com"

    def test_deeply_nested_settings(self):
        """Test overriding deeply nested settings dict."""
        os.environ["VT_PROVIDERS_VOICELIVE_SETTINGS_SESSION_OPTIONS_VOICE"] = "alloy"

        config = {
            "providers": {
                "voicelive": {
                    "settings": {
                        "session_options": {
                            "voice": "shimmer"
                        }
                    }
                }
            }
        }

        result = apply_env_overrides(config)

        assert result["providers"]["voicelive"]["settings"]["session_options"]["voice"] == "alloy"

    def test_uppercase_conversion(self):
        """Test that environment variable names are properly uppercased."""
        # Even if provider name is lowercase in config, env var should be uppercase
        os.environ["VT_PROVIDERS_MYSERVICE_API_KEY"] = "test-key"

        config = {
            "providers": {
                "myservice": {
                    "api_key": None
                }
            }
        }

        result = apply_env_overrides(config)

        assert result["providers"]["myservice"]["api_key"] == "test-key"

    def test_list_values_skipped(self):
        """Test that list values are skipped (not overridden)."""
        os.environ["VT_SETTINGS_LANGUAGES"] = '["en-US", "es-ES"]'

        config = {
            "settings": {
                "languages": ["fr-FR", "de-DE"]
            }
        }

        result = apply_env_overrides(config)

        # List should remain unchanged (skipped in v1)
        assert result["settings"]["languages"] == ["fr-FR", "de-DE"]

    def test_invalid_env_value_raises_error(self):
        """Test that invalid environment variable values raise ConfigError."""
        os.environ["VT_BUFFERING_INGRESS_QUEUE_MAX"] = "not_a_number"

        config = {"buffering": {"ingress_queue_max": 2000}}

        with pytest.raises(EnvConfigError, match="Failed to parse environment variable"):
            apply_env_overrides(config)

    def test_null_value_override(self):
        """Test setting value to None via environment variable."""
        os.environ["VT_PROVIDERS_OPENAI_ENDPOINT"] = ""

        config = {
            "providers": {
                "openai": {
                    "endpoint": "https://api.openai.com"
                }
            }
        }

        result = apply_env_overrides(config)

        assert result["providers"]["openai"]["endpoint"] is None

    def test_custom_prefix(self):
        """Test using a custom prefix instead of VT_."""
        os.environ["CUSTOM_SYSTEM_LOG_LEVEL"] = "DEBUG"

        config = {"system": {"log_level": "INFO"}}

        result = apply_env_overrides(config, prefix="CUSTOM")

        assert result["system"]["log_level"] == "DEBUG"

    def test_preserves_unrelated_values(self):
        """Test that values without env vars are preserved."""
        os.environ["VT_SYSTEM_LOG_LEVEL"] = "DEBUG"

        config = {
            "system": {
                "log_level": "INFO",
                "log_wire": False,
                "log_wire_dir": "logs",
            }
        }

        result = apply_env_overrides(config)

        assert result["system"]["log_level"] == "DEBUG"  # Changed
        assert result["system"]["log_wire"] is False  # Unchanged
        assert result["system"]["log_wire_dir"] == "logs"  # Unchanged

    def test_empty_config(self):
        """Test with empty configuration dict."""
        config: Dict[str, Any] = {}
        result = apply_env_overrides(config)
        assert result == {}

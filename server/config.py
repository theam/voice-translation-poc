from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .utils.dict_utils import deep_merge

logger = logging.getLogger(__name__)

class ConfigError(Exception):
    """Raised when configuration cannot be loaded or is invalid."""




@dataclass
class BufferingConfig:
    ingress_queue_max: int = 2_000
    egress_queue_max: int = 2_000
    overflow_policy: str = "DROP_OLDEST"

    def to_dict(self) -> Dict:
        return {
            "ingress_queue_max": self.ingress_queue_max,
            "egress_queue_max": self.egress_queue_max,
            "overflow_policy": self.overflow_policy,
        }


@dataclass
class BatchingConfig:
    enabled: bool = True
    max_batch_ms: int = 200
    max_batch_bytes: int = 65_536
    idle_timeout_ms: int = 500

    def to_dict(self) -> Dict:
        return {
            "enabled": self.enabled,
            "max_batch_ms": self.max_batch_ms,
            "max_batch_bytes": self.max_batch_bytes,
            "idle_timeout_ms": self.idle_timeout_ms,
        }


@dataclass
class DispatchConfig:
    provider: str = "mock"
    batching: BatchingConfig = field(default_factory=BatchingConfig)

    def to_dict(self) -> Dict:
        return {
            "provider": self.provider,
            "batching": self.batching.to_dict(),
        }


@dataclass
class ProviderConfig:
    type: str = "mock"
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    region: Optional[str] = None
    resource: Optional[str] = None
    settings: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "type": self.type,
            "endpoint": self.endpoint,
            "api_key": self.api_key,
            "region": self.region,
            "resource": self.resource,
        }


@dataclass
class ProvidersConfig:
    providers: Dict[str, ProviderConfig] = field(
        default_factory=lambda: {"mock": ProviderConfig(type="mock")}
    )

    def get(self, name: str) -> ProviderConfig:
        try:
            return self.providers[name]
        except KeyError as exc:
            raise ValueError(f"Provider configuration '{name}' not found") from exc

    @classmethod
    def from_dict(cls, data: Dict[str, Dict]) -> "ProvidersConfig":
        if not data:
            return cls()

        providers: Dict[str, ProviderConfig] = {}
        for name, provider_data in data.items():
            provider_data = provider_data or {}
            providers[name] = ProviderConfig(
                type=provider_data.get("type", "mock"),
                endpoint=provider_data.get("endpoint"),
                api_key=provider_data.get("api_key"),
                region=provider_data.get("region"),
                resource=provider_data.get("resource"),
                settings=provider_data.get("settings", {}) or {},
            )

        return cls(providers=providers)

    def to_dict(self) -> Dict:
        return {name: provider.to_dict() for name, provider in self.providers.items()}




@dataclass
class PayloadCaptureConfig:
    enabled: bool = False
    mode: str = "metadata_only"  # metadata_only | full
    output_dir: str = "./artifacts"

    def to_dict(self) -> Dict:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "output_dir": self.output_dir,
        }


@dataclass
class SystemConfig:
    log_level: str = "INFO"
    payload_capture: PayloadCaptureConfig = field(default_factory=PayloadCaptureConfig)

    def to_dict(self) -> Dict:
        return {
            "log_level": self.log_level,
            "payload_capture": self.payload_capture.to_dict(),
        }


@dataclass
class Config:
    system: SystemConfig = field(default_factory=SystemConfig)
    buffering: BufferingConfig = field(default_factory=BufferingConfig)
    dispatch: DispatchConfig = field(default_factory=DispatchConfig)
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)

    def to_dict(self) -> Dict:
        return {
            "system": self.system.to_dict(),
            "buffering": self.buffering.to_dict(),
            "dispatch": self.dispatch.to_dict(),
            "providers": self.providers.to_dict(),
        }

    @classmethod
    def from_yaml(cls, paths: list[Path]) -> "Config":
        """Load and merge multiple YAML config files.

        Configs are merged left-to-right, with later configs overriding earlier ones.

        Args:
            paths: List of paths to YAML config files

        Returns:
            Merged Config object
        """
        # Filter out non-existent paths and log them
        valid_paths = []
        for path in paths or []:
            if path.is_file():
                valid_paths.append(path)
            else:
                logger.warning(f"Config path does not exist or is not a file: {path}")

        # If no valid paths, return default config
        if not valid_paths:
            logger.info("No valid config files found, using default config")
            return DEFAULT_CONFIG

        # Start with DEFAULT_CONFIG as base
        merged_dict = DEFAULT_CONFIG.to_dict()

        # Load and merge each config file
        yaml = cls._import_yaml()
        for path in valid_paths:
            with Path(path).open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            merged_dict = deep_merge(merged_dict, data)

        return cls.from_dict(merged_dict)

    @classmethod
    def from_dict(cls, data: Dict) -> "Config":
        system = data.get("system", {})
        buffering = data.get("buffering", {})
        dispatch = data.get("dispatch", {})
        providers = data.get("providers", {})

        return cls(
            system=SystemConfig(
                log_level=system.get("log_level", "INFO"),
                payload_capture=PayloadCaptureConfig(**system.get("payload_capture", {})),
            ),
            buffering=BufferingConfig(**buffering),
            dispatch=DispatchConfig(
                provider=dispatch.get("provider", "mock"),
                batching=BatchingConfig(**dispatch.get("batching", {})),
            ),
            providers=ProvidersConfig.from_dict(providers),
        )

    @staticmethod
    def _import_yaml():
        if importlib.util.find_spec("yaml") is None:  # type: ignore[attr-defined]
            raise ConfigError("PyYAML is required to load configuration from YAML.")
        return importlib.import_module("yaml")


DEFAULT_CONFIG = Config()

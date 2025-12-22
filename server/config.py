from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

class ConfigError(Exception):
    """Raised when configuration cannot be loaded or is invalid."""




@dataclass
class BufferingConfig:
    ingress_queue_max: int = 2_000
    egress_queue_max: int = 2_000
    overflow_policy: str = "DROP_OLDEST"


@dataclass
class BatchingConfig:
    enabled: bool = True
    max_batch_ms: int = 200
    max_batch_bytes: int = 65_536
    idle_timeout_ms: int = 500


@dataclass
class DispatchConfig:
    provider: str = "mock"
    batching: BatchingConfig = field(default_factory=BatchingConfig)


@dataclass
class ProviderConfig:
    type: str = "mock"
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    region: Optional[str] = None
    resource: Optional[str] = None
    settings: Dict[str, Any] = field(default_factory=dict)


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




@dataclass
class PayloadCaptureConfig:
    enabled: bool = False
    mode: str = "metadata_only"  # metadata_only | full
    output_dir: str = "./artifacts"


@dataclass
class SystemConfig:
    log_level: str = "INFO"
    payload_capture: PayloadCaptureConfig = field(default_factory=PayloadCaptureConfig)


@dataclass
class Config:
    system: SystemConfig = field(default_factory=SystemConfig)
    buffering: BufferingConfig = field(default_factory=BufferingConfig)
    dispatch: DispatchConfig = field(default_factory=DispatchConfig)
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> "Config":
        yaml = cls._import_yaml()
        with Path(path).open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

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

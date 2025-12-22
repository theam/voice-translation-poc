from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

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
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    region: Optional[str] = None
    resource: Optional[str] = None


@dataclass
class ProvidersConfig:
    voicelive: ProviderConfig = field(default_factory=ProviderConfig)
    live_interpreter: ProviderConfig = field(default_factory=ProviderConfig)
    mock: ProviderConfig = field(default_factory=ProviderConfig)




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
            providers=ProvidersConfig(
                voicelive=ProviderConfig(**providers.get("voicelive", {})),
                live_interpreter=ProviderConfig(**providers.get("live_interpreter", {})),
                mock=ProviderConfig(**providers.get("mock", {})),
            ),
        )

    @staticmethod
    def _import_yaml():
        if importlib.util.find_spec("yaml") is None:  # type: ignore[attr-defined]
            raise ConfigError("PyYAML is required to load configuration from YAML.")
        return importlib.import_module("yaml")


DEFAULT_CONFIG = Config()

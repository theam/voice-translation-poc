from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from server.config import Config, DEFAULT_CONFIG
from server.utils.env_config import apply_env_overrides


@dataclass(frozen=True)
class WebClientConfig:
    translation_ws_url: str
    translation_ws_auth: str | None
    connect_timeout: float
    debug_wire: bool
    call_ttl_minutes: int
    cleanup_interval_seconds: int
    server_config_paths: List[Path]

    @classmethod
    def from_env(cls) -> "WebClientConfig":
        paths = _parse_paths(os.getenv("ACS_WEBCLIENT_SERVER_CONFIGS", ""))
        return cls(
            translation_ws_url=os.getenv("TRANSLATION_WEBSOCKET_URL", "ws://localhost:8080/ws"),
            translation_ws_auth=os.getenv("TRANSLATION_WS_AUTH"),
            connect_timeout=float(os.getenv("TRANSLATION_CONNECT_TIMEOUT", "10.0")),
            debug_wire=os.getenv("TRANSLATION_DEBUG_WIRE", "false").lower() == "true",
            call_ttl_minutes=int(os.getenv("ACS_WEBCLIENT_CALL_TTL_MINUTES", "10")),
            cleanup_interval_seconds=int(os.getenv("ACS_WEBCLIENT_CLEANUP_INTERVAL_SECONDS", "60")),
            server_config_paths=paths,
        )


def load_server_config(paths: Iterable[Path]) -> Config:
    path_list = [path for path in paths if path.exists()]
    if path_list:
        return Config.from_yaml(path_list)

    config_dict = DEFAULT_CONFIG.to_dict()
    config_dict = apply_env_overrides(config_dict, prefix="VT")
    return Config.from_dict(config_dict)


def _parse_paths(raw: str) -> List[Path]:
    if not raw:
        return []
    return [Path(part.strip()) for part in raw.split(",") if part.strip()]


__all__ = ["WebClientConfig", "load_server_config"]

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class Settings:
    upstream_url: str = "ws://localhost:8080"
    upstream_headers: Dict[str, str] = field(default_factory=dict)
    available_services: Dict[str, str] = field(
        default_factory=lambda: {
            "VT Translation Service": "ws://localhost:8080",
            "Capco": "ws://localhost:9090",
        }
    )
    allowed_providers: List[str] = field(
        default_factory=lambda: [
            "openai",
            "voice_live",
            "live_interpreter_spanish",
            "live_interpreter_english",
            "role_based_li_en_es",
        ]
    )
    allowed_barge_in_modes: List[str] = field(
        default_factory=lambda: ["play_through", "pause_and_buffer", "pause_and_drop"]
    )

    @classmethod
    def from_env(cls) -> "Settings":
        upstream_url = os.getenv("ACS_UPSTREAM_URL", "ws://localhost:8080")
        headers_raw = os.getenv("ACS_UPSTREAM_HEADERS", "")
        allowed_providers = _split_env_list(
            "WEBCLIENT_ALLOWED_PROVIDERS",
            "openai,voice_live,live_interpreter_spanish,live_interpreter_english,role_based_li_en_es",
        )
        allowed_barge_in = _split_env_list(
            "WEBCLIENT_ALLOWED_BARGE_IN",
            "play_through,pause_and_buffer,pause_and_drop",
        )

        upstream_headers = {}
        if headers_raw:
            upstream_headers = json.loads(headers_raw)

        # Parse available services from env or use defaults
        services_raw = os.getenv("WEBCLIENT_AVAILABLE_SERVICES", "")
        available_services = {}
        if services_raw:
            available_services = json.loads(services_raw)
        else:
            available_services = {
                "VT Translation Service": "ws://host.docker.internal:8080",
                "Capco": "ws://localhost:9090",
            }

        return cls(
            upstream_url=upstream_url,
            upstream_headers=upstream_headers,
            available_services=available_services,
            allowed_providers=allowed_providers,
            allowed_barge_in_modes=allowed_barge_in,
        )


def _split_env_list(name: str, fallback: str) -> List[str]:
    raw = os.getenv(name, fallback)
    return [item.strip() for item in raw.split(",") if item.strip()]

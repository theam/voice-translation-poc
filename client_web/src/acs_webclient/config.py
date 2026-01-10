from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class Settings:
    upstream_url: str = "ws://localhost:8080"
    upstream_headers: Dict[str, str] = field(default_factory=dict)
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

        return cls(
            upstream_url=upstream_url,
            upstream_headers=upstream_headers,
            allowed_providers=allowed_providers,
            allowed_barge_in_modes=allowed_barge_in,
        )


def _split_env_list(name: str, fallback: str) -> List[str]:
    raw = os.getenv(name, fallback)
    return [item.strip() for item in raw.split(",") if item.strip()]

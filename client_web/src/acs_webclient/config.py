from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class Settings:
    upstream_url: str = "ws://host.docker.internal:8080"
    upstream_headers: Dict[str, str] = field(default_factory=dict)
    available_services: Dict[str, str] = field(
        default_factory=lambda: {
            "VT Translation Service": "ws://host.docker.internal:8080",
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
            "participant_based_openai",
        ]
    )
    allowed_barge_in_modes: List[str] = field(
        default_factory=lambda: ["play_through", "pause_and_buffer", "pause_and_drop"]
    )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls()


def _split_env_list(name: str, fallback: str) -> List[str]:
    raw = os.getenv(name, fallback)
    return [item.strip() for item in raw.split(",") if item.strip()]

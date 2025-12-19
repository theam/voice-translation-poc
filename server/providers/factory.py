from __future__ import annotations

from .base import TranslationProvider
from .mock import MockProvider
from .voicelive import VoiceLiveProvider


def create_provider(name: str, *, endpoint: str | None = None, api_key: str | None = None, key: str | None = None) -> TranslationProvider:
    normalized = name.lower()
    if normalized == "mock":
        return MockProvider()
    if normalized == "voicelive":
        return VoiceLiveProvider(endpoint=endpoint, api_key=api_key)
    if normalized == "live_interpreter":
        # Placeholder: wire in actual implementation when available
        return VoiceLiveProvider(endpoint=endpoint, api_key=key or api_key)
    raise ValueError(f"Unknown provider {name}")


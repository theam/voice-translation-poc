"""Configuration helpers for the Azure Speech translation POC."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

try:
    load_dotenv = importlib.import_module("dotenv").load_dotenv
except ModuleNotFoundError:  # pragma: no cover - fallback when dependency missing
    def load_dotenv(path: Optional[str] = None) -> None:
        return None


SUBSCRIPTION_KEY_ENV = "SPEECH__SUBSCRIPTION__KEY"
SERVICE_REGION_ENV = "SPEECH__SERVICE__REGION"
PROVIDER_ENV = "SPEECH__PROVIDER"
LIVE_INTERPRETER_ENDPOINT_ENV = "SPEECH__ENDPOINT"
VOICE_LIVE_KEY_ENV = "AZURE_AI_FOUNDRY_KEY"
VOICE_LIVE_ENDPOINT_ENV = "AZURE_AI_FOUNDRY_ENDPOINT"
VOICE_LIVE_RESOURCE_ENV = "AZURE_AI_FOUNDRY_RESOURCE"
VOICE_LIVE_MODEL_ENV = "AZURE_AI_FOUNDRY_MODEL"
VOICE_LIVE_API_VERSION_ENV = "AZURE_AI_FOUNDRY_API_VERSION"
VOICE_LIVE_DEPLOYMENT_ENV = "AZURE_AI_FOUNDRY_DEPLOYMENT"
VOICE_LIVE_OUTPUT_RATE_ENV = "AZURE_AI_FOUNDRY_OUTPUT_SAMPLE_RATE"
VOICE_LIVE_VOICE_ENV = "AZURE_AI_FOUNDRY_VOICE"

VOICE_LIVE_COMMIT_INTERVAL_ENV = "AZURE_AI_FOUNDRY_COMMIT_INTERVAL"
VOICE_LIVE_SILENCE_CHUNKS_ENV = "AZURE_AI_FOUNDRY_SILENCE_CHUNKS"
VOICE_LIVE_FORCE_COMMIT_CHUNKS_ENV = "AZURE_AI_FOUNDRY_FORCE_COMMIT_CHUNKS"


class SpeechProvider(str, Enum):
    """Supported Azure Speech translation providers."""

    LIVE_INTERPRETER = "live_interpreter"
    VOICE_LIVE = "voice_live"


@dataclass(frozen=True)
class SpeechServiceSettings:
    """Configuration required to authenticate against Azure Speech service."""

    subscription_key: str
    service_region: str
    provider: SpeechProvider = SpeechProvider.LIVE_INTERPRETER
    endpoint: Optional[str] = None
    resource_name: Optional[str] = None
    voice_live_model: Optional[str] = None
    voice_live_api_version: Optional[str] = None
    voice_live_deployment: Optional[str] = None
    voice_live_output_sample_rate: Optional[int] = None
    voice_live_voice: Optional[str] = None
    voice_live_commit_interval: Optional[int] = None
    voice_live_silence_chunks: Optional[int] = None
    voice_live_force_commit_chunks: Optional[int] = None

    @classmethod
    def from_env(cls, *, dotenv_path: Optional[str] = None) -> "SpeechServiceSettings":
        """Load settings from environment variables, optionally loading a .env file first."""
        load_dotenv(dotenv_path)

        service_region = os.getenv(SERVICE_REGION_ENV)
        provider_raw = os.getenv(PROVIDER_ENV, SpeechProvider.LIVE_INTERPRETER.value)

        try:
            provider = SpeechProvider(provider_raw.lower())
        except ValueError as exc:
            valid = ", ".join(p.value for p in SpeechProvider)
            raise RuntimeError(
                f"Unsupported speech provider '{provider_raw}'. Choose one of: {valid}."
            ) from exc

        subscription_key: Optional[str] = None
        endpoint: Optional[str] = None
        resource_name: Optional[str] = None

        voice_live_model = None
        voice_live_api_version = None
        voice_live_deployment = None
        voice_live_output_sample_rate: Optional[int] = None
        voice_live_voice: Optional[str] = None
        voice_live_commit_interval: Optional[int] = None
        voice_live_silence_chunks: Optional[int] = None
        voice_live_force_commit_chunks: Optional[int] = None

        subscription_key = os.getenv(VOICE_LIVE_KEY_ENV)
        endpoint = os.getenv(VOICE_LIVE_ENDPOINT_ENV)

        if provider is SpeechProvider.LIVE_INTERPRETER:
            required_pairs = [
                (SUBSCRIPTION_KEY_ENV, subscription_key),
                (SERVICE_REGION_ENV, service_region),
            ]
        else:
            resource_name = os.getenv(VOICE_LIVE_RESOURCE_ENV)
            voice_live_model = os.getenv(VOICE_LIVE_MODEL_ENV, "gpt-realtime-mini")
            voice_live_api_version = os.getenv(VOICE_LIVE_API_VERSION_ENV, "2024-10-01-preview")
            voice_live_deployment = os.getenv(VOICE_LIVE_DEPLOYMENT_ENV, voice_live_model)
            output_rate_raw = os.getenv(VOICE_LIVE_OUTPUT_RATE_ENV)
            if output_rate_raw:
                try:
                    voice_live_output_sample_rate = int(output_rate_raw)
                except ValueError as exc:
                    raise RuntimeError(
                        f"Invalid value for {VOICE_LIVE_OUTPUT_RATE_ENV}: {output_rate_raw}"
                    ) from exc
            voice_live_voice = os.getenv(VOICE_LIVE_VOICE_ENV)
            commit_interval_raw = os.getenv(VOICE_LIVE_COMMIT_INTERVAL_ENV)
            if commit_interval_raw:
                try:
                    voice_live_commit_interval = int(commit_interval_raw)
                except ValueError as exc:
                    raise RuntimeError(
                        f"Invalid value for {VOICE_LIVE_COMMIT_INTERVAL_ENV}: {commit_interval_raw}"
                    ) from exc
            silence_chunks_raw = os.getenv(VOICE_LIVE_SILENCE_CHUNKS_ENV)
            if silence_chunks_raw:
                try:
                    voice_live_silence_chunks = int(silence_chunks_raw)
                except ValueError as exc:
                    raise RuntimeError(
                        f"Invalid value for {VOICE_LIVE_SILENCE_CHUNKS_ENV}: {silence_chunks_raw}"
                    ) from exc
            force_commit_chunks_raw = os.getenv(VOICE_LIVE_FORCE_COMMIT_CHUNKS_ENV)
            if force_commit_chunks_raw:
                try:
                    voice_live_force_commit_chunks = int(force_commit_chunks_raw)
                except ValueError as exc:
                    raise RuntimeError(
                        f"Invalid value for {VOICE_LIVE_FORCE_COMMIT_CHUNKS_ENV}: {force_commit_chunks_raw}"
                    ) from exc

            if not endpoint and resource_name:
                endpoint = f"https://{resource_name}.services.ai.azure.com/"

            required_pairs = [
                (VOICE_LIVE_KEY_ENV, subscription_key),
                (SERVICE_REGION_ENV, service_region),
                (VOICE_LIVE_ENDPOINT_ENV, endpoint),
            ]

        missing = [name for name, value in required_pairs if not value]
        if missing:
            missing_vars = ", ".join(missing)
            raise RuntimeError(
                "Missing required Azure Speech configuration variables. "
                f"Please set {missing_vars} in your environment."
            )

        return cls(
            subscription_key=subscription_key,
            service_region=service_region,
            provider=provider,
            endpoint=endpoint,
            resource_name=resource_name,
            voice_live_model=voice_live_model,
            voice_live_api_version=voice_live_api_version,
            voice_live_deployment=voice_live_deployment,
            voice_live_output_sample_rate=voice_live_output_sample_rate,
            voice_live_voice=voice_live_voice,
            voice_live_commit_interval=voice_live_commit_interval,
            voice_live_silence_chunks=voice_live_silence_chunks,
            voice_live_force_commit_chunks=voice_live_force_commit_chunks,
        )



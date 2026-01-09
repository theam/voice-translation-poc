from __future__ import annotations

from dataclasses import dataclass

from ..audio import AudioFormat


@dataclass(frozen=True)
class ProviderAudioCapabilities:
    """Describes native audio formats for a provider."""

    provider_input_format: AudioFormat
    provider_output_format: AudioFormat


OPENAI_AUDIO_CAPABILITIES = ProviderAudioCapabilities(
    provider_input_format=AudioFormat(sample_rate_hz=24_000, channels=1, sample_format="pcm16"),
    provider_output_format=AudioFormat(sample_rate_hz=24_000, channels=1, sample_format="pcm16"),
)

VOICE_LIVE_AUDIO_CAPABILITIES = ProviderAudioCapabilities(
    provider_input_format=AudioFormat(sample_rate_hz=24_000, channels=1, sample_format="pcm16"),
    provider_output_format=AudioFormat(sample_rate_hz=24_000, channels=1, sample_format="pcm16"),
)

LIVE_INTERPRETER_AUDIO_CAPABILITIES = ProviderAudioCapabilities(
    provider_input_format=AudioFormat(sample_rate_hz=16_000, channels=1, sample_format="pcm16"),
    provider_output_format=AudioFormat(sample_rate_hz=16_000, channels=1, sample_format="pcm16"),
)

DEFAULT_AUDIO_CAPABILITIES = ProviderAudioCapabilities(
    provider_input_format=AudioFormat(sample_rate_hz=16_000, channels=1, sample_format="pcm16"),
    provider_output_format=AudioFormat(sample_rate_hz=16_000, channels=1, sample_format="pcm16"),
)


def get_provider_capabilities(provider_type: str | None) -> ProviderAudioCapabilities:
    """Return native audio formats for a provider type."""
    normalized = (provider_type or "").lower()
    if normalized in {"openai", "openai_realtime"}:
        return OPENAI_AUDIO_CAPABILITIES
    if normalized in {"voice_live", "voicelive", "realtime"}:
        return VOICE_LIVE_AUDIO_CAPABILITIES
    if normalized in {"live_interpreter", "liveinterpreter"}:
        return LIVE_INTERPRETER_AUDIO_CAPABILITIES
    return DEFAULT_AUDIO_CAPABILITIES

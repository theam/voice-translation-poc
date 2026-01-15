from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Dict

# ACS Audio Format Standards - enforced by backend
# Clients must resample to match these parameters before sending audio
ACS_SAMPLE_RATE = 16000  # Hz
ACS_CHANNELS = 1  # Mono
ACS_FRAME_BYTES = 640  # 20ms of audio @ 16kHz mono 16-bit PCM (320 samples * 2 bytes)
ACS_ENCODING = "PCM"  # PCM16


def iso_timestamp(timestamp_ms: int | None = None) -> str:
    if timestamp_ms is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def build_audio_metadata(subscription_id: str) -> Dict[str, Any]:
    """Build ACS audio metadata with enforced standard format.

    Clients must resample their audio to match ACS_SAMPLE_RATE, ACS_CHANNELS before sending.
    """
    return {
        "kind": "AudioMetadata",
        "audioMetadata": {
            "subscriptionId": subscription_id,
            "encoding": ACS_ENCODING,
            "sampleRate": ACS_SAMPLE_RATE,
            "channels": ACS_CHANNELS,
            "length": ACS_FRAME_BYTES,
        },
    }


def build_audio_message(
    participant_id: str,
    pcm_bytes: bytes,
    timestamp_ms: int | None = None,
    silent: bool = False,
) -> Dict[str, Any]:
    return {
        "kind": "AudioData",
        "audioData": {
            "participantRawID": participant_id,
            "timestamp": iso_timestamp(timestamp_ms),
            "data": base64.b64encode(pcm_bytes).decode("ascii"),
            "silent": silent,
        },
    }


def build_test_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "control.test.settings",
        "settings": settings,
    }

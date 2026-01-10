from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Dict


def iso_timestamp(timestamp_ms: int | None = None) -> str:
    if timestamp_ms is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def build_audio_metadata(sample_rate: int, channels: int, frame_bytes: int, subscription_id: str) -> Dict[str, Any]:
    return {
        "kind": "AudioMetadata",
        "audioMetadata": {
            "subscriptionId": subscription_id,
            "encoding": "PCM",
            "sampleRate": sample_rate,
            "channels": channels,
            "length": frame_bytes,
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

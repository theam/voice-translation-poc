"""ACS protocol models used by the emulator and adapters."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _iso_timestamp(timestamp_ms: Optional[int] = None) -> str:
    """Return an ISO-8601 UTC timestamp string.

    If ``timestamp_ms`` is provided, it is treated as milliseconds since the
    epoch; otherwise the current time is used.
    """

    if timestamp_ms is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class AcsAudioMetadata:
    """Represents the initial metadata ACS emits before streaming audio frames."""

    subscription_id: str
    encoding: str
    sample_rate: int
    channels: int
    length: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": "AudioMetadata",
            "audioMetadata": {
                "subscriptionId": self.subscription_id,
                "encoding": self.encoding,
                "sampleRate": self.sample_rate,
                "channels": self.channels,
                "length": self.length,
            },
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "AcsAudioMetadata":
        audio_metadata = payload.get("audioMetadata", {})
        return cls(
            subscription_id=audio_metadata.get("subscriptionId", ""),
            encoding=audio_metadata.get("encoding", ""),
            sample_rate=int(audio_metadata.get("sampleRate", 0)),
            channels=int(audio_metadata.get("channels", 0)),
            length=int(audio_metadata.get("length", 0)),
        )


@dataclass
class AcsAudioMessage:
    """Represents ACS audio frames (both inbound and outbound)."""

    data: bytes
    participant_raw_id: Optional[str] = None
    timestamp: Optional[str] = None
    silent: bool = False
    play_to_participant: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        audio_payload: Dict[str, Any] = {
            "data": base64.b64encode(self.data).decode("ascii"),
        }
        if self.participant_raw_id:
            audio_payload["participantRawID"] = self.participant_raw_id
        if self.timestamp:
            audio_payload["timestamp"] = self.timestamp
        audio_payload["silent"] = self.silent
        if self.play_to_participant:
            audio_payload["playToParticipant"] = self.play_to_participant
        return {"kind": "AudioData", "audioData": audio_payload}

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "AcsAudioMessage":
        audio_data = payload.get("audioData", {}) if "audioData" in payload else payload
        data_field = audio_data.get("data", "")
        return cls(
            data=base64.b64decode(data_field, validate=False),
            participant_raw_id=audio_data.get("participantRawID"),
            timestamp=audio_data.get("timestamp"),
            silent=bool(audio_data.get("silent", False)),
            play_to_participant=audio_data.get("playToParticipant"),
        )


@dataclass
class AcsTranscriptMessage:
    """Represents transcript style messages emitted by the SUT."""

    text: str
    participant_id: str
    source_language: str
    target_language: str
    timestamp_ms: int
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "transcript",
            "participant_id": self.participant_id,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "text": self.text,
            "timestamp_ms": self.timestamp_ms,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "AcsTranscriptMessage":
        return cls(
            text=payload.get("text", ""),
            participant_id=payload.get("participant_id", ""),
            source_language=payload.get("source_language", ""),
            target_language=payload.get("target_language", ""),
            timestamp_ms=int(payload.get("timestamp_ms", 0)),
            raw=payload,
        )


@dataclass
class TranslationTextDelta:
    """Represents incremental transcript delta messages from the SUT."""

    delta: str
    participant_id: str | None = None
    source_language: str | None = None
    target_language: str | None = None
    timestamp_ms: int | None = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TranslationTextDelta":
        return cls(
            delta=payload.get("delta", ""),
            participant_id=payload.get("participant_id") or payload.get("participantId"),
            source_language=payload.get("source_language"),
            target_language=payload.get("target_language"),
            timestamp_ms=payload.get("timestamp_ms"),
            raw=payload,
        )


__all__ = [
    "AcsAudioMetadata",
    "AcsAudioMessage",
    "AcsTranscriptMessage",
    "TranslationTextDelta",
    "_iso_timestamp",
]

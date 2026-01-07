from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from ...models.gateway_input_event import GatewayInputEvent
from ...models.provider_events import ProviderOutputEvent
from ...utils.time_utils import MonotonicClock


@dataclass
class ControlEvent:
    """Normalized control-plane event extracted from internal envelopes."""

    session_id: str
    kind: str
    payload: Dict[str, Any]
    participant_id: Optional[str] = None
    provider_response_id: Optional[str] = None
    commit_id: Optional[str] = None
    timestamp_ms: Optional[int] = None

    @classmethod
    def from_gateway(cls, event: GatewayInputEvent) -> "ControlEvent":
        payload = event.payload or {}
        participant_id = None
        if isinstance(payload, dict):
            audio_data = payload.get("audiodata") or {}
            if isinstance(audio_data, dict):
                participant_id = audio_data.get("participantrawid")

        return cls(
            session_id=event.session_id,
            kind="gateway.input",
            payload=payload,
            participant_id=participant_id,
            timestamp_ms=MonotonicClock.now_ms(),
        )

    @classmethod
    def from_provider(cls, event: ProviderOutputEvent) -> "ControlEvent":
        kind = f"provider.{event.event_type}" if event.event_type else "provider.unknown"
        return cls(
            session_id=event.session_id,
            participant_id=event.participant_id,
            kind=kind,
            payload=event.payload or {},
            provider_response_id=event.provider_response_id or event.stream_id,
            commit_id=event.commit_id,
            timestamp_ms=event.timestamp_ms,
        )

    @classmethod
    def from_acs_outbound(cls, session_id: str, payload: Dict[str, Any]) -> Optional["ControlEvent"]:
        if not isinstance(payload, dict):
            return None

        kind = payload.get("kind")
        if kind not in {"audioData", "audio.data"}:
            return None

        audio_data = payload.get("audioData") or payload.get("audio_data") or {}
        participant_id = None
        if isinstance(audio_data, dict):
            participant_id = audio_data.get("participant") or audio_data.get("participantrawid")

        return cls(
            session_id=session_id,
            participant_id=participant_id,
            kind="acs_outbound.audio",
            payload=payload,
            timestamp_ms=MonotonicClock.now_ms(),
        )


__all__ = ["ControlEvent"]

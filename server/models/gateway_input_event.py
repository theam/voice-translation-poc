from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_id() -> str:
    return str(uuid.uuid4())


@dataclass
class ConnectionContext:
    ingress_ws_id: str
    call_connection_id: Optional[str] = None
    call_correlation_id: Optional[str] = None


@dataclass
class Trace:
    sequence: int
    ingress_ws_id: str
    received_at_utc: str
    call_correlation_id: Optional[str] = None


@dataclass
class GatewayInputEvent:
    event_id: str
    source: str
    event_type: str
    content_type: str
    session_id: str
    participant_id: Optional[str]
    subscription_id: Optional[str]
    received_at_utc: str
    timestamp_utc: str
    payload: Dict[str, Any]
    raw_frame: Dict[str, Any]
    trace: Trace

    @classmethod
    def from_acs_frame(cls, frame: Dict[str, Any], sequence: int, ctx: ConnectionContext) -> "GatewayInputEvent":
        """Create a canonical event for an inbound ACS WebSocket frame."""

        now = _utcnow_iso()
        kind = frame.get("kind")
        event_map = {
            "AudioMetadata": "acs.audio.metadata",
            "AudioData": "acs.audio.data",
        }

        event_type = event_map.get(kind, "acs.unknown")
        payload_key_map = {
            "acs.audio.metadata": "audioMetadata",
            "acs.audio.data": "audioData",
        }

        payload_key = payload_key_map.get(event_type)
        payload: Dict[str, Any] = {}
        if payload_key:
            payload_candidate = frame.get(payload_key, {})
            if isinstance(payload_candidate, dict):
                payload = payload_candidate

        participant_id: Optional[str] = None
        subscription_id: Optional[str] = None
        timestamp_utc: str = now

        if event_type == "acs.audio.metadata":
            subscription_id = payload.get("subscriptionId")
            timestamp_utc = now
        elif event_type == "acs.audio.data":
            participant_id = payload.get("participantRawID")
            timestamp_utc = payload.get("timestamp") or now

            data_field = payload.get("data")
            if isinstance(data_field, str):
                try:
                    base64.b64decode(data_field, validate=True)
                except Exception as exc:  # pragma: no cover - defensive check
                    raise ValueError(f"Invalid base64 data payload: {exc}") from exc

        session_id = ctx.call_connection_id or ctx.ingress_ws_id

        trace = Trace(
            sequence=sequence,
            ingress_ws_id=ctx.ingress_ws_id,
            call_correlation_id=ctx.call_correlation_id,
            received_at_utc=now,
        )

        return cls(
            event_id=_generate_id(),
            source="acs",
            event_type=event_type,
            content_type="application/json",
            session_id=session_id,
            participant_id=participant_id,
            subscription_id=subscription_id,
            received_at_utc=now,
            timestamp_utc=str(timestamp_utc),
            payload=payload,
            raw_frame=frame,
            trace=trace,
        )

    def to_json(self) -> str:
        def default(obj: Any) -> Any:
            if isinstance(obj, Trace):
                return obj.__dict__
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

        return json.dumps(self.__dict__, default=default)

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ...models.gateway_input_event import ConnectionContext, GatewayInputEvent, Trace


class AcsInputMapper:
    """Converts inbound ACS frames into canonical GatewayInputEvents."""

    _EVENT_MAP = {
        "audiometadata": "acs.audio.metadata",
        "audiodata": "acs.audio.data",
    }

    _PAYLOAD_KEY_MAP = {
        "acs.audio.metadata": "audiometadata",
        "acs.audio.data": "audiodata",
    }

    def __init__(self, ctx: ConnectionContext):
        self._ctx = ctx

    def from_frame(self, frame: Dict[str, Any], sequence: int) -> GatewayInputEvent:
        now = self._utcnow_iso()
        event_type = self._determine_event_type(frame)
        payload = self._extract_payload(frame, event_type)

        participant_id, subscription_id, timestamp_utc = self._extract_identifiers(
            event_type, payload, now
        )

        trace = Trace(
            sequence=sequence,
            ingress_ws_id=self._ctx.ingress_ws_id,
            call_correlation_id=self._ctx.call_correlation_id,
            received_at_utc=now,
        )

        session_id = self._ctx.call_connection_id or self._ctx.ingress_ws_id

        return GatewayInputEvent(
            event_id=self._generate_id(),
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

    def _determine_event_type(self, frame: Dict[str, Any]) -> str:
        """Decide event type using frame['type'] (test control) or frame['kind'] (ACS core)."""
        msg_type = frame.get("type")
        if isinstance(msg_type, str) and msg_type:
            return msg_type

        kind = frame.get("kind")
        if isinstance(kind, str):
            return self._EVENT_MAP.get(kind.lower(), "acs.unknown")

        return "acs.unknown"

    def _extract_payload(self, frame: Dict[str, Any], event_type: str) -> Dict[str, Any]:
        payload_key = self._PAYLOAD_KEY_MAP.get(event_type)
        if payload_key:
            payload_candidate = frame.get(payload_key, {})
            return payload_candidate if isinstance(payload_candidate, dict) else {}

        if isinstance(frame, dict) and frame.get("type") == event_type:
            return frame

        return {}

    def _extract_identifiers(
        self, event_type: str, payload: Dict[str, Any], fallback_timestamp: str
    ) -> tuple[Optional[str], Optional[str], str]:
        participant_id: Optional[str] = None
        subscription_id: Optional[str] = None
        timestamp_utc: Any = fallback_timestamp

        if event_type == "acs.audio.metadata":
            subscription_id = payload.get("subscriptionid")
        elif event_type == "acs.audio.data":
            participant_id = payload.get("participantrawid")
            timestamp_utc = payload.get("timestamp") or fallback_timestamp
            self._validate_audio_payload(payload)
        elif event_type.startswith("control"):
            timestamp_utc = payload.get("timestamp") or fallback_timestamp

        return participant_id, subscription_id, timestamp_utc

    def _validate_audio_payload(self, payload: Dict[str, Any]) -> None:
        data_field = payload.get("data")
        if isinstance(data_field, str):
            try:
                base64.b64decode(data_field, validate=True)
            except Exception as exc:  # pragma: no cover - defensive check
                raise ValueError(f"Invalid base64 data payload: {exc}") from exc

    @staticmethod
    def _utcnow_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _generate_id() -> str:
        return str(uuid.uuid4())

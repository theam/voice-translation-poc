from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_id() -> str:
    return str(uuid.uuid4())


@dataclass
class Trace:
    sequence: int
    received_at_utc: str
    ingress_ws_id: Optional[str] = None


@dataclass
class Envelope:
    message_id: str
    session_id: str
    participant_id: Optional[str]
    scenario_id: Optional[str]
    commit_id: Optional[str]
    timestamp_utc: str
    source: str
    type: str
    content_type: Optional[str]
    payload: Dict[str, Any]
    raw: Optional[Any] = None
    trace: Optional[Trace] = None

    @classmethod
    def from_acs_frame(cls, frame: Dict[str, Any], sequence: int, ingress_ws_id: str) -> "Envelope":
        now = _utcnow_iso()
        payload = frame.get("payload", {}) if isinstance(frame.get("payload"), dict) else {}
        return cls(
            message_id=str(frame.get("message_id") or _generate_id()),
            session_id=str(frame.get("session_id") or frame.get("call_id") or "unknown"),
            participant_id=frame.get("participant_id"),
            scenario_id=frame.get("scenario_id"),
            commit_id=frame.get("commit_id"),
            timestamp_utc=frame.get("timestamp_utc") or now,
            source="acs",
            type=frame.get("type", "unknown"),
            content_type=frame.get("content_type"),
            payload=payload,
            raw=frame if frame.get("raw") else None,
            trace=Trace(sequence=sequence, received_at_utc=now, ingress_ws_id=ingress_ws_id),
        )

    def ensure_audio_metadata(self) -> None:
        if self.type.startswith("audio") and self.payload.get("audio_b64"):
            # Validate base64; we do not decode to keep ingestion lightweight
            try:
                base64.b64decode(self.payload["audio_b64"], validate=True)
            except Exception as exc:  # pragma: no cover - defensive check
                raise ValueError(f"Invalid base64 audio payload: {exc}") from exc

    def to_json(self) -> str:
        def default(obj: Any) -> Any:
            if isinstance(obj, Trace):
                return obj.__dict__
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

        return json.dumps(self.__dict__, default=default)


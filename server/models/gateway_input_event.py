from __future__ import annotations

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
    content_type: str
    session_id: str
    received_at_utc: str
    payload: Dict[str, Any]
    trace: Trace

    @classmethod
    def from_acs_frame(cls, frame: Dict[str, Any], sequence: int, ctx: ConnectionContext) -> "GatewayInputEvent":
        """Wrap an inbound ACS WebSocket frame."""

        now = _utcnow_iso()
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
            content_type="application/json",
            session_id=session_id,
            received_at_utc=now,
            payload=frame,
            trace=trace,
        )

    def to_json(self) -> str:
        def default(obj: Any) -> Any:
            if isinstance(obj, Trace):
                return obj.__dict__
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

        return json.dumps(self.__dict__, default=default)

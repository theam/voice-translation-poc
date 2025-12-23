from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional


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

    def to_json(self) -> str:
        def default(obj: Any) -> Any:
            if isinstance(obj, Trace):
                return obj.__dict__
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

        return json.dumps(self.__dict__, default=default)

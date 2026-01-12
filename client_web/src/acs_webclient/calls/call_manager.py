from __future__ import annotations

import logging
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import WebSocket

from ..config import Settings
from .call_state import CallState

logger = logging.getLogger(__name__)

_CALL_ALPHABET = string.ascii_uppercase + string.digits
_MAX_RECENT_CALLS = 10


def _generate_call_code(length: int = 6) -> str:
    """Generate a random call code using uppercase letters and digits."""
    return "".join(secrets.choice(_CALL_ALPHABET) for _ in range(length))


@dataclass
class RecentCall:
    """Metadata about a recently created call for UI display."""
    call_code: str
    service: str
    provider: str
    barge_in: str
    created_at: str  # ISO timestamp
    participant_count: int = 0


class CallManager:
    """
    Manages multiple concurrent calls and their lifecycles.

    Responsibilities:
    - Create new calls with unique call codes
    - Track active and recent calls
    - Add/remove participants from calls
    - Clean up resources when calls end
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._calls: Dict[str, CallState] = {}
        self._recent_calls: List[RecentCall] = []

    def create_call(self, service: str, service_url: str, provider: str, barge_in: str) -> CallState:
        """Create a new call with a unique call code."""
        call_code = _generate_call_code()
        call_state = CallState(
            call_code=call_code,
            service=service,
            service_url=service_url,
            provider=provider,
            barge_in=barge_in,
            settings=self._settings,
        )
        self._calls[call_code] = call_state

        # Add to recent calls list
        recent_call = RecentCall(
            call_code=call_code,
            service=service,
            provider=provider,
            barge_in=barge_in,
            created_at=datetime.now(timezone.utc).isoformat(),
            participant_count=0,
        )
        self._recent_calls.insert(0, recent_call)  # Add to front
        if len(self._recent_calls) > _MAX_RECENT_CALLS:
            self._recent_calls = self._recent_calls[:_MAX_RECENT_CALLS]  # Keep only last 10

        logger.info("Created call %s (service: %s, provider: %s)", call_code, service, provider)
        return call_state

    def get_call(self, call_code: str) -> CallState | None:
        """Get call state by call code."""
        return self._calls.get(call_code)

    def get_recent_calls(self) -> List[Dict[str, Any]]:
        """Get recent calls with current participant counts."""
        result = []
        for recent_call in self._recent_calls:
            call_state = self._calls.get(recent_call.call_code)
            participant_count = len(call_state.participants) if call_state else 0
            result.append({
                "call_code": recent_call.call_code,
                "service": recent_call.service,
                "provider": recent_call.provider,
                "barge_in": recent_call.barge_in,
                "created_at": recent_call.created_at,
                "participant_count": participant_count,
                "is_active": call_state is not None and len(call_state.participants) > 0,
            })
        return result

    async def add_participant(self, call_code: str, participant_id: str, websocket: WebSocket) -> CallState:
        """Add a participant to a call and establish upstream connection if needed."""
        call_state = self._calls[call_code]
        call_state.participants[participant_id] = websocket

        await call_state.ensure_upstream()

        # Send current participant list to the new participant
        await call_state.send_participant_list(websocket)

        # Broadcast to all participants that someone joined
        await call_state.broadcast_participant_joined(participant_id)
        logger.info("Participant %s joined call %s (%d total participants)",
                   participant_id, call_code, len(call_state.participants))

        return call_state

    async def remove_participant(self, call_state: CallState, participant_id: str) -> None:
        """Remove a participant from the call and clean up if last participant."""
        call_state.participants.pop(participant_id, None)
        logger.info("Participant %s left call %s (%d remaining participants)",
                   participant_id, call_state.call_code, len(call_state.participants))

        # Broadcast to remaining participants that someone left
        if call_state.participants:
            await call_state.broadcast_participant_left(participant_id)

        # Clean up upstream connection if last participant left
        if not call_state.participants and call_state.upstream:
            logger.info("Last participant left call %s, closing upstream connection", call_state.call_code)
            await call_state.upstream.close()
            call_state.upstream = None

from __future__ import annotations

import logging
from typing import Any, Dict

from ....core.event_bus import EventBus
from ....models.provider_events import ProviderOutputEvent
from .base import OpenAIContext, extract_context

logger = logging.getLogger(__name__)


class AudioDoneHandler:
    """Normalize VoiceLive response.audio.done events to ProviderOutputEvent."""

    def __init__(self, inbound_bus: EventBus, seq_counters: Dict[str, int]):
        self.inbound_bus = inbound_bus
        self.seq_counters = seq_counters

    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if this handler can process the given message."""
        message_type = message.get("type") or ""
        return message_type == "response.audio.done"

    async def handle(self, message: Dict[str, Any]) -> None:
        context: OpenAIContext = extract_context(message)
        stream_key = context.stream_id or context.commit_id

        reason = message.get("reason") or message.get("status") or "completed"
        if str(message.get("type", "")).endswith("error"):
            reason = "error"

        error_detail = message.get("error") or message.get("message")
        if reason != "error" and message.get("cancelled"):
            reason = "canceled"

        # Reset sequence counter for the stream
        if stream_key in self.seq_counters:
            del self.seq_counters[stream_key]

        payload = {"reason": reason}
        if error_detail:
            payload["error"] = str(error_detail)

        event = ProviderOutputEvent(
            commit_id=context.commit_id,
            session_id=context.session_id,
            participant_id=context.participant_id,
            event_type="audio.done",
            payload=payload,
            provider="voice_live",
            stream_id=context.stream_id,
            provider_response_id=context.provider_response_id,
            provider_item_id=context.provider_item_id,
        )
        await self.inbound_bus.publish(event)

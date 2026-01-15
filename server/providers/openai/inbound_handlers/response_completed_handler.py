from __future__ import annotations

import logging
from typing import Any, Dict, List

from ....core.event_bus import EventBus
from ....models.provider_events import ProviderOutputEvent
from .base import OpenAIContext, extract_context

logger = logging.getLogger(__name__)


class ResponseCompletedHandler:
    """Emit any buffered translations when a response is marked complete."""

    def __init__(self, inbound_bus: EventBus, text_buffers: Dict[str, List[str]], transcript_buffers: Dict[str, List[str]]):
        self.inbound_bus = inbound_bus
        self.text_buffers = text_buffers
        self.transcript_buffers = transcript_buffers

    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if this handler can process the given message."""
        message_type = message.get("type") or ""
        return message_type == "response.completed"

    async def handle(self, message: Dict[str, Any]) -> None:
        context: OpenAIContext = extract_context(message)
        buffer_key = context.stream_id or context.commit_id
        buffered_text = "".join(self.text_buffers.pop(buffer_key, []))
        buffered_transcript = "".join(self.transcript_buffers.pop(buffer_key, []))
        final_text = buffered_text or buffered_transcript or message.get("text") or ""
        if not final_text:
            logger.debug("VoiceLive response completed without translation payload: %s", message)
            return

        role = "translation" if buffered_text or message.get("text") else "tts_transcript"
        event = ProviderOutputEvent(
            commit_id=context.commit_id,
            session_id=context.session_id,
            participant_id=context.participant_id,
            event_type="transcript.done",
            payload={"text": final_text, "final": True, "role": role},
            provider="voice_live",
            stream_id=context.stream_id,
            provider_response_id=context.provider_response_id,
            provider_item_id=context.provider_item_id,
        )
        await self.inbound_bus.publish(event)

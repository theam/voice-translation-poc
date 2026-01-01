from __future__ import annotations

import logging
from typing import Any, Dict, List

from ....core.event_bus import EventBus
from ....models.provider_events import ProviderOutputEvent
from .base import OpenAIContext, extract_context

logger = logging.getLogger(__name__)


class AudioTranscriptDeltaHandler:
    """Handle incremental transcript deltas from VoiceLive."""

    def __init__(self, inbound_bus: EventBus, transcript_buffers: Dict[str, List[str]]):
        self.inbound_bus = inbound_bus
        self.transcript_buffers = transcript_buffers

    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if this handler can process the given message."""
        message_type = message.get("type") or ""
        return message_type == "response.audio_transcript.delta"

    async def handle(self, message: Dict[str, Any]) -> None:
        context: OpenAIContext = extract_context(message)
        delta = message.get("delta") or message.get("transcript") or ""
        if not delta:
            logger.debug("VoiceLive transcript delta without content: %s", message)
            return

        buffer_key = context.stream_id or context.commit_id
        self.transcript_buffers[buffer_key].append(delta)
        event = ProviderOutputEvent(
            commit_id=context.commit_id,
            session_id=context.session_id,
            participant_id=context.participant_id,
            event_type="transcript.delta",
            payload={"text": delta, "final": False, "role": "tts_transcript"},
            provider="voice_live",
            stream_id=context.stream_id,
            provider_response_id=context.provider_response_id,
            provider_item_id=context.provider_item_id,
        )
        await self.inbound_bus.publish(event)

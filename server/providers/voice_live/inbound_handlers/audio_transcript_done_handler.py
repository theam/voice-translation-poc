from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ....models.messages import ProviderOutputEvent
from .base import VoiceLiveContext, extract_context

logger = logging.getLogger(__name__)


class AudioTranscriptDoneHandler:
    """Handle completion of transcript streaming."""

    def __init__(self, transcript_buffers: Dict[str, List[str]]):
        self.transcript_buffers = transcript_buffers

    async def handle(self, message: Dict[str, Any]) -> Optional[ProviderOutputEvent]:
        context: VoiceLiveContext = extract_context(message)
        buffer_key = context.stream_id or context.commit_id
        buffered_text = "".join(self.transcript_buffers.pop(buffer_key, []))
        final_text = buffered_text or message.get("transcript") or message.get("text") or ""
        if not final_text:
            logger.debug("VoiceLive transcript done without buffered content: %s", message)
            return None

        return ProviderOutputEvent(
            commit_id=context.commit_id,
            session_id=context.session_id,
            participant_id=context.participant_id,
            event_type="transcript.done",
            payload={"text": final_text, "final": True, "role": "tts_transcript"},
            provider="voice_live",
            stream_id=context.stream_id,
            provider_response_id=context.provider_response_id,
            provider_item_id=context.provider_item_id,
        )

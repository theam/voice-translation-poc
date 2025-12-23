from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ....models.messages import ProviderOutputEvent
from .base import VoiceLiveContext, extract_context

logger = logging.getLogger(__name__)


class AudioTranscriptDeltaHandler:
    """Handle incremental transcript deltas from VoiceLive."""

    def __init__(self, transcript_buffers: Dict[str, List[str]]):
        self.transcript_buffers = transcript_buffers

    async def handle(self, message: Dict[str, Any]) -> Optional[ProviderOutputEvent]:
        context: VoiceLiveContext = extract_context(message)
        delta = message.get("delta") or message.get("transcript") or ""
        if not delta:
            logger.debug("VoiceLive transcript delta without content: %s", message)
            return None

        buffer_key = context.stream_id or context.commit_id
        self.transcript_buffers[buffer_key].append(delta)
        return ProviderOutputEvent(
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

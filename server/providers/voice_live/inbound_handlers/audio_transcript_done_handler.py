from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...models.messages import TranslationResponse
from .base import extract_context

logger = logging.getLogger(__name__)


class AudioTranscriptDoneHandler:
    """Handle completion of transcript streaming."""

    def __init__(self, transcript_buffers: Dict[str, List[str]]):
        self.transcript_buffers = transcript_buffers

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        commit_id, session_id, participant_id = extract_context(message)
        buffered_text = "".join(self.transcript_buffers.pop(commit_id, []))
        final_text = buffered_text or message.get("transcript") or message.get("text") or ""
        if not final_text:
            logger.debug("VoiceLive transcript done without buffered content: %s", message)
            return None

        return TranslationResponse(
            commit_id=commit_id,
            session_id=session_id,
            participant_id=participant_id,
            text=final_text,
            partial=False,
        )

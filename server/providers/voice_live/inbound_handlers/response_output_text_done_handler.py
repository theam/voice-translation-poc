from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...models.messages import TranslationResponse
from .base import extract_context

logger = logging.getLogger(__name__)


class ResponseOutputTextDoneHandler:
    """Handle completion of text output by emitting the buffered translation."""

    def __init__(self, text_buffers: Dict[str, List[str]]):
        self.text_buffers = text_buffers

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        commit_id, session_id, participant_id = extract_context(message)
        buffered_text = "".join(self.text_buffers.pop(commit_id, []))
        final_text = buffered_text or message.get("text") or ""
        if not final_text:
            logger.debug("VoiceLive text done without buffered content: %s", message)
            return None

        return TranslationResponse(
            commit_id=commit_id,
            session_id=session_id,
            participant_id=participant_id,
            text=final_text,
            partial=False,
        )

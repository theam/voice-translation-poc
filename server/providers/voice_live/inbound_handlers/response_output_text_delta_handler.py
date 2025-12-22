from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...models.messages import TranslationResponse
from .base import extract_context

logger = logging.getLogger(__name__)


class ResponseOutputTextDeltaHandler:
    """Handle incremental text deltas returned by VoiceLive."""

    def __init__(self, text_buffers: Dict[str, List[str]]):
        self.text_buffers = text_buffers

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        commit_id, session_id, participant_id = extract_context(message)
        delta = message.get("delta") or message.get("text") or ""
        if not delta:
            logger.debug("VoiceLive text delta without content: %s", message)
            return None

        self.text_buffers[commit_id].append(delta)
        return TranslationResponse(
            commit_id=commit_id,
            session_id=session_id,
            participant_id=participant_id,
            text=delta,
            partial=True,
        )

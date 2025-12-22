from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ....models.messages import TranslationResponse
from .base import extract_context

logger = logging.getLogger(__name__)


class AudioTranscriptDeltaHandler:
    """Handle incremental transcript deltas from VoiceLive."""

    def __init__(self, transcript_buffers: Dict[str, List[str]]):
        self.transcript_buffers = transcript_buffers

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        commit_id, session_id, participant_id = extract_context(message)
        delta = message.get("delta") or message.get("transcript") or ""
        if not delta:
            logger.debug("VoiceLive transcript delta without content: %s", message)
            return None

        self.transcript_buffers[commit_id].append(delta)
        return TranslationResponse(
            commit_id=commit_id,
            session_id=session_id,
            participant_id=participant_id,
            text=delta,
            partial=True,
        )

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...models.messages import ProviderOutputEvent

if TYPE_CHECKING:
    from .audio_delta_handler import AudioDeltaHandler

logger = logging.getLogger(__name__)


class AudioDoneHandler:
    """Handles audio.done events from providers."""

    def __init__(self, audio_delta_handler: AudioDeltaHandler):
        self.audio_delta_handler = audio_delta_handler

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Handle audio done event by flushing remaining frames and cleaning up."""
        frame_bytes, format_info = self.audio_delta_handler._frame_config(event)

        # Flush any remaining buffered audio
        await self.audio_delta_handler.flush_and_clear(event, frame_bytes, format_info)

        # Publish audio.done notification
        reason = event.payload.get("reason") if isinstance(event.payload, dict) else None
        error = event.payload.get("error") if isinstance(event.payload, dict) else None
        await self.audio_delta_handler._publish_audio_done(
            event,
            reason=reason or "completed",
            error=error
        )

        logger.info(
            "Audio stream completed for session=%s participant=%s commit=%s",
            event.session_id,
            event.participant_id,
            event.commit_id
        )

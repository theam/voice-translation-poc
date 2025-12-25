from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...models.provider_events import ProviderOutputEvent

if TYPE_CHECKING:
    from .audio_delta_handler import AudioDeltaHandler

logger = logging.getLogger(__name__)


class AudioDoneHandler:
    """Handles audio.done events from providers."""

    def __init__(self, audio_delta_handler: AudioDeltaHandler):
        self.audio_delta_handler = audio_delta_handler

    def can_handle(self, event: ProviderOutputEvent) -> bool:
        """Check if this handler can process the event."""
        return event.event_type == "audio.done"

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Handle audio done by padding to full frames, draining playout, and publishing done."""
        buffer_key = self.audio_delta_handler._buffer_key(event)
        state = self.audio_delta_handler.ensure_state(buffer_key)
        buffer = state.buffer

        frame_bytes = state.frame_bytes or self.audio_delta_handler.chunk_size_for(event)
        if frame_bytes > 0 and buffer and len(buffer) % frame_bytes != 0:
            pad_len = frame_bytes - (len(buffer) % frame_bytes)
            buffer.extend(b"\x00" * pad_len)

        await self.audio_delta_handler.mark_done(buffer_key)
        await self.audio_delta_handler.wait_for_playout(buffer_key)

        # Publish audio.done notification
        reason = event.payload.get("reason") if isinstance(event.payload, dict) else None
        error = event.payload.get("error") if isinstance(event.payload, dict) else None
        await self.audio_delta_handler._publish_audio_done(
            event,
            reason=reason or "completed",
            error=error
        )

        # Clear state for this stream
        self.audio_delta_handler.clear_state(buffer_key)

        logger.info(
            "Audio stream completed for session=%s participant=%s commit=%s",
            event.session_id,
            event.participant_id,
            event.commit_id
        )

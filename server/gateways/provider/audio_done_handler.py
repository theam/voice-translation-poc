from __future__ import annotations

import base64
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

    def can_handle(self, event: ProviderOutputEvent) -> bool:
        """Check if this handler can process the event."""
        return event.event_type == "audio.done"

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Handle audio done event by emitting buffered audio once, then cleaning up."""
        buffer_key = self.audio_delta_handler._buffer_key(event)
        buffer = self.audio_delta_handler.get_buffer(event)

        # Emit aggregated audio for this response
        if buffer:
            source_format = (
                self.audio_delta_handler._format_overrides.get(buffer_key)
                or self.audio_delta_handler._frame_config(event)[1]
            )
            target_format = self.audio_delta_handler._target_format
            audio_bytes = self.audio_delta_handler._resample_audio(
                bytes(buffer),
                int(source_format.get("sample_rate_hz") or 16000),
                int(target_format.get("sample_rate_hz") or 16000),
                int(target_format.get("channels") or 1),
            )
            acs_payload = {
                "kind": "audioData",
                "audioData": {
                    "data": base64.b64encode(audio_bytes).decode("ascii"),
                    "timestamp": None,
                    "participant": None,
                    "isSilent": False,
                },
                "stopAudio": None,
            }
            await self.audio_delta_handler.acs_outbound_bus.publish(acs_payload)

        # Publish audio.done notification
        reason = event.payload.get("reason") if isinstance(event.payload, dict) else None
        error = event.payload.get("error") if isinstance(event.payload, dict) else None
        await self.audio_delta_handler._publish_audio_done(
            event,
            reason=reason or "completed",
            error=error
        )

        # Clear state for this stream
        self.audio_delta_handler.clear_buffer(buffer_key)

        logger.info(
            "Audio stream completed for session=%s participant=%s commit=%s",
            event.session_id,
            event.participant_id,
            event.commit_id
        )

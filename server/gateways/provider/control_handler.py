from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from ...core.event_bus import EventBus
from ...models.messages import ProviderOutputEvent

if TYPE_CHECKING:
    from .audio_delta_handler import AudioDeltaHandler

logger = logging.getLogger(__name__)


class ControlHandler:
    """Handles control events from providers (e.g., stop_audio)."""

    def __init__(
        self,
        acs_outbound_bus: EventBus,
        audio_delta_handler: AudioDeltaHandler
    ):
        self.acs_outbound_bus = acs_outbound_bus
        self.audio_delta_handler = audio_delta_handler

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Handle control event."""
        payload = event.payload or {}
        action = payload.get("action")

        if action != "stop_audio":
            logger.debug("Control event ignored (action=%s)", action)
            return

        # Clear any buffered audio for this stream
        buffer_key = self.audio_delta_handler._buffer_key(event)
        self.audio_delta_handler.clear_buffer(buffer_key)

        # Publish stop_audio control to ACS
        acs_payload = {
            "type": "control.stop_audio",
            "session_id": event.session_id,
            "participant_id": event.participant_id,
            "commit_id": event.commit_id,
            "stream_id": event.stream_id,
            "provider": event.provider,
            "detail": payload.get("detail"),
        }
        await self.acs_outbound_bus.publish(acs_payload)
        logger.info("Published stop_audio control for %s", buffer_key)

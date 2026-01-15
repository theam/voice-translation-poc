from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...core.event_bus import EventBus
from ...models.provider_events import ProviderOutputEvent
from .audio import PacedPlayoutEngine, PlayoutStore

if TYPE_CHECKING:
    from .call_outbound_renderer import ProviderAudioBufferingHandler

logger = logging.getLogger(__name__)


class ControlHandler:
    """Handles control events from providers (e.g., stop_audio)."""

    def __init__(
        self,
        acs_outbound_bus: EventBus,
        audio_buffer_handler: ProviderAudioBufferingHandler,
        playout_store: PlayoutStore,
        playout_engine: PacedPlayoutEngine,
    ):
        self.acs_outbound_bus = acs_outbound_bus
        self.audio_buffer_handler = audio_buffer_handler
        self.store: PlayoutStore = playout_store
        self.playout_engine: PacedPlayoutEngine = playout_engine

    def can_handle(self, event: ProviderOutputEvent) -> bool:
        """Check if this handler can process the event."""
        return event.event_type == "control"

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Handle control event."""
        payload = event.payload or {}
        action = payload.get("action")

        if action != "stop_audio":
            logger.debug("Control event ignored (action=%s)", action)
            return

        # Clear any buffered audio for this stream
        buffer_key = self.audio_buffer_handler.stream_key
        stream = self.store.get(buffer_key)
        if stream:
            await self.playout_engine.pause(stream)
            self.store.remove(buffer_key)
        self.audio_buffer_handler.clear_resampler(event.participant_id or "unknown")
        self.audio_buffer_handler.clear_buffer(event.participant_id)

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

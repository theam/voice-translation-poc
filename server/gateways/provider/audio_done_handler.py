from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...core.event_bus import EventBus
from ...models.outbound_audio import OutboundAudioDoneEvent
from ...models.provider_events import ProviderOutputEvent

if TYPE_CHECKING:
    from .call_outbound_renderer import ProviderAudioBufferingHandler

logger = logging.getLogger(__name__)


class AudioDoneHandler:
    """Handles audio.done events from providers by publishing to the provider audio bus."""

    def __init__(
        self,
        audio_buffer_handler: ProviderAudioBufferingHandler,
        provider_audio_bus: EventBus,
    ):
        self.audio_buffer_handler = audio_buffer_handler
        self.provider_audio_bus = provider_audio_bus

    def can_handle(self, event: ProviderOutputEvent) -> bool:
        """Check if this handler can process the event."""
        return event.event_type == "audio.done"

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Handle audio done by flushing resampler and publishing completion event to the bus."""
        participant_key = event.participant_id or "unknown"

        # Flush any remaining audio from the resampler
        drained = self.audio_buffer_handler.flush_resampler(participant_key)
        if drained:
            buffer = self.audio_buffer_handler.get_or_create_buffer(participant_key)
            buffer.append_audio(drained)

        # Extract completion metadata from event payload
        reason = event.payload.get("reason") if isinstance(event.payload, dict) else None
        error = event.payload.get("error") if isinstance(event.payload, dict) else None

        # Publish audio done event (OutboundPlayoutHandler will handle cleanup)
        await self.provider_audio_bus.publish(
            OutboundAudioDoneEvent(
                session_id=event.session_id,
                participant_id=event.participant_id,
                commit_id=event.commit_id,
                stream_id=event.stream_id,
                provider=event.provider,
                stream_key=self.audio_buffer_handler.stream_key,
                reason=reason or "completed",
                error=error,
            )
        )

        # Clear resampler state for this stream
        self.audio_buffer_handler.clear_resampler(participant_key)

        logger.debug(
            "Published audio done event for session=%s participant=%s commit=%s stream=%s",
            event.session_id,
            event.participant_id,
            event.commit_id,
            self.audio_buffer_handler.stream_key,
        )

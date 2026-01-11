from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...core.event_bus import EventBus
from ...models.outbound_audio import OutboundAudioBytesEvent, OutboundAudioDoneEvent
from ...models.provider_events import ProviderOutputEvent

if TYPE_CHECKING:
    from .audio_delta_handler import AudioDeltaHandler

logger = logging.getLogger(__name__)


class AudioDoneHandler:
    """Handles audio.done events from providers by publishing to the provider audio bus."""

    def __init__(
        self,
        audio_delta_handler: AudioDeltaHandler,
        provider_audio_bus: EventBus,
    ):
        self.audio_delta_handler = audio_delta_handler
        self.stream_key_builder = audio_delta_handler.stream_key_builder
        self.provider_audio_bus = provider_audio_bus

    def can_handle(self, event: ProviderOutputEvent) -> bool:
        """Check if this handler can process the event."""
        return event.event_type == "audio.done"

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Handle audio done by flushing resampler and publishing completion event to the bus."""
        buffer_key = self.stream_key_builder.build(event)

        # Flush any remaining audio from the resampler
        drained = self.audio_delta_handler.flush_resampler(buffer_key)
        if drained:
            # Publish final audio bytes
            target_format = self.audio_delta_handler.target_format
            await self.provider_audio_bus.publish(
                OutboundAudioBytesEvent(
                    session_id=event.session_id,
                    participant_id=getattr(event, "participant_id", None),
                    speaker_id=None,
                    stream_key=buffer_key,
                    audio_bytes=drained,
                    sample_rate_hz=target_format.sample_rate_hz,
                    channels=target_format.channels,
                )
            )

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
                stream_key=buffer_key,
                reason=reason or "completed",
                error=error,
            )
        )

        # Clear resampler state for this stream
        self.audio_delta_handler.clear_resampler(buffer_key)

        logger.debug(
            "Published audio done event for session=%s participant=%s commit=%s stream=%s",
            event.session_id,
            event.participant_id,
            event.commit_id,
            buffer_key,
        )

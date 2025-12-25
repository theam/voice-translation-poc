from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...models.provider_events import ProviderOutputEvent
from .audio import AcsAudioPublisher, PacedPlayoutEngine, PlayoutStore, StreamKeyBuilder

if TYPE_CHECKING:
    from .audio_delta_handler import AudioDeltaHandler

logger = logging.getLogger(__name__)


class AudioDoneHandler:
    """Handles audio.done events from providers."""

    def __init__(
        self,
        audio_delta_handler: AudioDeltaHandler,
    ):
        self.audio_delta_handler = audio_delta_handler
        self.stream_key_builder = audio_delta_handler.stream_key_builder
        self.store: PlayoutStore = audio_delta_handler.store
        self.playout_engine: PacedPlayoutEngine = audio_delta_handler.playout_engine
        self.publisher: AcsAudioPublisher = audio_delta_handler.publisher

    def can_handle(self, event: ProviderOutputEvent) -> bool:
        """Check if this handler can process the event."""
        return event.event_type == "audio.done"

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Handle audio done by padding to full frames, draining playout, and publishing done."""
        buffer_key = self.stream_key_builder.build(event)
        state = self.store.get_or_create(buffer_key, self.audio_delta_handler.target_format, self.audio_delta_handler.frame_bytes)
        buffer = state.buffer

        if state.resampler:
            drained = state.resampler.flush()
            if drained:
                buffer.extend(drained)

        frame_bytes = state.frame_bytes or self.audio_delta_handler.frame_bytes
        if frame_bytes > 0 and buffer and len(buffer) % frame_bytes != 0:
            pad_len = frame_bytes - (len(buffer) % frame_bytes)
            buffer.extend(b"\x00" * pad_len)

        await self.playout_engine.mark_done(state)
        await self.playout_engine.wait(state)

        # Publish audio.done notification
        reason = event.payload.get("reason") if isinstance(event.payload, dict) else None
        error = event.payload.get("error") if isinstance(event.payload, dict) else None
        await self.publisher.publish_audio_done(event, reason=reason or "completed", error=error)

        # Clear state for this stream
        if state.resampler:
            state.resampler.reset()
        self.store.remove(buffer_key)

        logger.info(
            "Audio stream completed for session=%s participant=%s commit=%s",
            event.session_id,
            event.participant_id,
            event.commit_id
        )

from __future__ import annotations

import logging

from ...core.event_bus import EventBus
from ...models.outbound_audio import OutboundAudioBytesEvent, OutboundAudioDoneEvent
from .audio import AcsAudioPublisher, AcsFormatResolver, PacedPlayoutEngine, PlayoutConfig, PlayoutStore
from ..base import Handler

logger = logging.getLogger(__name__)


class OutboundPlayoutHandler(Handler):
    def __init__(
        self,
        acs_outbound_bus: EventBus,
        playout_config: PlayoutConfig | None,
        session_metadata: dict,
    ):
        self.publisher = AcsAudioPublisher(acs_outbound_bus)
        self.store = PlayoutStore()
        self.engine = PacedPlayoutEngine(self.publisher, playout_config)
        self.format_resolver = AcsFormatResolver(session_metadata)

    def can_handle(self, event: OutboundAudioBytesEvent | OutboundAudioDoneEvent) -> bool:
        return isinstance(event, (OutboundAudioBytesEvent, OutboundAudioDoneEvent))

    async def handle(self, event: OutboundAudioBytesEvent | OutboundAudioDoneEvent) -> None:
        if isinstance(event, OutboundAudioBytesEvent):
            await self._handle_audio_bytes(event)
        elif isinstance(event, OutboundAudioDoneEvent):
            await self._handle_audio_done(event)

    async def _handle_audio_bytes(self, event: OutboundAudioBytesEvent) -> None:
        """Handle audio bytes by buffering and starting playout."""
        target_format = self.format_resolver.get_target_format()
        frame_bytes = self.format_resolver.get_frame_bytes(target_format)
        stream = self.store.get_or_create(event.stream_key, target_format, frame_bytes)
        stream.frame_bytes = frame_bytes
        stream.fmt = target_format
        stream.buffer.extend(event.audio_bytes)
        stream.data_ready.set()
        self.engine.ensure_task(stream)

    async def _handle_audio_done(self, event: OutboundAudioDoneEvent) -> None:
        """Handle audio done by padding, draining playout, and publishing completion."""
        target_format = self.format_resolver.get_target_format()
        frame_bytes = self.format_resolver.get_frame_bytes(target_format)
        stream = self.store.get_or_create(event.stream_key, target_format, frame_bytes)
        buffer = stream.buffer

        # Pad to frame boundary if needed
        if frame_bytes > 0 and buffer and len(buffer) % frame_bytes != 0:
            pad_len = frame_bytes - (len(buffer) % frame_bytes)
            buffer.extend(b"\x00" * pad_len)

        # Mark stream as done and wait for playout to complete
        await self.engine.mark_done(stream)
        await self.engine.wait(stream)

        # Publish audio.done notification with original event metadata
        await self.publisher.publish_audio_done(
            session_id=event.session_id,
            participant_id=event.participant_id,
            commit_id=event.commit_id,
            stream_id=event.stream_id,
            provider=event.provider,
            reason=event.reason,
            error=event.error,
        )

        # Clean up stream
        self.store.remove(event.stream_key)

        logger.info(
            "Audio stream completed for session=%s participant=%s commit=%s stream=%s",
            event.session_id,
            event.participant_id,
            event.commit_id,
            event.stream_key,
        )

    async def shutdown(self) -> None:
        for key in list(self.store.keys()):
            stream = self.store.get(key)
            if stream:
                await self.engine.pause(stream)

from __future__ import annotations

from ...core.event_bus import EventBus
from ...models.outbound_audio import OutboundAudioBytesEvent
from .audio import AcsAudioPublisher, AcsFormatResolver, PacedPlayoutEngine, PlayoutConfig, PlayoutStore
from ..base import Handler


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

    def can_handle(self, event: OutboundAudioBytesEvent) -> bool:
        return isinstance(event, OutboundAudioBytesEvent)

    async def handle(self, event: OutboundAudioBytesEvent) -> None:
        target_format = self.format_resolver.get_target_format()
        frame_bytes = self.format_resolver.get_frame_bytes(target_format)
        state = self.store.get_or_create(event.stream_key, target_format, frame_bytes)
        state.frame_bytes = frame_bytes
        state.fmt = target_format
        state.buffer.extend(event.audio_bytes)
        state.data_ready.set()
        self.engine.ensure_task(event.stream_key, state)

    async def shutdown(self) -> None:
        for key in list(self.store.keys()):
            state = self.store.get(key)
            if state:
                await self.engine.cancel(key, state)

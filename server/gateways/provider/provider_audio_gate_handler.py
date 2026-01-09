from __future__ import annotations

from ...core.event_bus import EventBus
from ...models.outbound_audio import OutboundAudioBytesEvent
from ..base import Handler


class ProviderAudioGateHandler(Handler):
    def __init__(self, gated_bus: EventBus):
        self._gated_bus = gated_bus

    def can_handle(self, event: OutboundAudioBytesEvent) -> bool:
        return isinstance(event, OutboundAudioBytesEvent)

    async def handle(self, event: OutboundAudioBytesEvent) -> None:
        await self._gated_bus.publish(event)

    async def shutdown(self) -> None:
        return

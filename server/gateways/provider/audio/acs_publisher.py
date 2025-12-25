from __future__ import annotations

from typing import Any, Dict

from ....audio import Base64AudioCodec
from ....core.event_bus import EventBus
from ....models.provider_events import ProviderOutputEvent


class AcsAudioPublisher:
    """Publishes audioData chunks and audio.done notifications to ACS."""

    def __init__(self, bus: EventBus):
        self.bus = bus

    async def publish_audio_chunk(self, audio_bytes: bytes) -> None:
        payload = {
            "kind": "audioData",
            "audioData": {
                "data": Base64AudioCodec.encode(audio_bytes),
                "timestamp": None,
                "participant": None,
                "isSilent": False,
            },
            "stopAudio": None,
        }
        await self.bus.publish(payload)

    async def publish_audio_done(
        self,
        event: ProviderOutputEvent,
        *,
        reason: str,
        error: str | None,
    ) -> None:
        payload: Dict[str, Any] = {
            "type": "audio.done",
            "session_id": event.session_id,
            "participant_id": event.participant_id,
            "commit_id": event.commit_id,
            "stream_id": event.stream_id,
            "provider": event.provider,
            "reason": reason,
            "error": error,
        }
        await self.bus.publish(payload)

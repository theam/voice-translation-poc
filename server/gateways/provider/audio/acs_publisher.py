from __future__ import annotations

from typing import Any, Dict

from ....audio import Base64AudioCodec
from ....core.event_bus import EventBus


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
        *,
        session_id: str,
        participant_id: str | None,
        commit_id: str | None,
        stream_id: str | None,
        provider: str | None,
        reason: str,
        error: str | None,
    ) -> None:
        """Publish audio.done notification with explicit metadata."""
        payload: Dict[str, Any] = {
            "type": "control.test.response.audio_done",
            "session_id": session_id,
            "participant_id": participant_id,
            "commit_id": commit_id,
            "stream_id": stream_id,
            "provider": provider,
            "reason": reason,
            "error": error,
        }
        await self.bus.publish(payload)

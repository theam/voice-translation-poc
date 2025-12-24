from __future__ import annotations

import base64
import logging
from collections import defaultdict
from typing import Any, Dict

from ...core.event_bus import EventBus
from ...models.messages import ProviderOutputEvent

logger = logging.getLogger(__name__)


class AudioDeltaHandler:
    """Handles audio.delta events from providers."""

    def __init__(
        self,
        acs_outbound_bus: EventBus,
        session_metadata: Dict[str, Any],
    ):
        self.acs_outbound_bus = acs_outbound_bus
        self.session_metadata = session_metadata
        self._audio_buffers: Dict[str, bytearray] = defaultdict(bytearray)
        self._outgoing_seq: Dict[str, int] = defaultdict(int)

    def can_handle(self, event: ProviderOutputEvent) -> bool:
        """Check if this handler can process the event."""
        return event.event_type == "audio.delta"

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Handle audio delta event by buffering and flushing frames."""
        payload = event.payload or {}
        audio_b64 = payload.get("audio_b64")
        if not audio_b64:
            logger.warning("Audio delta missing payload.audio_b64: %s", payload)
            return

        buffer_key = self._buffer_key(event)
        frame_bytes, format_info = self._frame_config(event)

        try:
            audio_bytes = base64.b64decode(audio_b64, validate=False)
        except Exception as exc:
            logger.exception("Failed to decode audio for stream %s: %s", buffer_key, exc)
            await self._publish_audio_done(event, reason="error", error=str(exc))
            return

        self._audio_buffers[buffer_key] += audio_bytes
        seq = payload.get("seq")
        logger.debug(
            "Buffered audio for %s (seq=%s len=%s buffer=%s)",
            buffer_key,
            seq,
            len(audio_bytes),
            len(self._audio_buffers[buffer_key]),
        )

        await self._flush_frames(event, buffer_key, frame_bytes, format_info)

    async def _flush_frames(
        self,
        event: ProviderOutputEvent,
        buffer_key: str,
        frame_bytes: int,
        format_info: Dict[str, Any],
        drain: bool = False,
    ) -> None:
        """Flush complete frames from buffer to ACS."""
        buffer = self._audio_buffers.get(buffer_key, bytearray())

        while len(buffer) >= frame_bytes or (drain and buffer):
            frame = bytes(buffer[:frame_bytes])
            del buffer[:frame_bytes]

            # ACS outbound audio frame (canonical format per spec)
            acs_payload = {
                "kind": "audioData",
                "audioData": {
                    "data": base64.b64encode(frame).decode("ascii"),
                    "timestamp": None,
                    "participant": None,
                    "isSilent": False,
                },
                "stopAudio": None,
            }
            await self.acs_outbound_bus.publish(acs_payload)

            logger.debug(
                "Sent audio frame to ACS (buffer=%s bytes=%s)",
                buffer_key,
                len(frame)
            )

        self._audio_buffers[buffer_key] = buffer

    def _frame_config(self, event: ProviderOutputEvent) -> tuple[int, Dict[str, Any]]:
        """Determine frame size and format from event and session metadata."""
        format_info = {"encoding": "pcm16", "sample_rate_hz": 16000, "channels": 1}
        payload_format = event.payload.get("format") if isinstance(event.payload, dict) else None
        if isinstance(payload_format, dict):
            format_info.update({k: v for k, v in payload_format.items() if v is not None})

        metadata_format = (
            self.session_metadata.get("acs_audio", {}).get("format")
            if isinstance(self.session_metadata, dict)
            else None
        )
        frame_bytes = 0
        if isinstance(metadata_format, dict):
            frame_bytes = int(metadata_format.get("frame_bytes") or 0)
            for key in ("encoding", "sample_rate_hz", "channels"):
                if metadata_format.get(key):
                    format_info[key] = metadata_format[key]

        if frame_bytes <= 0:
            sample_rate = int(format_info.get("sample_rate_hz") or 16000)
            channels = int(format_info.get("channels") or 1)
            frame_bytes = int((sample_rate / 1000) * 20 * channels * 2)

        return frame_bytes, format_info

    def _buffer_key(self, event: ProviderOutputEvent) -> str:
        """Generate unique buffer key for this stream."""
        participant = event.participant_id or "unknown"
        stream = event.stream_id or event.commit_id or "stream"
        return f"{event.session_id}:{participant}:{stream}"

    def _next_outgoing_seq(self, buffer_key: str) -> int:
        """Get next sequence number for this buffer."""
        self._outgoing_seq[buffer_key] = self._outgoing_seq.get(buffer_key, 0) + 1
        return self._outgoing_seq[buffer_key]

    async def _publish_audio_done(
        self,
        event: ProviderOutputEvent,
        *,
        reason: str,
        error: str | None
    ) -> None:
        """Publish audio.done event."""
        payload = {
            "type": "audio.done",
            "session_id": event.session_id,
            "participant_id": event.participant_id,
            "commit_id": event.commit_id,
            "stream_id": event.stream_id,
            "provider": event.provider,
            "reason": reason,
            "error": error,
        }
        await self.acs_outbound_bus.publish(payload)

    def clear_buffer(self, buffer_key: str) -> None:
        """Clear buffer and sequence state for a stream."""
        self._audio_buffers.pop(buffer_key, None)
        self._outgoing_seq.pop(buffer_key, None)

    def get_buffer(self, event: ProviderOutputEvent) -> bytearray:
        """Get buffer for an event's stream."""
        buffer_key = self._buffer_key(event)
        return self._audio_buffers.get(buffer_key, bytearray())

    async def flush_and_clear(
        self,
        event: ProviderOutputEvent,
        frame_bytes: int,
        format_info: Dict[str, Any]
    ) -> None:
        """Flush remaining frames and clear buffer."""
        buffer_key = self._buffer_key(event)
        await self._flush_frames(event, buffer_key, frame_bytes, format_info, drain=True)
        self.clear_buffer(buffer_key)

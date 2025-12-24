from __future__ import annotations

import audioop
import base64
import logging
from collections import defaultdict
from typing import Any, Dict, Optional

from ...core.event_bus import EventBus
from ...models.messages import ProviderOutputEvent

logger = logging.getLogger(__name__)


class AudioDeltaHandler:
    """Buffers provider audio deltas per response and emits once at response completion."""

    def __init__(
        self,
        acs_outbound_bus: EventBus,
        session_metadata: Dict[str, Any],
    ):
        self.acs_outbound_bus = acs_outbound_bus
        self.session_metadata = session_metadata
        self._audio_buffers: Dict[str, bytearray] = defaultdict(bytearray)
        self._format_overrides: Dict[str, Dict[str, Any]] = {}
        self._target_format = self._default_format_from_metadata(session_metadata)

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

        # Capture format per stream if provided
        if frame_bytes and format_info:
            self._format_overrides[buffer_key] = format_info

        self._audio_buffers[buffer_key] += audio_bytes
        seq = payload.get("seq")
        logger.debug(
            "Buffered audio for %s (seq=%s len=%s buffer=%s)",
            buffer_key,
            seq,
            len(audio_bytes),
            len(self._audio_buffers[buffer_key]),
        )

    def _frame_config(self, event: ProviderOutputEvent) -> tuple[int, Dict[str, Any]]:
        """Determine frame size and format from event and session metadata."""
        # Voice Live defaults to 24 kHz pcm16 mono for output if no format is provided.
        format_info = {"encoding": "pcm16", "sample_rate_hz": 24000, "channels": 1}
        payload_format = event.payload.get("format") if isinstance(event.payload, dict) else None
        if isinstance(payload_format, dict):
            format_info.update({k: v for k, v in payload_format.items() if v is not None})

        frame_bytes = 0
        metadata_format = (
            self.session_metadata.get("acs_audio", {}).get("format")
            if isinstance(self.session_metadata, dict)
            else None
        )
        if isinstance(metadata_format, dict):
            frame_bytes = int(metadata_format.get("frame_bytes") or 0)

        if frame_bytes <= 0:
            sample_rate = int(format_info.get("sample_rate_hz") or 16000)
            channels = int(format_info.get("channels") or 1)
            frame_bytes = int((sample_rate / 1000) * 20 * channels * 2)

        return frame_bytes, format_info

    def _default_format_from_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve desired ACS audio format from metadata or defaults."""
        fmt = {"encoding": "pcm16", "sample_rate_hz": 16000, "channels": 1}
        acs_audio = metadata.get("acs_audio") if isinstance(metadata, dict) else None
        meta_fmt = acs_audio.get("format") if isinstance(acs_audio, dict) else None
        if isinstance(meta_fmt, dict):
            fmt.update({k: v for k, v in meta_fmt.items() if v is not None})
        return fmt

    def _resample_audio(
        self,
        audio_bytes: bytes,
        source_rate: int,
        target_rate: int,
        channels: int,
    ) -> bytes:
        """Resample PCM audio to the target rate if needed."""
        if source_rate == target_rate:
            return audio_bytes
        try:
            converted, _ = audioop.ratecv(
                audio_bytes,
                2,  # width (16-bit PCM)
                channels,
                source_rate,
                target_rate,
                None,
            )
            return converted
        except Exception as exc:
            logger.warning("Failed to resample audio (%s -> %s): %s", source_rate, target_rate, exc)
            return audio_bytes

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
        """Clear buffer state for a stream."""
        self._audio_buffers.pop(buffer_key, None)
        self._format_overrides.pop(buffer_key, None)

    def get_buffer(self, event: ProviderOutputEvent) -> bytearray:
        """Get buffer for an event's stream."""
        buffer_key = self._buffer_key(event)
        return self._audio_buffers.get(buffer_key, bytearray())

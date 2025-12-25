from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict

from ...audio import AudioChunker, AudioFormat, Base64AudioCodec, PcmConverter, UnsupportedAudioFormatError
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
        self._chunk_sizes: Dict[str, int] = {}
        self._target_format = self._default_format_from_metadata(session_metadata)
        self._converter = PcmConverter()
        self._chunker = AudioChunker()

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
        chunk_bytes, source_format = self._frame_config(event)

        try:
            audio_bytes = Base64AudioCodec.decode(audio_b64)
        except ValueError as exc:
            logger.exception("Failed to decode audio for stream %s: %s", buffer_key, exc)
            await self._publish_audio_done(event, reason="error", error=str(exc))
            return

        if source_format == self._target_format:
            converted = audio_bytes
        else:
            try:
                converted = self._converter.convert(audio_bytes, source_format, self._target_format)
            except UnsupportedAudioFormatError as exc:
                logger.warning("Unsupported audio format for stream %s: %s", buffer_key, exc)
                await self._publish_audio_done(event, reason="error", error=str(exc))
                return
            except Exception:
                logger.exception("Failed to convert audio for stream %s", buffer_key)
                await self._publish_audio_done(event, reason="error", error="conversion_failed")
                return

        buffer = self._audio_buffers[buffer_key]
        buffer.extend(converted)
        self._chunk_sizes[buffer_key] = chunk_bytes or self._chunk_size_for_format(self._target_format)

        logger.debug(
            "Buffered audio for %s (seq=%s len=%s buffer=%s)",
            buffer_key,
            payload.get("seq"),
            len(converted),
            len(buffer),
        )

        await self._emit_chunks(buffer_key)

    def _chunk_size_for_format(self, fmt: AudioFormat) -> int:
        chunk_size = self._chunker.bytes_for_ms(fmt, 20)
        return chunk_size or fmt.bytes_per_frame()

    def _frame_config(self, event: ProviderOutputEvent) -> tuple[int, AudioFormat]:
        """Determine frame size and format from event and session metadata."""
        # Voice Live defaults to 24 kHz pcm16 mono for output if no format is provided.
        format_info: Dict[str, Any] = {"encoding": "pcm16", "sample_rate_hz": None, "channels": None}
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
            for key in ("sample_rate_hz", "channels", "encoding", "sample_format"):
                if format_info.get(key) is None and metadata_format.get(key) is not None:
                    format_info[key] = metadata_format.get(key)
            try:
                frame_bytes = int(metadata_format.get("frame_bytes") or 0)
            except (TypeError, ValueError):
                frame_bytes = 0

        if format_info.get("sample_rate_hz") is None:
            format_info["sample_rate_hz"] = 24000
        if format_info.get("channels") is None:
            format_info["channels"] = 1

        fmt = self._audio_format_from_dict(format_info)

        chunk_size = self._sanitize_chunk_size(frame_bytes, fmt)
        if chunk_size <= 0:
            chunk_size = self._chunk_size_for_format(fmt)

        return chunk_size, fmt

    def _default_format_from_metadata(self, metadata: Dict[str, Any]) -> AudioFormat:
        """Resolve desired ACS audio format from metadata or defaults."""
        fmt: Dict[str, Any] = {"encoding": "pcm16", "sample_rate_hz": 16000, "channels": 1}
        acs_audio = metadata.get("acs_audio") if isinstance(metadata, dict) else None
        meta_fmt = acs_audio.get("format") if isinstance(acs_audio, dict) else None
        if isinstance(meta_fmt, dict):
            fmt.update({k: v for k, v in meta_fmt.items() if v is not None})
        return self._audio_format_from_dict(fmt)

    def _audio_format_from_dict(self, data: Dict[str, Any]) -> AudioFormat:
        sample_rate = int(data.get("sample_rate_hz") or data.get("sampleRateHz") or 16000)
        channels = int(data.get("channels") or 1)
        sample_format = data.get("encoding") or data.get("sample_format") or "pcm16"
        return AudioFormat(sample_rate_hz=sample_rate, channels=channels, sample_format=sample_format)

    def _sanitize_chunk_size(self, frame_bytes: int, fmt: AudioFormat) -> int:
        if frame_bytes <= 0:
            return 0
        frame_size = fmt.bytes_per_frame()
        if frame_bytes < frame_size:
            return frame_size
        remainder = frame_bytes % frame_size
        return frame_bytes if remainder == 0 else frame_bytes - remainder

    def _buffer_key(self, event: ProviderOutputEvent) -> str:
        """Generate unique buffer key for this stream."""
        participant = event.participant_id or "unknown"
        stream = event.stream_id or event.commit_id or "stream"
        return f"{event.session_id}:{participant}:{stream}"

    async def _emit_chunks(self, buffer_key: str) -> None:
        buffer = self._audio_buffers[buffer_key]
        chunk_size = self._chunk_sizes.get(buffer_key) or self._chunk_size_for_format(self._target_format)
        if chunk_size <= 0:
            return

        while len(buffer) >= chunk_size:
            chunk = bytes(buffer[:chunk_size])
            del buffer[:chunk_size]
            await self._publish_audio_chunk(chunk)

    async def _publish_audio_chunk(self, audio_bytes: bytes) -> None:
        acs_payload = {
            "kind": "audioData",
            "audioData": {
                "data": Base64AudioCodec.encode(audio_bytes),
                "timestamp": None,
                "participant": None,
                "isSilent": False,
            },
            "stopAudio": None,
        }
        await self.acs_outbound_bus.publish(acs_payload)

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
        self._chunk_sizes.pop(buffer_key, None)

    def get_buffer(self, event: ProviderOutputEvent) -> bytearray:
        """Get buffer for an event's stream."""
        buffer_key = self._buffer_key(event)
        return self._audio_buffers.get(buffer_key, bytearray())

    def chunk_size_for(self, event: ProviderOutputEvent) -> int:
        buffer_key = self._buffer_key(event)
        return self._chunk_sizes.get(buffer_key) or self._chunk_size_for_format(self._target_format)

    @property
    def target_format(self) -> AudioFormat:
        return self._target_format

    @property
    def chunker(self) -> AudioChunker:
        return self._chunker

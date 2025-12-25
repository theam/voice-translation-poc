from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict

from ...audio import AudioChunker, AudioFormat, Base64AudioCodec, PcmConverter, UnsupportedAudioFormatError
from ...core.event_bus import EventBus
from ...models.provider_events import ProviderOutputEvent

logger = logging.getLogger(__name__)


@dataclass
class PlayoutState:
    buffer: bytearray
    frame_bytes: int
    fmt: AudioFormat
    done: bool = False
    task: asyncio.Task | None = None
    data_ready: asyncio.Event = field(default_factory=asyncio.Event)


class AudioDeltaHandler:
    """Buffers provider audio deltas per response and emits paced ACS frames."""

    def __init__(
        self,
        acs_outbound_bus: EventBus,
        session_metadata: Dict[str, Any],
    ):
        self.acs_outbound_bus = acs_outbound_bus
        self.session_metadata = session_metadata
        self._converter = PcmConverter()
        self._chunker = AudioChunker()
        self._playouts: Dict[str, PlayoutState] = {}
        self._target_format = self._default_format_from_metadata(session_metadata)
        self._frame_bytes = self._frame_bytes_from_metadata(self._target_format)

    def can_handle(self, event: ProviderOutputEvent) -> bool:
        """Check if this handler can process the event."""
        return event.event_type == "audio.delta"

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Handle audio delta event by buffering converted PCM and scheduling playout."""
        payload = event.payload or {}
        audio_b64 = payload.get("audio_b64")
        if not audio_b64:
            logger.warning("Audio delta missing payload.audio_b64: %s", payload)
            return

        buffer_key = self._buffer_key(event)
        source_format = self._source_format(event)
        state = self._ensure_state(buffer_key)

        try:
            audio_bytes = Base64AudioCodec.decode(audio_b64)
        except ValueError as exc:
            logger.exception("Failed to decode audio for stream %s: %s", buffer_key, exc)
            await self._publish_audio_done(event, reason="error", error=str(exc))
            await self.cancel_stream(buffer_key)
            return

        if source_format == self._target_format:
            converted = audio_bytes
        else:
            try:
                converted = self._converter.convert(audio_bytes, source_format, self._target_format)
            except UnsupportedAudioFormatError as exc:
                logger.warning("Unsupported audio format for stream %s: %s", buffer_key, exc)
                await self._publish_audio_done(event, reason="error", error=str(exc))
                await self.cancel_stream(buffer_key)
                return
            except Exception:
                logger.exception("Failed to convert audio for stream %s", buffer_key)
                await self._publish_audio_done(event, reason="error", error="conversion_failed")
                await self.cancel_stream(buffer_key)
                return

        state.buffer.extend(converted)
        state.data_ready.set()
        logger.debug(
            "Buffered audio for %s (seq=%s len=%s buffer=%s)",
            buffer_key,
            payload.get("seq"),
            len(converted),
            len(state.buffer),
        )

        self._start_playout_task(buffer_key, state)

    def _buffer_key(self, event: ProviderOutputEvent) -> str:
        """Generate unique buffer key for this stream."""
        participant = event.participant_id or "unknown"
        stream = event.stream_id or event.commit_id or "stream"
        return f"{event.session_id}:{participant}:{stream}"

    def _frame_bytes_from_metadata(self, fmt: AudioFormat) -> int:
        meta_fmt = (
            self.session_metadata.get("acs_audio", {}).get("format")
            if isinstance(self.session_metadata, dict)
            else None
        )
        if isinstance(meta_fmt, dict):
            frame_bytes = self._sanitize_frame_bytes(meta_fmt.get("frame_bytes"), fmt)
        else:
            frame_bytes = 0

        if frame_bytes <= 0:
            frame_bytes = self._chunker.bytes_for_ms(fmt, 20)

        frame_bytes = self._sanitize_frame_bytes(frame_bytes, fmt)

        if isinstance(meta_fmt, dict):
            meta_fmt["frame_bytes"] = frame_bytes
        return frame_bytes

    def _sanitize_frame_bytes(self, frame_bytes: Any, fmt: AudioFormat) -> int:
        try:
            value = int(frame_bytes)
        except (TypeError, ValueError):
            return 0
        if value <= 0:
            return 0
        frame_size = fmt.bytes_per_frame()
        if value < frame_size:
            return frame_size
        remainder = value % frame_size
        return value if remainder == 0 else value - remainder

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
        raw_sample_format = data.get("encoding") or data.get("sample_format") or "pcm16"
        sample_format = str(raw_sample_format).lower()
        if sample_format.startswith("pcm"):
            sample_format = "pcm16"
        return AudioFormat(sample_rate_hz=sample_rate, channels=channels, sample_format=sample_format)

    def _source_format(self, event: ProviderOutputEvent) -> AudioFormat:
        """Determine source format from provider payload, falling back to ACS metadata."""
        format_info: Dict[str, Any] = {"encoding": None, "sample_rate_hz": None, "channels": None, "sample_format": None}
        payload_format = event.payload.get("format") if isinstance(event.payload, dict) else None
        if isinstance(payload_format, dict):
            format_info.update({k: v for k, v in payload_format.items() if v is not None})

        if format_info.get("sample_rate_hz") is None:
            format_info["sample_rate_hz"] = self._target_format.sample_rate_hz
        if format_info.get("channels") is None:
            format_info["channels"] = self._target_format.channels
        if format_info.get("encoding") is None and format_info.get("sample_format") is None:
            format_info["encoding"] = self._target_format.sample_format

        return self._audio_format_from_dict(format_info)

    def _ensure_state(self, buffer_key: str) -> PlayoutState:
        state = self._playouts.get(buffer_key)
        if state:
            return state
        state = PlayoutState(buffer=bytearray(), frame_bytes=self._frame_bytes, fmt=self._target_format)
        self._playouts[buffer_key] = state
        return state

    def ensure_state(self, buffer_key: str) -> PlayoutState:
        """Create or fetch playout state for a stream."""
        return self._ensure_state(buffer_key)

    def _start_playout_task(self, buffer_key: str, state: PlayoutState) -> None:
        if state.task and not state.task.done():
            return
        state.task = asyncio.create_task(self._playout_loop(buffer_key, state), name=f"playout-{buffer_key}")

    async def _playout_loop(self, buffer_key: str, state: PlayoutState) -> None:
        """Emit paced 20ms frames to ACS outbound bus."""
        warmup_frames = 3
        next_deadline: float | None = None

        try:
            while True:
                if not state.done and len(state.buffer) < warmup_frames * state.frame_bytes:
                    state.data_ready.clear()
                    await state.data_ready.wait()
                    continue

                if len(state.buffer) >= state.frame_bytes:
                    chunk = bytes(state.buffer[: state.frame_bytes])
                    del state.buffer[: state.frame_bytes]
                    await self._publish_audio_chunk(chunk)

                    now = time.monotonic()
                    next_deadline = (now + 0.02) if next_deadline is None else next_deadline + 0.02
                    sleep_for = next_deadline - time.monotonic()
                    if sleep_for > 0:
                        await asyncio.sleep(sleep_for)
                    continue

                if state.done:
                    break

                state.data_ready.clear()
                await state.data_ready.wait()
        except asyncio.CancelledError:
            logger.info("Playout task cancelled for %s", buffer_key)
            raise
        finally:
            state.task = None

    async def mark_done(self, buffer_key: str) -> None:
        state = self._playouts.get(buffer_key)
        if not state:
            return
        state.done = True
        state.data_ready.set()

    async def cancel_stream(self, buffer_key: str) -> None:
        state = self._playouts.pop(buffer_key, None)
        if not state:
            return
        state.done = True
        state.data_ready.set()
        if state.task and not state.task.done():
            state.task.cancel()
            await asyncio.gather(state.task, return_exceptions=True)

    async def cancel_all(self) -> None:
        keys = list(self._playouts.keys())
        for key in keys:
            await self.cancel_stream(key)

    async def wait_for_playout(self, buffer_key: str) -> None:
        state = self._playouts.get(buffer_key)
        if not state or not state.task:
            return
        await asyncio.gather(state.task, return_exceptions=True)

    def clear_state(self, buffer_key: str) -> None:
        self._playouts.pop(buffer_key, None)

    def get_buffer(self, event: ProviderOutputEvent) -> bytearray:
        """Get buffer for an event's stream (for testing/introspection)."""
        buffer_key = self._buffer_key(event)
        state = self._playouts.get(buffer_key)
        return state.buffer if state else bytearray()

    def chunk_size_for(self, event: ProviderOutputEvent) -> int:
        buffer_key = self._buffer_key(event)
        state = self._playouts.get(buffer_key)
        return state.frame_bytes if state else self._frame_bytes

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

    @property
    def target_format(self) -> AudioFormat:
        return self._target_format

    @property
    def chunker(self) -> AudioChunker:
        return self._chunker

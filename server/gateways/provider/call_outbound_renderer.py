from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional

import numpy as np

from ...audio import PcmConverter, StreamingPcmResampler
from ...core.event_bus import EventBus
from ...models.outbound_audio import OutboundAudioBytesEvent
from ...models.provider_events import ProviderOutputEvent
from ...providers.capabilities import ProviderAudioCapabilities
from .audio import (
    AcsFormatResolver,
    AudioDeltaDecoder,
    AudioDecodingError,
    AudioTranscoder,
    AudioTranscodingError,
    ProviderFormatResolver,
)

logger = logging.getLogger(__name__)


class ParticipantAudioBuffer:
    """Per-participant PCM16 buffer that returns fixed-size frames or silence."""

    def __init__(
        self,
        *,
        participant_id: str,
        sample_rate_hz: int = 16000,
        channels: int = 1,
        sample_width_bytes: int = 2,
        frame_ms: int = 20,
        start_buffer_ms: int = 60,
    ) -> None:
        self.participant_id = participant_id
        self.sample_rate_hz = sample_rate_hz
        self.channels = channels
        self.sample_width_bytes = sample_width_bytes
        self.frame_ms = frame_ms
        self.start_buffer_ms = start_buffer_ms
        self._buffer = bytearray()
        self._started = start_buffer_ms <= 0
        self._frame_bytes = int(
            (sample_rate_hz * frame_ms / 1000.0) * channels * sample_width_bytes
        )
        self._start_buffer_bytes = int(
            (sample_rate_hz * start_buffer_ms / 1000.0) * channels * sample_width_bytes
        )
        self._silence_frame = b"\x00" * self._frame_bytes

    def append_audio(self, pcm16_bytes: bytes) -> None:
        """Append decoded PCM16 audio for this participant."""
        if pcm16_bytes:
            self._buffer.extend(pcm16_bytes)

    def pop_frame(self) -> bytes:
        """Return exactly one frame of audio (frame_ms), silence on underrun."""
        if not self._started:
            if len(self._buffer) < self._start_buffer_bytes:
                return self._silence_frame
            self._started = True

        if len(self._buffer) < self._frame_bytes:
            return self._silence_frame

        frame = bytes(self._buffer[: self._frame_bytes])
        del self._buffer[: self._frame_bytes]
        return frame

    def available_ms(self) -> float:
        """Return buffered audio duration in milliseconds."""
        bytes_per_ms = (
            self.sample_rate_hz * self.channels * self.sample_width_bytes / 1000.0
        )
        if bytes_per_ms <= 0:
            return 0.0
        return float(len(self._buffer) / bytes_per_ms)

    def clear(self) -> None:
        """Drop all buffered audio."""
        self._buffer.clear()
        self._started = self.start_buffer_ms <= 0


class CallOutboundRenderer:
    """Per-call renderer that mixes participant buffers into one outbound stream."""

    def __init__(
        self,
        *,
        call_id: str,
        outbound_bus: EventBus,
        participant_buffers: Dict[str, ParticipantAudioBuffer],
        frame_ms: int = 20,
        sample_rate_hz: int = 16000,
        channels: int = 1,
        stream_key: str = "call_out",
    ) -> None:
        self.call_id = call_id
        self.outbound_bus = outbound_bus
        self.participant_buffers = participant_buffers
        self.frame_ms = frame_ms
        self.sample_rate_hz = sample_rate_hz
        self.channels = channels
        self.stream_key = stream_key
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sequence = 0
        self._frame_bytes = int(sample_rate_hz * channels * 2 * frame_ms / 1000.0)
        self._silence_frame = b"\x00" * self._frame_bytes

    def start(self) -> None:
        """Idempotent: starts renderer task if not already running."""
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"call-outbound-{self.call_id}")
        logger.info("CallOutboundRenderer started for call=%s", self.call_id)

    async def stop(self) -> None:
        """Stops renderer task and resets state."""
        self._running = False
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        self._sequence = 0
        logger.info("CallOutboundRenderer stopped for call=%s", self.call_id)

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        interval = self.frame_ms / 1000.0
        next_deadline = loop.time()
        try:
            while self._running:
                next_deadline += interval
                frame = self._mix_frame()
                await self.outbound_bus.publish(
                    OutboundAudioBytesEvent(
                        session_id=self.call_id,
                        stream_key=self.stream_key,
                        audio_bytes=frame,
                        sample_rate_hz=self.sample_rate_hz,
                        channels=self.channels,
                        sequence_number=self._sequence,
                    )
                )
                self._sequence += 1
                sleep_for = next_deadline - loop.time()
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                else:
                    next_deadline = loop.time()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("CallOutboundRenderer failed for call=%s", self.call_id)

    def _mix_frame(self) -> bytes:
        buffers = list(self.participant_buffers.values())
        if not buffers:
            return self._silence_frame

        frames = [buffer.pop_frame() for buffer in buffers]
        if len(buffers) == 1:
            return frames[0]

        mix = np.zeros(self._frame_bytes // 2, dtype=np.float32)
        for frame in frames:
            samples = np.frombuffer(frame, dtype="<i2").astype(np.float32)
            if samples.size != mix.size:
                padded = np.zeros_like(mix)
                length = min(samples.size, mix.size)
                padded[:length] = samples[:length]
                samples = padded
            mix += samples
        mix /= len(frames)
        np.clip(mix, -32768, 32767, out=mix)
        return mix.astype("<i2").tobytes()


class ProviderAudioBufferingHandler:
    """Buffers provider audio by participant and starts the call-level renderer."""

    def __init__(
        self,
        *,
        call_id: str,
        outbound_bus: EventBus,
        session_metadata: Dict[str, object],
        stream_key: str = "call_out",
        frame_ms: int = 20,
        provider_capabilities: ProviderAudioCapabilities | None = None,
        decoder: AudioDeltaDecoder | None = None,
        transcoder: AudioTranscoder | None = None,
        start_buffer_ms: int = 60,
    ) -> None:
        self.call_id = call_id
        self.outbound_bus = outbound_bus
        self.stream_key = stream_key
        self.frame_ms = frame_ms
        self.start_buffer_ms = start_buffer_ms
        self.participant_buffers: Dict[str, ParticipantAudioBuffer] = {}
        self.acs_format_resolver = AcsFormatResolver(session_metadata)
        default_provider_format = None
        if provider_capabilities:
            default_provider_format = getattr(provider_capabilities, "provider_output_format", None)
        self.provider_format_resolver = ProviderFormatResolver(
            provider_output_format=default_provider_format,
            provider_capabilities=provider_capabilities,
        )
        self.decoder = decoder or AudioDeltaDecoder()
        self.transcoder = transcoder or AudioTranscoder(PcmConverter())
        self._resamplers: dict[str, StreamingPcmResampler] = {}
        self._resampler_configs: dict[str, tuple[int, int, int]] = {}
        target_format = self.acs_format_resolver.get_target_format()
        self.renderer = CallOutboundRenderer(
            call_id=call_id,
            outbound_bus=outbound_bus,
            participant_buffers=self.participant_buffers,
            frame_ms=frame_ms,
            sample_rate_hz=target_format.sample_rate_hz,
            channels=target_format.channels,
            stream_key=stream_key,
        )

    def can_handle(self, event: ProviderOutputEvent) -> bool:
        return event.event_type == "audio.delta"

    async def handle(self, event: ProviderOutputEvent) -> None:
        payload = event.payload or {}
        audio_b64 = payload.get("audio_b64")
        if not audio_b64:
            logger.warning("Audio delta missing payload.audio_b64: %s", payload)
            return

        participant_key = event.participant_id or "unknown"
        target_format = self.acs_format_resolver.get_target_format()
        source_format = self.provider_format_resolver.resolve(event, target_format)
        resampler = None
        if source_format.sample_rate_hz != target_format.sample_rate_hz:
            config = (
                source_format.sample_rate_hz,
                target_format.sample_rate_hz,
                target_format.channels,
            )
            if (
                participant_key not in self._resamplers
                or self._resampler_configs.get(participant_key) != config
            ):
                self._resamplers[participant_key] = StreamingPcmResampler(
                    source_format.sample_rate_hz,
                    target_format.sample_rate_hz,
                    target_format.channels,
                )
                self._resampler_configs[participant_key] = config
            resampler = self._resamplers.get(participant_key)
        else:
            self._resamplers.pop(participant_key, None)
            self._resampler_configs.pop(participant_key, None)

        try:
            audio_bytes = self.decoder.decode(audio_b64)
            converted = self.transcoder.transcode(
                audio_bytes,
                source_format,
                target_format,
                resampler=resampler,
                streaming=True,
            )
        except AudioDecodingError as exc:
            logger.exception("Failed to decode audio for participant %s: %s", participant_key, exc)
            self.clear_resampler(participant_key)
            return
        except AudioTranscodingError as exc:
            logger.warning("Audio transcoding failed for participant %s: %s", participant_key, exc)
            self.clear_resampler(participant_key)
            return

        if converted:
            buffer = self.get_or_create_buffer(participant_key)
            buffer.append_audio(converted)
            self.renderer.start()

    @property
    def target_format(self):
        return self.acs_format_resolver.get_target_format()

    def flush_resampler(self, participant_key: str) -> bytes:
        resampler = self._resamplers.get(participant_key)
        if not resampler:
            return b""
        drained = resampler.flush()
        resampler.reset()
        return drained

    def clear_resampler(self, participant_key: str) -> None:
        self._resamplers.pop(participant_key, None)
        self._resampler_configs.pop(participant_key, None)

    def clear_buffer(self, participant_key: str | None) -> None:
        if participant_key is None:
            for buffer in self.participant_buffers.values():
                buffer.clear()
            return
        buffer = self.participant_buffers.get(participant_key)
        if buffer:
            buffer.clear()

    def get_or_create_buffer(self, participant_key: str) -> ParticipantAudioBuffer:
        buffer = self.participant_buffers.get(participant_key)
        if buffer is None:
            target_format = self.acs_format_resolver.get_target_format()
            buffer = ParticipantAudioBuffer(
                participant_id=participant_key,
                sample_rate_hz=target_format.sample_rate_hz,
                channels=target_format.channels,
                frame_ms=self.frame_ms,
                start_buffer_ms=self.start_buffer_ms,
            )
            self.participant_buffers[participant_key] = buffer
        return buffer

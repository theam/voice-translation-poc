from __future__ import annotations

import logging
from typing import Any, Dict

from ...core.event_bus import EventBus
from ...models.provider_events import ProviderOutputEvent
from ...providers.capabilities import ProviderAudioCapabilities
from .audio import (
    AcsAudioPublisher,
    AcsFormatResolver,
    AudioDeltaDecoder,
    AudioDecodingError,
    AudioTranscoder,
    AudioTranscodingError,
    PacedPlayoutEngine,
    PlayoutConfig,
    PlayoutStore,
    ProviderFormatResolver,
    StreamKeyBuilder,
)
from ...audio import PcmConverter, StreamingPcmResampler

logger = logging.getLogger(__name__)


class AudioDeltaHandler:
    """Buffers provider audio deltas per response and emits paced ACS frames."""

    def __init__(
        self,
        acs_outbound_bus: EventBus,
        session_metadata: Dict[str, Any],
        *,
        stream_key_builder: StreamKeyBuilder | None = None,
        acs_format_resolver: AcsFormatResolver | None = None,
        provider_format_resolver: ProviderFormatResolver | None = None,
        decoder: AudioDeltaDecoder | None = None,
        transcoder: AudioTranscoder | None = None,
        store: PlayoutStore | None = None,
        publisher: AcsAudioPublisher | None = None,
        playout_engine: PacedPlayoutEngine | None = None,
        playout_config: PlayoutConfig | None = None,
        provider_capabilities: ProviderAudioCapabilities | None = None,
        on_stream_start: callable | None = None,
    ):
        self.acs_outbound_bus = acs_outbound_bus
        self.session_metadata = session_metadata
        self.stream_key_builder = stream_key_builder or StreamKeyBuilder()
        self.acs_format_resolver = acs_format_resolver or AcsFormatResolver(session_metadata)
        default_provider_format = None
        if provider_capabilities:
            default_provider_format = getattr(provider_capabilities, "provider_output_format", None)
        self.provider_format_resolver = provider_format_resolver or ProviderFormatResolver(
            provider_output_format=default_provider_format,
            provider_capabilities=provider_capabilities,
        )
        self.decoder = decoder or AudioDeltaDecoder()
        self.transcoder = transcoder or AudioTranscoder(PcmConverter())
        self.store = store or PlayoutStore()
        self.publisher = publisher or AcsAudioPublisher(acs_outbound_bus)
        self.playout_engine = playout_engine or PacedPlayoutEngine(self.publisher, playout_config)
        self._started_keys: set[str] = set()
        self._on_stream_start = on_stream_start

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

        buffer_key = self.stream_key_builder.build(event)
        target_format = self.acs_format_resolver.get_target_format()
        frame_bytes = self.acs_format_resolver.get_frame_bytes(target_format)
        state = self.store.get_or_create(buffer_key, target_format, frame_bytes)
        state.frame_bytes = frame_bytes
        state.fmt = target_format
        source_format = self.provider_format_resolver.resolve(event, target_format)
        resampler = None
        if source_format.sample_rate_hz != target_format.sample_rate_hz:
            resampler = state.resampler
            if (
                resampler is None
                or resampler.src_rate_hz != source_format.sample_rate_hz
                or resampler.dst_rate_hz != target_format.sample_rate_hz
                or resampler.channels != target_format.channels
            ):
                resampler = StreamingPcmResampler(
                    source_format.sample_rate_hz,
                    target_format.sample_rate_hz,
                    target_format.channels,
                )
                state.resampler = resampler

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
            logger.exception("Failed to decode audio for stream %s: %s", buffer_key, exc)
            await self.publisher.publish_audio_done(event, reason="error", error=str(exc))
            await self.playout_engine.cancel(buffer_key, state)
            self.store.remove(buffer_key)
            return
        except AudioTranscodingError as exc:
            logger.warning("Audio transcoding failed for stream %s: %s", buffer_key, exc)
            await self.publisher.publish_audio_done(event, reason="error", error=str(exc))
            await self.playout_engine.cancel(buffer_key, state)
            self.store.remove(buffer_key)
            return

        if source_format.sample_rate_hz != target_format.sample_rate_hz or source_format.channels != target_format.channels:
            logger.debug(
                "Resampling provider->ACS: %sk -> %sk (len %s -> %s)",
                source_format.sample_rate_hz,
                target_format.sample_rate_hz,
                len(audio_bytes),
                len(converted),
            )
        state.buffer.extend(converted)
        state.data_ready.set()
        logger.debug(
            "Buffered audio for %s (seq=%s len=%s buffer=%s)",
            buffer_key,
            payload.get("seq"),
            len(converted),
            len(state.buffer),
        )

        self.playout_engine.ensure_task(buffer_key, state)

        # Notify turn controller when a new outbound stream starts
        if self._on_stream_start and buffer_key not in self._started_keys:
            self._started_keys.add(buffer_key)
            try:
                await self._on_stream_start(event, buffer_key)
            except Exception:
                logger.exception("on_stream_start callback failed for %s", buffer_key)

    def clear_stream(self, buffer_key: str) -> None:
        """Clear bookkeeping for a stream after completion/cancel."""
        self._started_keys.discard(buffer_key)

    @property
    def target_format(self):
        return self.acs_format_resolver.get_target_format()

    @property
    def frame_bytes(self):
        return self.acs_format_resolver.get_frame_bytes(self.target_format)

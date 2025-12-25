from __future__ import annotations

import logging
from typing import Any, Dict

from ...core.event_bus import EventBus
from ...models.provider_events import ProviderOutputEvent
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
from ...audio import PcmConverter

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
    ):
        self.acs_outbound_bus = acs_outbound_bus
        self.session_metadata = session_metadata
        self.stream_key_builder = stream_key_builder or StreamKeyBuilder()
        self.acs_format_resolver = acs_format_resolver or AcsFormatResolver(session_metadata)
        self.provider_format_resolver = provider_format_resolver or ProviderFormatResolver()
        self.decoder = decoder or AudioDeltaDecoder()
        self.transcoder = transcoder or AudioTranscoder(PcmConverter())
        self.store = store or PlayoutStore()
        self.publisher = publisher or AcsAudioPublisher(acs_outbound_bus)
        self.playout_engine = playout_engine or PacedPlayoutEngine(self.publisher, playout_config)

        self._target_format = self.acs_format_resolver.get_target_format()
        self._frame_bytes = self.acs_format_resolver.get_frame_bytes(self._target_format)

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
        target_format = self._target_format
        frame_bytes = self._frame_bytes
        state = self.store.get_or_create(buffer_key, target_format, frame_bytes)
        source_format = self.provider_format_resolver.resolve(event, target_format)

        try:
            audio_bytes = self.decoder.decode(audio_b64)
            converted = self.transcoder.transcode(audio_bytes, source_format, target_format)
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

    @property
    def target_format(self):
        return self._target_format

    @property
    def frame_bytes(self):
        return self._frame_bytes

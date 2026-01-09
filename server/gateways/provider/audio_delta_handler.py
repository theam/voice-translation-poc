from __future__ import annotations

import logging
from typing import Any, Dict

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
    StreamKeyBuilder,
)
from ...audio import PcmConverter, StreamingPcmResampler

logger = logging.getLogger(__name__)


class AudioDeltaHandler:
    """Converts provider audio deltas to ACS target format and publishes bytes events."""

    def __init__(
        self,
        provider_audio_bus: EventBus,
        session_metadata: Dict[str, Any],
        *,
        stream_key_builder: StreamKeyBuilder | None = None,
        acs_format_resolver: AcsFormatResolver | None = None,
        provider_format_resolver: ProviderFormatResolver | None = None,
        decoder: AudioDeltaDecoder | None = None,
        transcoder: AudioTranscoder | None = None,
        provider_capabilities: ProviderAudioCapabilities | None = None,
    ):
        self.provider_audio_bus = provider_audio_bus
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
        self._resamplers: dict[str, StreamingPcmResampler] = {}
        self._resampler_configs: dict[str, tuple[int, int, int]] = {}

    def can_handle(self, event: ProviderOutputEvent) -> bool:
        """Check if this handler can process the event."""
        return event.event_type == "audio.delta"

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Handle audio delta event by converting PCM and publishing bytes."""
        payload = event.payload or {}
        audio_b64 = payload.get("audio_b64")
        if not audio_b64:
            logger.warning("Audio delta missing payload.audio_b64: %s", payload)
            return

        buffer_key = self.stream_key_builder.build(event)
        target_format = self.acs_format_resolver.get_target_format()
        frame_bytes = self.acs_format_resolver.get_frame_bytes(target_format)
        source_format = self.provider_format_resolver.resolve(event, target_format)
        resampler = None
        if source_format.sample_rate_hz != target_format.sample_rate_hz:
            if (
                buffer_key not in self._resamplers
                or self._resampler_configs.get(buffer_key)
                != (source_format.sample_rate_hz, target_format.sample_rate_hz, target_format.channels)
            ):
                resampler = StreamingPcmResampler(
                    source_format.sample_rate_hz,
                    target_format.sample_rate_hz,
                    target_format.channels,
                )
                self._resamplers[buffer_key] = resampler
                self._resampler_configs[buffer_key] = (
                    source_format.sample_rate_hz,
                    target_format.sample_rate_hz,
                    target_format.channels,
                )
            resampler = self._resamplers.get(buffer_key)
        else:
            self._resamplers.pop(buffer_key, None)
            self._resampler_configs.pop(buffer_key, None)

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
            self._resamplers.pop(buffer_key, None)
            self._resampler_configs.pop(buffer_key, None)
            return
        except AudioTranscodingError as exc:
            logger.warning("Audio transcoding failed for stream %s: %s", buffer_key, exc)
            self._resamplers.pop(buffer_key, None)
            self._resampler_configs.pop(buffer_key, None)
            return

        if source_format.sample_rate_hz != target_format.sample_rate_hz or source_format.channels != target_format.channels:
            logger.debug(
                "Resampling provider->ACS: %sk -> %sk (len %s -> %s)",
                source_format.sample_rate_hz,
                target_format.sample_rate_hz,
                len(audio_bytes),
                len(converted),
            )
        logger.debug(
            "Buffered audio for %s (seq=%s len=%s buffer=%s)",
            buffer_key,
            payload.get("seq"),
            len(converted),
            len(converted),
        )

        await self.provider_audio_bus.publish(
            OutboundAudioBytesEvent(
                session_id=event.session_id,
                participant_id=getattr(event, "participant_id", None),
                speaker_id=getattr(event, "speaker_id", None),
                stream_key=buffer_key,
                audio_bytes=converted,
                sample_rate_hz=target_format.sample_rate_hz,
                channels=target_format.channels,
            )
        )

    @property
    def target_format(self):
        return self.acs_format_resolver.get_target_format()

    @property
    def frame_bytes(self):
        return self.acs_format_resolver.get_frame_bytes(self.target_format)

    def flush_resampler(self, buffer_key: str) -> bytes:
        resampler = self._resamplers.get(buffer_key)
        if not resampler:
            return b""
        drained = resampler.flush()
        resampler.reset()
        return drained

    def clear_resampler(self, buffer_key: str) -> None:
        self._resamplers.pop(buffer_key, None)
        self._resampler_configs.pop(buffer_key, None)

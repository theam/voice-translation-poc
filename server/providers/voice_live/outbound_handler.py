from __future__ import annotations

import json
import logging
from typing import Any, Dict

from ...audio import Base64AudioCodec, PcmConverter
from ...core.websocket_server import WebSocketServer
from ...gateways.provider.audio import AcsFormatResolver
from ...models.provider_events import ProviderInputEvent
from ..capabilities import ProviderAudioCapabilities, get_provider_capabilities

logger = logging.getLogger(__name__)


class VoiceLiveOutboundHandler:
    """Handles outbound AudioRequest messages to VoiceLive."""

    def __init__(
        self,
        websocket: WebSocketServer,
        *,
        session_metadata: Dict[str, Any],
        capabilities: ProviderAudioCapabilities | None = None,
        converter: PcmConverter | None = None,
        acs_format_resolver: AcsFormatResolver | None = None,
    ):
        self.websocket = websocket
        self.converter = converter or PcmConverter()
        self.capabilities = capabilities or get_provider_capabilities("voice_live")
        self.acs_format_resolver = acs_format_resolver or AcsFormatResolver(session_metadata)

    @staticmethod
    def _serialize_request(audio_b64: str) -> Dict[str, Any]:
        return {
            "type": "input_audio_buffer.append",
            "audio": audio_b64,
        }

    async def handle(self, event: ProviderInputEvent) -> None:
        """Convert and send audio payload to VoiceLive over the WebSocket connection."""
        try:
            acs_format = self.acs_format_resolver.get_target_format()
            provider_format = self.capabilities.provider_input_format
            try:
                pcm_bytes = Base64AudioCodec.decode(event.b64_audio_string)
            except Exception as exc:
                logger.warning("Failed to decode outbound audio for commit=%s: %s", event.commit_id, exc)
                return

            converted = self.converter.convert(pcm_bytes, acs_format, provider_format)
            if acs_format.sample_rate_hz != provider_format.sample_rate_hz or acs_format.channels != provider_format.channels:
                logger.debug(
                    "Resampling ACS->provider: %sk -> %sk (len %s -> %s)",
                    acs_format.sample_rate_hz,
                    provider_format.sample_rate_hz,
                    len(pcm_bytes),
                    len(converted),
                )

            payload = self._serialize_request(Base64AudioCodec.encode(converted))
            await self.websocket.send(json.dumps(payload))
            logger.info(
                "Sent audio to VoiceLive: commit=%s session=%s bytes=%s",
                event.commit_id,
                event.session_id,
                len(converted),
            )
            logger.debug(
                "VoiceLive outbound detail commit=%s participant=%s ts=%s",
                event.commit_id,
                event.participant_id,
                event.metadata.get("timestamp_utc"),
            )
        except Exception as exc:
            logger.exception(
                "Failed to send audio to VoiceLive: commit=%s error=%s",
                event.commit_id,
                exc,
            )

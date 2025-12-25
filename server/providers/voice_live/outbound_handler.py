from __future__ import annotations

import json
import logging
from typing import Any, Dict

from ...core.websocket_server import WebSocketServer
from ...models.provider_events import ProviderInputEvent

logger = logging.getLogger(__name__)


class VoiceLiveOutboundHandler:
    """Handles outbound AudioRequest messages to VoiceLive."""

    def __init__(self, websocket: WebSocketServer):
        self.websocket = websocket

    @staticmethod
    def _serialize_request(event: ProviderInputEvent) -> Dict[str, Any]:
        return {
            "type": "input_audio_buffer.append",
            "audio": event.b64_audio_string,
        }

    async def handle(self, event: ProviderInputEvent) -> None:
        """Send audio payload to VoiceLive over the WebSocket connection."""
        try:
            payload = self._serialize_request(event)
            await self.websocket.send(json.dumps(payload))
            logger.info(
                "Sent audio to VoiceLive: commit=%s session=%s bytes=%s",
                event.commit_id,
                event.session_id,
                len(event.b64_audio_string),
            )
        except Exception as exc:
            logger.exception(
                "Failed to send audio to VoiceLive: commit=%s error=%s",
                event.commit_id,
                exc,
            )

from __future__ import annotations

import json
import logging
from typing import Any, Dict

import websockets

from ...models.messages import AudioRequest

logger = logging.getLogger(__name__)


class VoiceLiveOutboundHandler:
    """Handles outbound AudioRequest messages to VoiceLive."""

    def __init__(self, websocket: websockets.WebSocketClientProtocol):
        self.websocket = websocket

    @staticmethod
    def _serialize_request(request: AudioRequest) -> Dict[str, Any]:
        return {
            "type": "translate",
            "commit_id": request.commit_id,
            "session_id": request.session_id,
            "participant_id": request.participant_id,
            "audio_data": request.audio_data.decode("utf-8"),
            "metadata": request.metadata,
        }

    async def handle(self, request: AudioRequest) -> None:
        """Send audio payload to VoiceLive over the WebSocket connection."""
        try:
            payload = self._serialize_request(request)
            await self.websocket.send(json.dumps(payload))
            logger.info(
                "Sent audio to VoiceLive: commit=%s session=%s bytes=%s",
                request.commit_id,
                request.session_id,
                len(request.audio_data),
            )
        except Exception as exc:
            logger.exception(
                "Failed to send audio to VoiceLive: commit=%s error=%s",
                request.commit_id,
                exc,
            )

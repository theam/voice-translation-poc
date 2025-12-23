from __future__ import annotations

import logging
import time
from typing import Any, Dict

from ...core.event_bus import EventBus
from ...models.messages import ProviderOutputEvent

logger = logging.getLogger(__name__)


class TranscriptDeltaHandler:
    """Handles transcript.delta events from providers."""

    def __init__(self, acs_outbound_bus: EventBus):
        self.acs_outbound_bus = acs_outbound_bus

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Handle transcript delta event by publishing partial translation result."""
        payload = event.payload or {}
        text = payload.get("text")
        if not text:
            logger.debug("Transcript delta event missing text: %s", payload)
            return

        # Publish partial translation result
        translation_payload = {
            #"type": "control.test.response.text_delta",
            "type": "translation.text_delta",
            "session_id": event.session_id,
            "participant_id": event.participant_id,
            "commit_id": event.commit_id,
            "stream_id": event.stream_id,
            "provider": event.provider,
            "text": text,
            "timestamp_ms": event.timestamp_ms or int(time.time() * 1000),
        }
        await self.acs_outbound_bus.publish(translation_payload)

        logger.info(
            "Published translation delta for session=%s participant=%s",
            event.session_id,
            event.participant_id
        )

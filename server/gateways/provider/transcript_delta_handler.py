from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from ...core.event_bus import EventBus
from ...models.provider_events import ProviderOutputEvent

logger = logging.getLogger(__name__)


class TranscriptDeltaHandler:
    """Handles transcript.delta events from providers."""

    def __init__(self, acs_outbound_bus: EventBus):
        self.acs_outbound_bus = acs_outbound_bus

    def can_handle(self, event: ProviderOutputEvent) -> bool:
        """Check if this handler can process the event."""
        return event.event_type == "transcript.delta"

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Handle transcript delta event by publishing incremental translation update."""
        payload = event.payload or {}
        text = payload.get("text")
        if not text:
            logger.debug("Transcript delta event missing text: %s", payload)
            return

        # Generate ISO 8601 timestamp
        timestamp = datetime.now(timezone.utc).isoformat()

        # Publish incremental translation delta
        translation_payload = {
            "type": "control.test.response.text_delta",
            "participant_id": event.participant_id,
            "delta": text,
            "timestamp": timestamp,
        }
        await self.acs_outbound_bus.publish(translation_payload)

        logger.info(
            "Published translation delta for session=%s participant=%s",
            event.session_id,
            event.participant_id
        )

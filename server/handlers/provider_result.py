from __future__ import annotations

import logging
from typing import Any, Dict

from ..core.event_bus import EventBus
from ..models.messages import TranslationResponse
from .base import Handler, HandlerSettings

logger = logging.getLogger(__name__)


class ProviderResultHandler(Handler):
    """
    Handles translation results from provider.
    Receives TranslationResponse from provider_inbound_bus and
    publishes to acs_outbound_bus for egress to ACS.
    """

    def __init__(self, settings: HandlerSettings, acs_outbound_bus: EventBus):
        super().__init__(settings)
        self.acs_outbound_bus = acs_outbound_bus

    async def handle(self, response: TranslationResponse) -> None:
        logger.info(
            "Provider result partial=%s session=%s participant=%s commit=%s text=%s",
            response.partial,
            response.session_id,
            response.participant_id,
            response.commit_id,
            response.text,
        )

        # Convert to ACS payload format
        payload = self._to_acs_payload(response)

        # Publish to ACS outbound bus
        await self.acs_outbound_bus.publish(payload)

    def _to_acs_payload(self, response: TranslationResponse) -> Dict[str, Any]:
        """Convert TranslationResponse to ACS egress payload format."""
        return {
            "type": "translation.result",
            "partial": response.partial,
            "session_id": response.session_id,
            "participant_id": response.participant_id,
            "commit_id": response.commit_id,
            "text": response.text,
        }


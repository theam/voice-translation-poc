"""Handler for sending messages to ACS egress."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..adapters.egress import ACSEgressAdapter
from .base import Handler, HandlerSettings

logger = logging.getLogger(__name__)


class ACSEgressHandler(Handler):
    """
    Handles outgoing messages to ACS.
    Consumes payloads from acs_outbound_bus and sends via ACS egress adapter.
    """

    def __init__(self, settings: HandlerSettings, egress_adapter: Optional[ACSEgressAdapter] = None):
        super().__init__(settings)
        self.egress_adapter = egress_adapter

    async def handle(self, payload: Dict[str, Any]) -> None:
        """
        Send payload to ACS egress adapter.

        Args:
            payload: Dictionary containing the message to send to ACS
        """
        if not self.egress_adapter:
            logger.warning("No egress adapter configured, dropping payload: %s", payload.get("type"))
            return

        try:
            await self.egress_adapter.send(payload)
            logger.debug(
                "Sent to ACS egress: type=%s session=%s",
                payload.get("type"),
                payload.get("session_id")
            )
        except Exception as e:
            logger.exception(
                "Failed to send to ACS egress: type=%s error=%s",
                payload.get("type"),
                e
            )

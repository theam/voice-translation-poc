from __future__ import annotations

import logging

from ...models.envelope import Envelope

logger = logging.getLogger(__name__)


class ControlMessageHandler:
    """Handles control messages from ACS."""

    async def handle(self, envelope: Envelope) -> None:
        """Handle control envelope."""
        logger.info("Control event received: %s", envelope.message_id)

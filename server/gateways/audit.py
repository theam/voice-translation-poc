from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from ..models.gateway_input_event import GatewayInputEvent
from ..services.payload_capture import PayloadCapture
from .base import Handler, HandlerSettings

logger = logging.getLogger(__name__)


class AuditHandler(Handler):
    """Non-blocking audit handler with optional payload capture."""

    def __init__(self, settings: HandlerSettings, payload_capture: Optional[PayloadCapture] = None):
        super().__init__(settings)
        self.payload_capture = payload_capture

    async def handle(self, event: GatewayInputEvent) -> None:
        logger.debug(
            "Audit event %s session=%s source=%s",
            event.event_id,
            event.session_id,
            event.source,
        )
        if self.payload_capture:
            await self.payload_capture.capture(event)

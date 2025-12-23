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

    async def handle(self, envelope: GatewayInputEvent) -> None:
        logger.info(
            "Audit event %s type=%s session=%s participant=%s",
            envelope.event_id,
            envelope.event_type,
            envelope.session_id,
            envelope.participant_id,
        )
        if self.payload_capture:
            await self.payload_capture.capture(envelope)

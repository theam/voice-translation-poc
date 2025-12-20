from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from ..models.envelope import Envelope
from ..services.payload_capture import PayloadCapture
from .base import Handler, HandlerSettings

logger = logging.getLogger(__name__)


class AuditHandler(Handler):
    """Non-blocking audit handler with optional payload capture."""

    def __init__(self, settings: HandlerSettings, payload_capture: Optional[PayloadCapture] = None):
        super().__init__(settings)
        self.payload_capture = payload_capture

    async def handle(self, envelope: Envelope) -> None:
        logger.info(
            "Audit event %s type=%s session=%s participant=%s commit=%s",
            envelope.message_id,
            envelope.type,
            envelope.session_id,
            envelope.participant_id,
            envelope.commit_id,
        )
        if self.payload_capture:
            await self.payload_capture.capture(envelope)


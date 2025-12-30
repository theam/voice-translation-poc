from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ....models.provider_events import ProviderOutputEvent

logger = logging.getLogger(__name__)


class LoggingOnlyHandler:
    """Handler for messages where we don't yet translate payloads."""

    def __init__(self, name: str):
        self.name = name

    async def handle(self, message: Dict[str, Any]) -> Optional[ProviderOutputEvent]:
        logger.debug("VoiceLive handler '%s' received payload with no action: %s", self.name, message)
        return None

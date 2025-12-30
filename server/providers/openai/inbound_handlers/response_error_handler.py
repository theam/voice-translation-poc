from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ....models.provider_events import ProviderOutputEvent

logger = logging.getLogger(__name__)


class ResponseErrorHandler:
    """Handle error messages from VoiceLive."""

    async def handle(self, message: Dict[str, Any]) -> Optional[ProviderOutputEvent]:
        logger.error("VoiceLive error message received: %s", message)
        return None

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ....models.messages import TranslationResponse

logger = logging.getLogger(__name__)


class UnknownMessageHandler:
    """Fallback handler for unrecognized message types."""

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        logger.debug("VoiceLive unknown message type received: %s", message)
        return None

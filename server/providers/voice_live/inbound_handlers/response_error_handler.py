from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ...models.messages import TranslationResponse

logger = logging.getLogger(__name__)


class ResponseErrorHandler:
    """Handle error messages from VoiceLive."""

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        logger.error("VoiceLive error message received: %s", message)
        return None

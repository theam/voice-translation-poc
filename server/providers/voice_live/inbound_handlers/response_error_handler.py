from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ResponseErrorHandler:
    """Handle error messages from VoiceLive."""

    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if this handler can process the given message."""
        message_type = message.get("type") or ""
        return message_type in ("response.error", "error")

    async def handle(self, message: Dict[str, Any]) -> None:
        logger.error("VoiceLive error message received: %s", message)

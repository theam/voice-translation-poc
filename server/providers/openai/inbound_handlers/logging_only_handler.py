from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class LoggingOnlyHandler:
    """Default handler for messages where we don't yet translate payloads."""

    def can_handle(self, message: Dict[str, Any]) -> bool:
        """This handler accepts all messages as the catch-all default."""
        return True

    async def handle(self, message: Dict[str, Any]) -> None:
        message_type = message.get("type") or "unknown"
        logger.debug("OpenAI message type '%s' received with no action: %s", message_type, message)

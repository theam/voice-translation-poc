"""Translation text delta message handler.

Handles messages with type="translation.text_delta" containing incremental text updates.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from production.acs_emulator.message_handlers.base import MessageHandler
from production.acs_emulator.models import TranslationTextDelta
from production.acs_emulator.protocol_adapter import ProtocolEvent

if TYPE_CHECKING:
    from production.acs_emulator.protocol_adapter import ProtocolAdapter


logger = logging.getLogger(__name__)


class TextDeltaHandler(MessageHandler):
    """Handler for translation.text_delta messages.

    Decodes incremental text delta messages and buffers them to reconstruct
    complete translations. Maintains per-participant or per-language-pair buffers.
    """

    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if message is a translation.text_delta message.

        Args:
            message: Raw message dictionary from WebSocket

        Returns:
            True if message has type="translation.text_delta"
        """
        return message.get("type") == "translation.text_delta"

    def decode(self, message: Dict[str, Any]) -> ProtocolEvent:
        """Decode translation.text_delta message to ProtocolEvent.

        Buffers incremental text deltas to reconstruct complete translations.
        The buffered text accumulates across multiple delta messages for the
        same participant or language pair.

        Args:
            message: Raw message dictionary from WebSocket

        Returns:
            ProtocolEvent with translated_text type and buffered text
        """
        delta = TranslationTextDelta.from_dict(message)

        # Create buffer key from participant or language pair
        lang_key = (
            f"{delta.source_language or ''}->{delta.target_language or ''}"
            if delta.source_language or delta.target_language
            else None
        )
        buffer_key = delta.participant_id or lang_key or "default"

        # Buffer the delta
        buffered_text = self.adapter._transcript_buffers.get(buffer_key, "") + delta.delta
        self.adapter._transcript_buffers[buffer_key] = buffered_text

        event = ProtocolEvent(
            event_type="translated_delta",
            participant_id=delta.participant_id,
            source_language=delta.source_language,
            target_language=delta.target_language,
            timestamp_ms=delta.timestamp_ms,
            text=delta.delta,
            raw=delta.raw,
        )

        logger.debug("Decoded translation.text_delta event; buffered_text='%s'", buffered_text)
        return event


__all__ = ["TextDeltaHandler"]

"""Transcript message handler.

Handles messages with type="transcript" containing complete transcription results.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from production.acs_emulator.message_handlers.base import MessageHandler
from production.acs_emulator.models import AcsTranscriptMessage
from production.acs_emulator.protocol_adapter import ProtocolEvent

if TYPE_CHECKING:
    from production.acs_emulator.protocol_adapter import ProtocolAdapter


logger = logging.getLogger(__name__)


class TranscriptHandler(MessageHandler):
    """Handler for transcript messages (type="transcript").

    Decodes complete transcript messages containing translated text with
    source/target language information and participant details.
    """

    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if message is a transcript message.

        Args:
            message: Raw message dictionary from WebSocket

        Returns:
            True if message has type="transcript"
        """
        return message.get("type") == "transcript"

    def decode(self, message: Dict[str, Any]) -> ProtocolEvent:
        """Decode transcript message to ProtocolEvent.

        Args:
            message: Raw message dictionary from WebSocket

        Returns:
            ProtocolEvent with translated_text type and transcript data
        """
        transcript = AcsTranscriptMessage.from_dict(message)

        event = ProtocolEvent(
            event_type="translated_text",
            participant_id=transcript.participant_id,
            source_language=transcript.source_language,
            target_language=transcript.target_language,
            timestamp_ms=transcript.timestamp_ms,
            text=transcript.text,
            raw=message,
        )

        logger.debug("Decoded transcript event: %s", transcript)
        return event


__all__ = ["TranscriptHandler"]

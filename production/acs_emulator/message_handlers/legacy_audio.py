"""Legacy audio message handler.

Handles legacy audio messages with type="audio" (non-ACS format).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from production.acs_emulator.message_handlers.base import MessageHandler
from production.acs_emulator.models import AcsAudioMessage
from production.acs_emulator.protocol_adapter import ProtocolEvent

if TYPE_CHECKING:
    from production.acs_emulator.protocol_adapter import ProtocolAdapter


logger = logging.getLogger(__name__)


class LegacyAudioHandler(MessageHandler):
    """Handler for legacy audio messages (type="audio").

    Decodes legacy audio messages that don't follow the ACS AudioData format.
    Maintained for backward compatibility with older protocol versions.
    """

    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if message is a legacy audio message.

        Args:
            message: Raw message dictionary from WebSocket

        Returns:
            True if message has type="audio"
        """
        return message.get("type") == "audio"

    def decode(self, message: Dict[str, Any]) -> ProtocolEvent:
        """Decode legacy audio message to ProtocolEvent.

        Args:
            message: Raw message dictionary from WebSocket

        Returns:
            ProtocolEvent with translated_audio type and audio payload
        """
        audio = AcsAudioMessage.from_dict(message)

        event = ProtocolEvent(
            event_type="translated_audio",
            participant_id=audio.participant_raw_id,
            source_language=None,
            target_language=None,
            timestamp_ms=0,
            audio_payload=audio.data,
            raw=message,
        )

        logger.debug("Decoded legacy audio event for participant %s", audio.participant_raw_id)
        return event


__all__ = ["LegacyAudioHandler"]

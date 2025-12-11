"""AudioMetadata message handler.

Handles messages with kind="AudioMetadata" containing audio configuration.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from production.acs_emulator.message_handlers.base import MessageHandler
from production.acs_emulator.models import AcsAudioMetadata
from production.acs_emulator.protocol_adapter import ProtocolEvent

if TYPE_CHECKING:
    from production.acs_emulator.protocol_adapter import ProtocolAdapter


logger = logging.getLogger(__name__)


class AudioMetadataHandler(MessageHandler):
    """Handler for AudioMetadata messages (kind="AudioMetadata").

    Decodes ACS-style AudioMetadata messages containing audio configuration
    such as sample rate, channels, and encoding format.
    """

    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if message is an AudioMetadata message.

        Args:
            message: Raw message dictionary from WebSocket

        Returns:
            True if message has kind="AudioMetadata"
        """
        return message.get("kind") == "AudioMetadata"

    def decode(self, message: Dict[str, Any]) -> ProtocolEvent:
        """Decode AudioMetadata message to ProtocolEvent.

        Args:
            message: Raw message dictionary from WebSocket

        Returns:
            ProtocolEvent with metadata type
        """
        metadata = AcsAudioMetadata.from_dict(message)

        event = ProtocolEvent(
            event_type="metadata",
            participant_id=None,
            source_language=None,
            target_language=None,
            timestamp_ms=0,
            raw={"audioMetadata": metadata.to_dict().get("audioMetadata", {})},
        )

        logger.debug("Decoded ACS-style AudioMetadata event: %s", metadata)
        return event


__all__ = ["AudioMetadataHandler"]

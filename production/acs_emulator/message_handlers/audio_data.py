"""AudioData message handler.

Handles messages with kind="AudioData" containing translated audio payloads.
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


class AudioDataHandler(MessageHandler):
    """Handler for AudioData messages (kind="AudioData").

    Decodes ACS-style AudioData messages containing translated audio payloads.
    These messages include PCM audio data, participant information, and timestamps.
    """

    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if message is an AudioData message.

        Args:
            message: Raw message dictionary from WebSocket

        Returns:
            True if message has kind="AudioData"
        """
        return str(message.get("kind", "")).lower() == "audiodata"

    def decode(self, message: Dict[str, Any]) -> ProtocolEvent:
        """Decode AudioData message to ProtocolEvent.

        Args:
            message: Raw message dictionary from WebSocket

        Returns:
            ProtocolEvent with translated_audio type and audio payload
        """
        audio = AcsAudioMessage.from_dict(message)
        timestamp_ms = self._parse_iso_to_ms(audio.timestamp)

        event = ProtocolEvent(
            event_type="translated_audio",
            participant_id=audio.play_to_participant or audio.participant_raw_id,
            source_language=None,
            target_language=None,
            timestamp_ms=timestamp_ms,
            audio_payload=audio.data,
            raw=message,
        )

        logger.debug("Decoded ACS-style AudioData event")
        return event

    def _parse_iso_to_ms(self, timestamp: str | None) -> int | None:
        """Parse ISO timestamp to milliseconds.

        Args:
            timestamp: ISO timestamp string

        Returns:
            Timestamp in milliseconds or None if invalid
        """
        if not timestamp:
            return None
        try:
            from datetime import datetime
            return int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return None


__all__ = ["AudioDataHandler"]

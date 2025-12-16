"""ACS protocol adapter encodes/decodes messages for the emulator."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from production.acs_emulator.models import AcsAudioMessage, AcsAudioMetadata, AcsTranscriptMessage, TranslationTextDelta, _iso_timestamp

logger = logging.getLogger(__name__)


@dataclass
class ProtocolEvent:
    event_type: str
    participant_id: Optional[str]
    source_language: Optional[str]
    target_language: Optional[str]
    timestamp_ms: int
    text: Optional[str] = None
    audio_payload: Optional[bytes] = None
    raw: Optional[Dict[str, Any]] = None


class ProtocolAdapter:
    """Translate between internal events and ACS JSON messages."""

    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        self.subscription_id = str(uuid.uuid4())
        self._transcript_buffers: dict[str, str] = {}
        self._message_handlers: Optional[List] = None

    def build_audio_metadata(self, sample_rate: int, channels: int, frame_bytes: int) -> Dict[str, Any]:
        metadata = AcsAudioMetadata(
            subscription_id=self.subscription_id,
            encoding="PCM",
            sample_rate=sample_rate,
            channels=channels,
            length=frame_bytes,
        )
        payload = metadata.to_dict()
        logger.debug("Built ACS AudioMetadata message: %s", json.dumps(payload))
        return payload

    def build_audio_message(
        self,
        participant_id: str,
        pcm_bytes: bytes,
        timestamp_ms: int,
        silent: bool = False,
    ) -> Dict[str, Any]:
        message = AcsAudioMessage(
            participant_raw_id=participant_id,
            data=pcm_bytes,
            timestamp=_iso_timestamp(timestamp_ms),
            silent=silent,
        )
        payload = message.to_dict()
        logger.debug("Built ACS AudioData message: %s", json.dumps({**payload, "audioData": {**payload["audioData"], "data": "<omitted>"}}))
        return payload

    def build_outbound_audio(self, pcm_bytes: bytes, play_to: str = "all", silent: bool = False) -> Dict[str, Any]:
        """Construct an outbound AudioData payload for bidirectional scenarios."""

        message = AcsAudioMessage(data=pcm_bytes, play_to_participant=play_to, silent=silent)
        payload = message.to_dict()
        logger.debug(
            "Built outbound ACS AudioData message: %s", json.dumps({**payload, "audioData": {**payload["audioData"], "data": "<omitted>"}})
        )
        return payload

    @property
    def message_handlers(self) -> List:
        """Get message handlers (lazy-loads if not already created).

        Returns:
            List of message handlers in priority order
        """
        if self._message_handlers is None:
            from production.acs_emulator.message_handlers import get_message_handlers
            self._message_handlers = get_message_handlers(self)
        return self._message_handlers

    def decode_inbound(self, message: Dict[str, Any]) -> Optional[ProtocolEvent]:
        """Decode inbound SUT messages to structured events.

        Uses a chain of message handlers to decode different message types.
        Each handler checks if it can handle the message, and the first match
        processes it. The UnknownMessageHandler serves as a fallback.

        Args:
            message: Raw message dictionary from WebSocket

        Returns:
            ProtocolEvent containing structured event data, or None if the message
            cannot be decoded (safety fallback when no handler matches)
        """
        for handler in self.message_handlers:
            if handler.can_handle(message):
                return handler.decode(message)

        # This should never be reached since UnknownMessageHandler accepts all messages,
        # but include as a safety fallback
        logger.debug("Unknown message type - ignoring: %s", message)
        return None


__all__ = ["ProtocolAdapter", "ProtocolEvent"]

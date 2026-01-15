from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ....core.event_bus import EventBus
from ....models.provider_events import ProviderOutputEvent
from .base import OpenAIContext, extract_context

logger = logging.getLogger(__name__)


class AudioDeltaHandler:
    """Normalize VoiceLive response.audio.delta events to ProviderOutputEvent."""

    def __init__(self, inbound_bus: EventBus, seq_counters: Dict[str, int], default_format: Dict[str, Any]):
        self.inbound_bus = inbound_bus
        self.seq_counters = seq_counters
        self.default_format = default_format

    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if this handler can process the given message."""
        message_type = message.get("type") or ""
        return message_type in ("response.audio.delta", "response.output_audio.delta")

    async def handle(self, message: Dict[str, Any]) -> None:
        context: OpenAIContext = extract_context(message)
        audio_b64 = message.get("delta") or message.get("audio") or message.get("audio_b64")
        if not audio_b64:
            logger.debug("VoiceLive audio delta without audio content: %s", message)
            return

        stream_key = context.stream_id or context.commit_id
        seq = self._next_seq(stream_key)

        format_info = self._resolve_format(message)
        payload = {
            "audio_b64": audio_b64,
            "seq": seq,
            "format": format_info,
        }

        event = ProviderOutputEvent(
            commit_id=context.commit_id,
            session_id=context.session_id,
            participant_id=context.participant_id,
            event_type="audio.delta",
            payload=payload,
            provider="voice_live",
            stream_id=context.stream_id,
            provider_response_id=context.provider_response_id,
            provider_item_id=context.provider_item_id,
        )
        await self.inbound_bus.publish(event)

    def _next_seq(self, stream_key: Optional[str]) -> int:
        key = stream_key or "default"
        self.seq_counters[key] = self.seq_counters.get(key, 0) + 1
        return self.seq_counters[key]

    def _resolve_format(self, message: Dict[str, Any]) -> Dict[str, Any]:
        candidate = message.get("format")
        if isinstance(candidate, dict):
            merged = dict(self.default_format)
            merged.update({k: v for k, v in candidate.items() if v is not None})
            return merged
        return dict(self.default_format)

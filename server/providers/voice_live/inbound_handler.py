from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from ...core.event_bus import EventBus
from .inbound_handlers import (
    AudioTranscriptDeltaHandler,
    AudioTranscriptDoneHandler,
    LoggingOnlyHandler,
    ResponseCompletedHandler,
    ResponseErrorHandler,
    ResponseOutputTextDeltaHandler,
    ResponseOutputTextDoneHandler,
    VoiceLiveMessageHandler,
)


class VoiceLiveInboundHandler:
    """Dispatch VoiceLive messages to dedicated handlers and publish translations."""

    def __init__(self, inbound_bus: EventBus):
        self.inbound_bus = inbound_bus
        self.text_buffers: Dict[str, List[str]] = defaultdict(list)
        self.transcript_buffers: Dict[str, List[str]] = defaultdict(list)
        self._handlers: Dict[str, VoiceLiveMessageHandler] = {
            "response.output_text.delta": ResponseOutputTextDeltaHandler(self.text_buffers),
            "response.output_text.done": ResponseOutputTextDoneHandler(self.text_buffers),
            "response.completed": ResponseCompletedHandler(self.text_buffers, self.transcript_buffers),
            "response.audio_transcript.delta": AudioTranscriptDeltaHandler(self.transcript_buffers),
            "response.audio_transcript.done": AudioTranscriptDoneHandler(self.transcript_buffers),
            "response.audio.delta": LoggingOnlyHandler("response.audio.delta"),
            "response.output_audio.delta": LoggingOnlyHandler("response.output_audio.delta"),
            "response.created": LoggingOnlyHandler("response.created"),
            "response.error": ResponseErrorHandler(),
            "error": ResponseErrorHandler(),
            "input_audio_buffer.committed": LoggingOnlyHandler("input_audio_buffer.committed"),
            "input_audio_buffer.speech.started": LoggingOnlyHandler("input_audio_buffer.speech.started"),
            "input_audio_buffer.speech.stopped": LoggingOnlyHandler("input_audio_buffer.speech.stopped"),
            "input_audio_buffer.speech.recognized": LoggingOnlyHandler("input_audio_buffer.speech.recognized"),
            "conversation.item.created": LoggingOnlyHandler("conversation.item.created"),
            "response.output_item.added": LoggingOnlyHandler("response.output_item.added"),
            "session.created": LoggingOnlyHandler("session.created"),
            "session.updated": LoggingOnlyHandler("session.updated"),
        }
        self._default_handler: VoiceLiveMessageHandler = LoggingOnlyHandler("unknown")

    async def handle(self, message: Dict[str, Any]) -> None:
        """Dispatch to a handler and publish any resulting translation."""
        message_type = message.get("type") or ""
        handler = self._handlers.get(message_type, self._default_handler)
        response = await handler.handle(message)
        if response:
            await self.inbound_bus.publish(response)

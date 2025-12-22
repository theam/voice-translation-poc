from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Protocol

from ...core.event_bus import EventBus
from ...models.messages import TranslationResponse

logger = logging.getLogger(__name__)


class VoiceLiveMessageHandler(Protocol):
    """Protocol for VoiceLive inbound message handlers."""

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        ...


def _extract_context(message: Dict[str, Any]) -> tuple[str, str, Optional[str]]:
    """Extract common context fields from a VoiceLive message."""
    response_meta = message.get("response", {}) if isinstance(message.get("response"), dict) else {}
    output_item = message.get("output", {}) if isinstance(message.get("output"), dict) else {}
    commit_id = (
        message.get("commit_id")
        or response_meta.get("commit_id")
        or output_item.get("commit_id")
        or response_meta.get("id")
        or message.get("id")
        or "unknown"
    )
    session_id = message.get("session_id") or response_meta.get("session_id") or "unknown"
    participant_id = message.get("participant_id") or response_meta.get("participant_id")
    return str(commit_id), str(session_id), participant_id


class ResponseOutputTextDeltaHandler:
    """Handle incremental text deltas returned by VoiceLive."""

    def __init__(self, text_buffers: Dict[str, List[str]]):
        self.text_buffers = text_buffers

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        commit_id, session_id, participant_id = _extract_context(message)
        delta = message.get("delta") or message.get("text") or ""
        if not delta:
            logger.debug("VoiceLive text delta without content: %s", message)
            return None

        self.text_buffers[commit_id].append(delta)
        return TranslationResponse(
            commit_id=commit_id,
            session_id=session_id,
            participant_id=participant_id,
            text=delta,
            partial=True,
        )


class ResponseOutputTextDoneHandler:
    """Handle completion of text output by emitting the buffered translation."""

    def __init__(self, text_buffers: Dict[str, List[str]]):
        self.text_buffers = text_buffers

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        commit_id, session_id, participant_id = _extract_context(message)
        buffered_text = "".join(self.text_buffers.pop(commit_id, []))
        final_text = buffered_text or message.get("text") or ""
        if not final_text:
            logger.debug("VoiceLive text done without buffered content: %s", message)
            return None

        return TranslationResponse(
            commit_id=commit_id,
            session_id=session_id,
            participant_id=participant_id,
            text=final_text,
            partial=False,
        )


class ResponseCompletedHandler:
    """Emit any buffered translations when a response is marked complete."""

    def __init__(self, text_buffers: Dict[str, List[str]], transcript_buffers: Dict[str, List[str]]):
        self.text_buffers = text_buffers
        self.transcript_buffers = transcript_buffers

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        commit_id, session_id, participant_id = _extract_context(message)
        buffered_text = "".join(self.text_buffers.pop(commit_id, []))
        buffered_transcript = "".join(self.transcript_buffers.pop(commit_id, []))
        final_text = buffered_text or buffered_transcript or message.get("text") or ""
        if not final_text:
            logger.debug("VoiceLive response completed without translation payload: %s", message)
            return None

        return TranslationResponse(
            commit_id=commit_id,
            session_id=session_id,
            participant_id=participant_id,
            text=final_text,
            partial=False,
        )


class AudioTranscriptDeltaHandler:
    """Handle incremental transcript deltas from VoiceLive."""

    def __init__(self, transcript_buffers: Dict[str, List[str]]):
        self.transcript_buffers = transcript_buffers

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        commit_id, session_id, participant_id = _extract_context(message)
        delta = message.get("delta") or message.get("transcript") or ""
        if not delta:
            logger.debug("VoiceLive transcript delta without content: %s", message)
            return None

        self.transcript_buffers[commit_id].append(delta)
        return TranslationResponse(
            commit_id=commit_id,
            session_id=session_id,
            participant_id=participant_id,
            text=delta,
            partial=True,
        )


class AudioTranscriptDoneHandler:
    """Handle completion of transcript streaming."""

    def __init__(self, transcript_buffers: Dict[str, List[str]]):
        self.transcript_buffers = transcript_buffers

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        commit_id, session_id, participant_id = _extract_context(message)
        buffered_text = "".join(self.transcript_buffers.pop(commit_id, []))
        final_text = buffered_text or message.get("transcript") or message.get("text") or ""
        if not final_text:
            logger.debug("VoiceLive transcript done without buffered content: %s", message)
            return None

        return TranslationResponse(
            commit_id=commit_id,
            session_id=session_id,
            participant_id=participant_id,
            text=final_text,
            partial=False,
        )


class ResponseErrorHandler:
    """Handle error messages from VoiceLive."""

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        logger.error("VoiceLive error message received: %s", message)
        return None


class LoggingOnlyHandler:
    """Handler for messages where we don't yet translate payloads."""

    def __init__(self, name: str):
        self.name = name

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        logger.debug("VoiceLive handler '%s' received payload with no action: %s", self.name, message)
        return None


class UnknownMessageHandler:
    """Fallback handler for unrecognized message types."""

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        logger.debug("VoiceLive unknown message type received: %s", message)
        return None


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
        self._default_handler: VoiceLiveMessageHandler = UnknownMessageHandler()

    async def handle(self, message: Dict[str, Any]) -> None:
        """Dispatch to a handler and publish any resulting translation."""
        message_type = message.get("type") or ""
        handler = self._handlers.get(message_type, self._default_handler)
        response = await handler.handle(message)
        if response:
            await self.inbound_bus.publish(response)

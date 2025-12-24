from __future__ import annotations

import logging
from typing import Any, Dict

from ...core.event_bus import EventBus
from ...models.messages import ProviderOutputEvent
from ..base import Handler, HandlerSettings
from .audio_delta_handler import AudioDeltaHandler
from .audio_done_handler import AudioDoneHandler
from .control_handler import ControlHandler
from .transcript_delta_handler import TranscriptDeltaHandler

logger = logging.getLogger(__name__)


class ProviderOutputHandler(Handler):
    """
    Handles normalized provider output events by delegating to specialized handlers.
    Receives ProviderOutputEvent from provider_inbound_bus and
    publishes ACS-ready payloads (audio frames, stop controls, transcripts) to acs_outbound_bus.
    """

    def __init__(
        self,
        settings: HandlerSettings,
        acs_outbound_bus: EventBus,
        translation_settings: Dict[str, Any],
        session_metadata: Dict[str, Any],
    ):
        super().__init__(settings)
        self.acs_outbound_bus = acs_outbound_bus
        self.translation_settings = translation_settings
        self.session_metadata = session_metadata

        # Create specialized handlers
        self.audio_delta_handler = AudioDeltaHandler(
            acs_outbound_bus=acs_outbound_bus,
            session_metadata=session_metadata
        )
        self.audio_done_handler = AudioDoneHandler(
            audio_delta_handler=self.audio_delta_handler
        )
        self.control_handler = ControlHandler(
            acs_outbound_bus=acs_outbound_bus,
            audio_delta_handler=self.audio_delta_handler
        )
        self.transcript_delta_handler = TranscriptDeltaHandler(
            acs_outbound_bus=acs_outbound_bus
        )

    async def _handle_transcript_done(self, event: ProviderOutputEvent) -> None:
        payload = event.payload or {}
        text = payload.get("text")
        if not text:
            logger.debug("Transcript done event missing text: %s", payload)
            return

        translation_payload = {
            "type": "translation.result",
            "session_id": event.session_id,
            "participant_id": event.participant_id,
            "commit_id": event.commit_id,
            "stream_id": event.stream_id,
            "provider": event.provider,
            "partial": False,
            "text": text,
        }

        await self.acs_outbound_bus.publish(translation_payload)

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Route event to appropriate specialized handler."""
        logger.info(
            "Provider output received type=%s session=%s participant=%s commit=%s",
            event.event_type,
            event.session_id,
            event.participant_id,
            event.commit_id,
        )

        if event.event_type == "audio.delta":
            await self.audio_delta_handler.handle(event)
        elif event.event_type == "audio.done":
            await self.audio_done_handler.handle(event)
        elif event.event_type == "control":
            await self.control_handler.handle(event)
        elif event.event_type == "transcript.delta":
            await self.transcript_delta_handler.handle(event)
        elif event.event_type == "transcript.done":
            await self._handle_transcript_done(event)
        else:
            logger.info("Ignoring unsupported provider output event: %s", event.event_type)

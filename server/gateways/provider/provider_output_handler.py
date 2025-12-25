from __future__ import annotations

import logging
from typing import Any, Dict

from ...core.event_bus import EventBus
from ...models.provider_events import ProviderOutputEvent
from ..base import Handler, HandlerSettings
from .audio_delta_handler import AudioDeltaHandler
from .audio_done_handler import AudioDoneHandler
from .control_handler import ControlHandler
from .transcript_delta_handler import TranscriptDeltaHandler
from .transcript_done_handler import TranscriptDoneHandler

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
        self.transcript_done_handler = TranscriptDoneHandler(
            acs_outbound_bus=acs_outbound_bus
        )

        # List of handlers to check in order
        self._handlers = [
            self.audio_delta_handler,
            self.audio_done_handler,
            self.control_handler,
            self.transcript_delta_handler,
            self.transcript_done_handler,
        ]

    async def handle(self, event: ProviderOutputEvent) -> None:
        """Dispatch event to appropriate specialized handler based on event type."""
        logger.info(
            "Provider output received type=%s session=%s participant=%s commit=%s",
            event.event_type,
            event.session_id,
            event.participant_id,
            event.commit_id,
        )

        for handler in self._handlers:
            if handler.can_handle(event):
                await handler.handle(event)
                return

        logger.info("Ignoring unsupported provider output event: %s", event.event_type)

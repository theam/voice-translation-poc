from __future__ import annotations

import logging
from typing import Any, Dict

from ...core.event_bus import EventBus
from ...models.provider_events import ProviderOutputEvent
from ..base import Handler, HandlerSettings
from .audio import AcsAudioPublisher, PacedPlayoutEngine, PlayoutStore
from .audio_delta_handler import AudioDeltaHandler
from .audio_done_handler import AudioDoneHandler
from .control_handler import ControlHandler
from ...config import LOG_EVERY_N_ITEMS
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
        provider_audio_bus: EventBus,
        translation_settings: Dict[str, Any],
        session_metadata: Dict[str, Any],
        playout_store: PlayoutStore,
        playout_engine: PacedPlayoutEngine,
        audio_publisher: AcsAudioPublisher,
        provider_capabilities=None,
    ):
        super().__init__(settings)
        self.acs_outbound_bus = acs_outbound_bus
        self.provider_audio_bus = provider_audio_bus
        self.translation_settings = translation_settings
        self.session_metadata = session_metadata

        # Track sends for periodic logging
        self._received_count = 0

        # Create specialized handlers
        self.audio_delta_handler = AudioDeltaHandler(
            provider_audio_bus=provider_audio_bus,
            session_metadata=session_metadata,
            provider_capabilities=provider_capabilities,
        )
        self.audio_done_handler = AudioDoneHandler(
            audio_delta_handler=self.audio_delta_handler,
            provider_audio_bus=provider_audio_bus,
        )
        self.control_handler = ControlHandler(
            acs_outbound_bus=acs_outbound_bus,
            audio_delta_handler=self.audio_delta_handler,
            playout_store=playout_store,
            playout_engine=playout_engine,
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
        self._received_count += 1
        if self._received_count % LOG_EVERY_N_ITEMS == 0:
            logger.info(
            "Provider output progress session=%s total_received=%d",
            event.session_id,
                self._received_count,
            )

        for handler in self._handlers:
            if handler.can_handle(event):
                await handler.handle(event)
                return

        logger.info("Ignoring unsupported provider output event: %s", event.event_type)

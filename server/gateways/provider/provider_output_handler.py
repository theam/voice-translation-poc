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
from ...session.turn_controller import TurnController

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
        provider_capabilities=None,
        turn_controller: TurnController | None = None,
    ):
        super().__init__(settings)
        self.acs_outbound_bus = acs_outbound_bus
        self.translation_settings = translation_settings
        self.session_metadata = session_metadata
        self.turn_controller = turn_controller
        self._stop_audio_action = self._build_stop_audio_action()

        # Create specialized handlers
        self.audio_delta_handler = AudioDeltaHandler(
            acs_outbound_bus=acs_outbound_bus,
            session_metadata=session_metadata,
            provider_capabilities=provider_capabilities,
            on_stream_start=self._on_stream_start if turn_controller else None,
        )
        self.audio_done_handler = AudioDoneHandler(
            audio_delta_handler=self.audio_delta_handler,
            on_stream_done=self._on_stream_done if turn_controller else None,
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

    async def _on_stream_start(self, event: ProviderOutputEvent, stream_key: str) -> None:
        if self.turn_controller:
            await self.turn_controller.on_outbound_start(event, stream_key)

    async def _on_stream_done(self, event: ProviderOutputEvent, stream_key: str) -> None:
        if self.turn_controller:
            await self.turn_controller.on_outbound_end(event, stream_key)
        # Clear started bookkeeping even without controller
        self.audio_delta_handler.clear_stream(stream_key)

    def _build_stop_audio_action(self):
        async def stop_stream(stream_key: str, event: ProviderOutputEvent | None = None):
            state = self.audio_delta_handler.store.get(stream_key)
            if state:
                await self.audio_delta_handler.playout_engine.cancel(stream_key, state)
                self.audio_delta_handler.store.remove(stream_key)
                self.audio_delta_handler.clear_stream(stream_key)

            # Notify ACS to stop audio if we have event context
            if event:
                payload = {
                    "type": "control.stop_audio",
                    "session_id": event.session_id,
                    "participant_id": event.participant_id,
                    "commit_id": event.commit_id,
                    "stream_id": event.stream_id,
                    "provider": event.provider,
                    "detail": "barge_in",
                }
                await self.acs_outbound_bus.publish(payload)

        return stop_stream

    async def stop_active_stream(self, stream_key: str, event: ProviderOutputEvent | None = None):
        await self._stop_audio_action(stream_key, event)

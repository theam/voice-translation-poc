from __future__ import annotations

import logging
from typing import Any, Dict

from ...config import BatchingConfig
from ...models.envelope import Envelope
from ...core.event_bus import EventBus
from ..base import Handler, HandlerSettings
from .audio import AudioMessageHandler
from .audio_metadata import AudioMetadataHandler
from .test_settings import TestSettingsHandler
from .system_info import SystemInfoMessageHandler

logger = logging.getLogger(__name__)


class AcsInboundMessageHandler(Handler):
    """Dispatcher for inbound ACS messages to specific handlers."""

    def __init__(
        self,
        settings: HandlerSettings,
        provider_outbound_bus: EventBus,
        acs_outbound_bus: EventBus,
        batching_config: BatchingConfig,
        session_metadata: Dict[str, Any],
        translation_settings: Dict[str, Any],
    ):
        super().__init__(settings)
        self.audio_handler = AudioMessageHandler(provider_outbound_bus, batching_config)
        self.control_handler = TestSettingsHandler(translation_settings, session_metadata)
        self.system_info_handler = SystemInfoMessageHandler(acs_outbound_bus)
        self.audio_metadata_handler = AudioMetadataHandler(session_metadata)

    async def handle(self, envelope: Envelope) -> None:
        """Dispatch envelope to appropriate handler based on type."""
        if envelope.type.startswith("audio"):
            await self.audio_handler.handle(envelope)
        elif envelope.type == "audio_metadata":
            await self.audio_metadata_handler.handle(envelope)
        elif envelope.type == "control":
            await self.control_handler.handle(envelope)
        elif envelope.type == "control.test.settings":
            await self.control_handler.handle(envelope)
        elif envelope.type == "control.test.request.system_info":
            await self.system_info_handler.handle(envelope)
        else:
            logger.debug("Ignoring unsupported envelope type: %s", envelope.type)

    async def shutdown(self) -> None:
        """Shutdown child handlers."""
        await self.audio_handler.shutdown()
        # Control and System Info handlers don't have state to cleanup

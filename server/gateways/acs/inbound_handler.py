from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from ...config import BatchingConfig
from ...models.gateway_input_event import GatewayInputEvent
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
        pipeline_completion_callback: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        super().__init__(settings)
        self.audio_handler = AudioMessageHandler(provider_outbound_bus, batching_config)
        self.control_handler = TestSettingsHandler(translation_settings, session_metadata)
        self.system_info_handler = SystemInfoMessageHandler(acs_outbound_bus)
        self.audio_metadata_handler = AudioMetadataHandler(
            session_metadata,
            pipeline_completion_callback=pipeline_completion_callback
        )
        self._handlers = [
            self.audio_handler,
            self.audio_metadata_handler,
            self.control_handler,
            self.system_info_handler,
        ]

    async def handle(self, event: GatewayInputEvent) -> None:
        """Dispatch envelope to appropriate handler based on payload contents."""
        for handler in self._handlers:
            if handler.can_handle(event):
                await handler.handle(event)
                return

        logger.info("Ignoring unsupported ACS event: %s", event.payload)

    async def shutdown(self) -> None:
        """Shutdown child handlers."""
        await self.audio_handler.shutdown()
        # Control and System Info handlers don't have state to cleanup

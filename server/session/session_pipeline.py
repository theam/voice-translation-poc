"""Session pipeline: translation pipeline shared across participants in a session."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..providers.provider_factory import ProviderFactory, TranslationProvider
from ..config import Config
from ..models.gateway_input_event import GatewayInputEvent
from ..core.event_bus import EventBus, HandlerConfig
from ..gateways.audit import AuditHandler
from ..gateways.base import HandlerSettings
from ..gateways.provider import ProviderOutputHandler
from ..gateways.acs.inbound_handler import AcsInboundMessageHandler
from ..core.queues import OverflowPolicy

logger = logging.getLogger(__name__)


class SessionPipeline:
    """Translation pipeline shared across all participants in an ACS session."""

    def __init__(
        self,
        session_id: str,
        config: Config,
        provider_name: str,
        metadata: Dict[str, Any],
        translation_settings: Dict[str, Any],
    ):
        self.session_id = session_id
        self.config = config
        self.provider_name = provider_name
        self.metadata = metadata
        self.translation_settings = translation_settings
        self.pipeline_id = f"{session_id}"

        # Event buses (scoped to the session)
        self.acs_inbound_bus = EventBus(f"acs_in_{self.pipeline_id}")
        self.provider_outbound_bus = EventBus(f"prov_out_{self.pipeline_id}")
        self.provider_inbound_bus = EventBus(f"prov_in_{self.pipeline_id}")
        self.acs_outbound_bus = EventBus(f"acs_out_{self.pipeline_id}")

        # Provider adapter (per-participant)
        self.provider_adapter: Optional[TranslationProvider] = None

        # Handlers (per-participant instances)
        self._translation_handler: Optional[AcsInboundMessageHandler] = None

    async def start(self):
        """Start session pipeline: create provider and register handlers."""
        # Create provider adapter
        self.provider_adapter = ProviderFactory.create_provider(
            config=self.config,
            provider_name=self.provider_name,
            outbound_bus=self.provider_outbound_bus,
            inbound_bus=self.provider_inbound_bus,
            session_metadata=self.metadata,
        )

        # Start provider
        await self.provider_adapter.start()
        logger.info(
            "Session %s provider started: %s",
            self.session_id,
            self.provider_name,
        )

        # Register handlers
        await self._register_handlers()

    async def _register_handlers(self):
        """Register handlers on session event buses."""
        overflow_policy = OverflowPolicy(self.config.buffering.overflow_policy)

        # 1. Audit handler
        await self.acs_inbound_bus.register_handler(
            HandlerConfig(
                name=f"audit_{self.session_id}",
                queue_max=500,
                overflow_policy=overflow_policy,
                concurrency=1
            ),
            AuditHandler(
                HandlerSettings(
                    name=f"audit_{self.session_id}",
                    queue_max=500,
                    overflow_policy=str(overflow_policy)
                ),
                payload_capture=None
            )
        )

        # 2. Translation dispatch handler
        self._translation_handler = AcsInboundMessageHandler(
            HandlerSettings(
                name="translation",
                queue_max=self.config.buffering.ingress_queue_max,
                overflow_policy=str(self.config.buffering.overflow_policy)
            ),
            provider_outbound_bus=self.provider_outbound_bus,
            acs_outbound_bus=self.acs_outbound_bus,
            batching_config=self.config.dispatch.batching,
            session_metadata=self.metadata,
            translation_settings=self.translation_settings,
        )

        await self.acs_inbound_bus.register_handler(
            HandlerConfig(
                name=f"translation_{self.session_id}",
                queue_max=self.config.buffering.ingress_queue_max,
                overflow_policy=overflow_policy,
                concurrency=1
            ),
            self._translation_handler
        )

        # 3. Provider output handler
        await self.provider_inbound_bus.register_handler(
            HandlerConfig(
                name=f"provider_output_{self.session_id}",
                queue_max=self.config.buffering.egress_queue_max,
                overflow_policy=overflow_policy,
                concurrency=1
            ),
            ProviderOutputHandler(
                HandlerSettings(
                    name=f"provider_output_{self.session_id}",
                    queue_max=self.config.buffering.egress_queue_max,
                    overflow_policy=str(self.config.buffering.overflow_policy)
                ),
                acs_outbound_bus=self.acs_outbound_bus,
                translation_settings=self.translation_settings,
                session_metadata=self.metadata,
            )
        )

        logger.info("Session %s handlers registered", self.session_id)

    async def process_message(self, envelope: GatewayInputEvent):
        """Process message from ACS for this session."""
        await self.acs_inbound_bus.publish(envelope)

    async def cleanup(self):
        """Cleanup session pipeline."""
        # Shutdown translation handler
        if self._translation_handler:
            await self._translation_handler.shutdown()

        # Shutdown provider
        if self.provider_adapter:
            await self.provider_adapter.close()

        # Shutdown buses
        await self.acs_inbound_bus.shutdown()
        await self.provider_outbound_bus.shutdown()
        await self.provider_inbound_bus.shutdown()
        await self.acs_outbound_bus.shutdown()

        logger.info("Session %s pipeline cleaned up", self.session_id)

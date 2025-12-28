"""Session pipeline: translation pipeline shared across participants in a session."""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
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
from ..gateways.provider.audio import AcsFormatResolver
from ..providers.capabilities import get_provider_capabilities

logger = logging.getLogger(__name__)


class PipelineStage(str, Enum):
    """Pipeline initialization stages."""
    NOT_STARTED = "not_started"
    ACS_PROCESSING = "acs_processing"
    PROVIDER_PROCESSING = "provider_processing"


class SessionPipeline:
    """Translation pipeline shared across all participants in an ACS session."""

    def __init__(
        self,
        session_id: str,
        config: Config,
        metadata: Dict[str, Any],
        translation_settings: Dict[str, Any],
    ):
        self.session_id = session_id
        self.config = config
        self.metadata = metadata
        self.translation_settings = translation_settings
        self.pipeline_id = f"{session_id}"

        # Event buses (scoped to the session)
        self.acs_inbound_bus = EventBus(f"acs_in_{self.pipeline_id}")
        self.provider_outbound_bus = EventBus(f"prov_out_{self.pipeline_id}")
        self.provider_inbound_bus = EventBus(f"prov_in_{self.pipeline_id}")
        self.acs_outbound_bus = EventBus(f"acs_out_{self.pipeline_id}")

        # Provider adapter (created in start_provider_processing)
        self.provider_adapter: Optional[TranslationProvider] = None
        self.provider_capabilities = None

        # Handlers
        self._translation_handler: Optional[AcsInboundMessageHandler] = None

        # Pipeline stage tracking
        self._stage = PipelineStage.NOT_STARTED
        self._provider_processing_ready = asyncio.Event()

    async def start_acs_processing(self):
        """Start ACS processing: register ACS handlers (no provider yet).

        This is the first initialization stage that happens immediately after
        WebSocket connection. It sets up handlers to receive and queue ACS messages
        before the provider is configured and started.
        """
        if self._stage != PipelineStage.NOT_STARTED:
            logger.warning(
                "Session %s: start_acs_processing called but stage is %s, ignoring",
                self.session_id,
                self._stage
            )
            return

        # Register ACS handlers (they will queue messages until provider is ready)
        await self._register_acs_handlers()

        self._stage = PipelineStage.ACS_PROCESSING
        logger.info(
            "Session %s: ACS processing started (messages will queue until provider ready)",
            self.session_id
        )

    async def start_provider_processing(self):
        """Start provider processing: create provider and register provider handlers.

        This is the second initialization stage triggered by AudioMetadata handler.
        By this point, all configuration messages (test settings, etc.) have been
        processed and we can create the provider with the correct configuration.
        """
        if self._stage == PipelineStage.PROVIDER_PROCESSING:
            logger.warning(
                "Session %s: start_provider_processing already called, ignoring",
                self.session_id
            )
            return

        if self._stage != PipelineStage.ACS_PROCESSING:
            logger.error(
                "Session %s: start_provider_processing called but stage is %s (expected ACS_PROCESSING)",
                self.session_id,
                self._stage
            )
            return

        # Create provider adapter (now that all configuration has been received)
        # Provider name is selected dynamically from translation_settings -> metadata -> config.default_provider
        self.provider_adapter = ProviderFactory.create_provider(
            config=self.config,
            provider_name=None,  # Dynamically selected by factory
            outbound_bus=self.provider_outbound_bus,
            inbound_bus=self.provider_inbound_bus,
            session_metadata=self.metadata,
            translation_settings=self.translation_settings,
            provider_capabilities=None,  # Will be set after creation
        )

        # Get provider capabilities after creation
        # (need to determine provider type first)
        provider_name = ProviderFactory.select_provider_name(
            config=self.config,
            session_metadata=self.metadata,
            translation_settings=self.translation_settings,
        )
        provider_config = self.config.providers.get(provider_name)
        self.provider_capabilities = get_provider_capabilities(provider_config.type)

        # Start provider (async WebSocket connection)
        await self.provider_adapter.start()
        logger.info(
            "Session %s provider started: %s",
            self.session_id,
            provider_name,
        )

        # Register provider handlers
        await self._register_provider_handlers()
        self._log_audio_formats()

        # Mark provider processing as ready
        self._stage = PipelineStage.PROVIDER_PROCESSING
        self._provider_processing_ready.set()
        logger.info(
            "Session %s: Provider processing started (queued messages will now be consumed)",
            self.session_id
        )

    async def _register_acs_handlers(self):
        """Register ACS handlers that process incoming messages and configuration.

        These handlers can operate before the provider is ready. They will queue
        messages until start_provider_processing is called.
        """
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

        # 2. Translation dispatch handler (processes test settings, audio metadata, audio data)
        # This handler includes a callback to trigger provider initialization
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
            pipeline_completion_callback=self.start_provider_processing,
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

        logger.info("Session %s ACS handlers registered", self.session_id)

    async def _register_provider_handlers(self):
        """Register provider handlers that consume from provider buses.

        These handlers require the provider to be created and started.
        They process provider output and send it back to ACS.
        """
        overflow_policy = OverflowPolicy(self.config.buffering.overflow_policy)

        # Provider output handler
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
                provider_capabilities=self.provider_capabilities,
            )
        )

        logger.info("Session %s provider handlers registered", self.session_id)

    async def process_message(self, envelope: GatewayInputEvent):
        """Process message from ACS for this session."""
        await self.acs_inbound_bus.publish(envelope)

    def _log_audio_formats(self) -> None:
        acs_format = AcsFormatResolver(self.metadata).get_target_format()
        logger.info(
            "Audio formats (session=%s): acs=%s provider_input=%s provider_output=%s",
            self.session_id,
            acs_format,
            getattr(self.provider_capabilities, "provider_input_format", None),
            getattr(self.provider_capabilities, "provider_output_format", None),
        )

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

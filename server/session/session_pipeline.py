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
from ..gateways.base import HandlerSettings
from ..gateways.provider import ProviderOutputHandler
from ..gateways.acs.inbound_handler import AcsInboundMessageHandler
from ..core.queues import OverflowPolicy
from ..gateways.provider.audio import AcsFormatResolver
from ..providers.capabilities import get_provider_capabilities
from .session_activity import SessionActivity
from .turn_controller import TurnController

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

        # Activity callbacks (phase 0/1: instrumentation hooks only)
        self._activity: Optional[SessionActivity] = None
        self._turn_controller = TurnController(session_id, on_barge_in=self._handle_barge_in)
        self._provider_output_handler: Optional[ProviderOutputHandler] = None

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

        # 1. Translation dispatch handler (processes test settings, audio metadata, audio data)
        # This handler includes a callback to trigger provider initialization
        if self._activity is None:
            self._activity = SessionActivity(self.session_id, listener=self._turn_controller.on_inbound_activity)
            await self._activity.start()

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
            activity_callback=self._activity.sink,
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
            self._build_provider_output_handler()
        )
        # Handler reference already created

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

        if self._activity:
            await self._activity.shutdown()

        await self._turn_controller.shutdown()

        # Shutdown provider
        if self.provider_adapter:
            await self.provider_adapter.close()

        # Shutdown buses
        await self.acs_inbound_bus.shutdown()
        await self.provider_outbound_bus.shutdown()
        await self.provider_inbound_bus.shutdown()
        await self.acs_outbound_bus.shutdown()

        logger.info("Session %s pipeline cleaned up", self.session_id)

    def _build_provider_output_handler(self) -> ProviderOutputHandler:
        handler = ProviderOutputHandler(
            HandlerSettings(
                name=f"provider_output_{self.session_id}",
                queue_max=self.config.buffering.egress_queue_max,
                overflow_policy=str(self.config.buffering.overflow_policy)
            ),
            acs_outbound_bus=self.acs_outbound_bus,
            translation_settings=self.translation_settings,
            session_metadata=self.metadata,
            provider_capabilities=self.provider_capabilities,
            turn_controller=self._turn_controller,
        )
        self._provider_output_handler = handler
        return handler

    async def _handle_barge_in(self, activity: AudioActivityEvent, stream_key: str) -> None:
        """Stop outbound audio and cancel provider response on barge-in."""
        logger.info(
            "Handling barge-in: session=%s participant=%s stream=%s",
            self.session_id,
            activity.participant_id,
            stream_key,
        )
        # Stop ACS playout for the active stream
        if self._provider_output_handler:
            await self._provider_output_handler.stop_active_stream(stream_key)

        # Attempt provider-side cancel if supported
        cancel_method = getattr(self.provider_adapter, "cancel_response", None)
        if cancel_method:
            try:
                await cancel_method()
            except Exception:
                logger.exception("Provider cancel_response failed for session=%s", self.session_id)
        await self._turn_controller.mark_barge_handled()

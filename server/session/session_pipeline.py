"""Session pipeline: translation pipeline shared across participants in a session."""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional

from ..providers.provider_factory import ProviderFactory, TranslationProvider
from ..config import Config
from ..models.gateway_input_event import GatewayInputEvent
from ..core.event_bus import EventBus, HandlerConfig
from ..gateways.base import HandlerSettings
from ..gateways.acs.acs_sender_handler import AcsWebsocketSendHandler
from ..gateways.provider import ProviderOutputHandler
from ..gateways.acs.inbound_handler import AcsInboundMessageHandler
from ..core.queues import OverflowPolicy
from ..gateways.provider.audio import AcsFormatResolver
from ..gateways.provider.outbound_playout_handler import OutboundPlayoutHandler
from ..gateways.provider.provider_audio_gate_handler import ProviderAudioGateHandler, OutboundGateMode
from ..providers.capabilities import get_provider_capabilities
from .input_state import InputState

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
        self.provider_audio_bus = EventBus(f"prov_audio_{self.pipeline_id}")
        self.gated_audio_bus = EventBus(f"gated_audio_{self.pipeline_id}")

        self.input_state = InputState(self.config.system)
        self._input_state_listeners: list[Callable[[InputState], Awaitable[None]]] = []

        # Provider adapter (created in start_provider_processing)
        self.provider_adapter: Optional[TranslationProvider] = None
        self.provider_capabilities = None

        # Handlers
        self._translation_handler: Optional[AcsInboundMessageHandler] = None
        self._provider_output_handler: Optional[ProviderOutputHandler] = None
        self._edge_playout_handler: Optional[OutboundPlayoutHandler] = None

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
        await self._register_edge_outbound_chain()
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
            input_state=self.input_state,
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
        if self._edge_playout_handler is None:
            raise RuntimeError("Edge playout handler must be initialized before provider handlers.")

        self._provider_output_handler = ProviderOutputHandler(
            HandlerSettings(
                name=f"provider_output_{self.session_id}",
                queue_max=self.config.buffering.egress_queue_max,
                overflow_policy=str(self.config.buffering.overflow_policy)
            ),
            acs_outbound_bus=self.acs_outbound_bus,
            provider_audio_bus=self.provider_audio_bus,
            translation_settings=self.translation_settings,
            session_metadata=self.metadata,
            playout_store=self._edge_playout_handler.store,
            playout_engine=self._edge_playout_handler.engine,
            audio_publisher=self._edge_playout_handler.publisher,
            provider_capabilities=self.provider_capabilities,
        )

        await self.provider_inbound_bus.register_handler(
            HandlerConfig(
                name=f"provider_output_{self.session_id}",
                queue_max=self.config.buffering.egress_queue_max,
                overflow_policy=overflow_policy,
                concurrency=1
            ),
            self._provider_output_handler
        )

        logger.info("Session %s provider handlers registered", self.session_id)

    async def register_acs_sender_handler(
        self,
        send_callable: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> None:
        sender = AcsWebsocketSendHandler(send_callable)
        await self.acs_outbound_bus.register_handler(
            HandlerConfig(
                name=f"acs_sender_{self.session_id}",
                queue_max=self.config.buffering.egress_queue_max,
                overflow_policy=OverflowPolicy(self.config.buffering.overflow_policy),
                concurrency=1,
            ),
            sender,
        )

    async def _register_edge_outbound_chain(self) -> None:
        overflow_policy = OverflowPolicy(self.config.buffering.overflow_policy)

        # 1. Create playout handler FIRST (needed by gate for references)
        playout = OutboundPlayoutHandler(
            acs_outbound_bus=self.acs_outbound_bus,
            playout_config=getattr(self.config, "playout", None),
            session_metadata=self.metadata,
        )
        self._edge_playout_handler = playout

        # Register playout handler on gated_audio_bus
        playout_handler_name = f"edge_playout_{self.session_id}"
        await self.gated_audio_bus.register_handler(
            HandlerConfig(
                name=playout_handler_name,
                queue_max=self.config.buffering.egress_queue_max,
                overflow_policy=overflow_policy,
                concurrency=1,
            ),
            playout,
        )

        # 2. Determine gate mode from config
        translation_settings = self.metadata.get("translation_settings", {})
        gate_mode_value = (
                translation_settings.get("gate_mode")
                or translation_settings.get("outbound_gate_mode")  # backward compatibility
                or self.config.system.default_gate_mode
        )
        gate_mode = OutboundGateMode.from_value(gate_mode_value)

        # 3. Create gate with references to control downstream handler
        gate = ProviderAudioGateHandler(
            gated_bus=self.gated_audio_bus,
            input_state=self.input_state,
            downstream_handler_name=playout_handler_name,  # Controls this handler
            playout_store=playout.store,
            playout_engine=playout.engine,
            gate_mode=gate_mode,
            session_id=self.session_id,
        )

        # Register gate on provider_audio_bus
        await self.provider_audio_bus.register_handler(
            HandlerConfig(
                name=f"provider_audio_gate_{self.session_id}",
                queue_max=self.config.buffering.egress_queue_max,
                overflow_policy=overflow_policy,
                concurrency=1,
            ),
            gate,
        )

    async def process_message(self, envelope: GatewayInputEvent):
        """Process message from ACS for this session."""
        await self.acs_inbound_bus.publish(envelope)

    def register_input_state_listener(self, listener: Callable[[InputState], Awaitable[None]]) -> None:
        self._input_state_listeners.append(listener)

    async def _notify_input_state_changed(self) -> None:
        for listener in list(self._input_state_listeners):
            await listener(self.input_state)

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
        await self.provider_audio_bus.shutdown()
        await self.gated_audio_bus.shutdown()

        logger.info("Session %s pipeline cleaned up", self.session_id)

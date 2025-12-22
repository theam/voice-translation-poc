"""Participant pipeline: independent translation pipeline for a single participant."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..providers.provider_factory import ProviderFactory, TranslationProvider
from ..config import Config
from ..models.envelope import Envelope
from ..core.event_bus import EventBus, HandlerConfig
from ..gateways.audit import AuditHandler
from ..gateways.base import HandlerSettings
from ..gateways.provider_result import ProviderResultHandler
from ..gateways.acs.inbound_handler import AcsInboundMessageHandler
from ..core.queues import OverflowPolicy

logger = logging.getLogger(__name__)


class ParticipantPipeline:
    """Independent translation pipeline for a single participant.

    Each pipeline has its own:
    - Event buses (4)
    - Handlers (4 instances)
    - Provider adapter
    - Auto-commit state

    This enables complete isolation between participants.
    """

    def __init__(
        self,
        session_id: str,
        participant_id: str,
        config: Config,
        provider_type: str,
        metadata: Dict[str, Any]
    ):
        self.session_id = session_id
        self.participant_id = participant_id
        self.config = config
        self.provider_type = provider_type
        self.metadata = metadata

        # Event buses (per-participant)
        pipeline_id = f"{session_id}_{participant_id}"
        self.acs_inbound_bus = EventBus(f"acs_in_{pipeline_id}")
        self.provider_outbound_bus = EventBus(f"prov_out_{pipeline_id}")
        self.provider_inbound_bus = EventBus(f"prov_in_{pipeline_id}")
        self.acs_outbound_bus = EventBus(f"acs_out_{pipeline_id}")

        # Provider adapter (per-participant)
        self.provider_adapter: Optional[TranslationProvider] = None

        # Handlers (per-participant instances)
        self._translation_handler: Optional[AcsInboundMessageHandler] = None

    async def start(self):
        """Start participant pipeline: create provider and register handlers."""
        # Create provider adapter
        self.provider_adapter = ProviderFactory.create_adapter(
            config=self.config,
            provider_type=self.provider_type,
            outbound_bus=self.provider_outbound_bus,
            inbound_bus=self.provider_inbound_bus,
            session_metadata=self.metadata,
        )

        # Start provider
        await self.provider_adapter.start()
        logger.info(
            f"Participant {self.participant_id} provider started: {self.provider_type}"
        )

        # Register handlers
        await self._register_handlers()

    async def _register_handlers(self):
        """Register handlers on participant's event buses."""
        overflow_policy = OverflowPolicy(self.config.buffering.overflow_policy)

        # 1. Audit handler
        await self.acs_inbound_bus.register_handler(
            HandlerConfig(
                name="audit",
                queue_max=500,
                overflow_policy=overflow_policy,
                concurrency=1
            ),
            AuditHandler(
                HandlerSettings(
                    name="audit",
                    queue_max=500,
                    overflow_policy=str(overflow_policy)
                ),
                payload_capture=None  # Could be per-participant
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
            session_metadata=self.metadata
        )

        await self.acs_inbound_bus.register_handler(
            HandlerConfig(
                name="translation",
                queue_max=self.config.buffering.ingress_queue_max,
                overflow_policy=overflow_policy,
                concurrency=1
            ),
            self._translation_handler
        )

        # 3. Provider result handler
        await self.provider_inbound_bus.register_handler(
            HandlerConfig(
                name="provider_result",
                queue_max=self.config.buffering.egress_queue_max,
                overflow_policy=overflow_policy,
                concurrency=1
            ),
            ProviderResultHandler(
                HandlerSettings(
                    name="provider_result",
                    queue_max=self.config.buffering.egress_queue_max,
                    overflow_policy=str(self.config.buffering.overflow_policy)
                ),
                acs_outbound_bus=self.acs_outbound_bus
            )
        )

        logger.info(f"Participant {self.participant_id} handlers registered")

    async def process_message(self, envelope: Envelope):
        """Process message from ACS for this participant."""
        await self.acs_inbound_bus.publish(envelope)

    async def cleanup(self):
        """Cleanup participant pipeline."""
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

        logger.info(f"Participant {self.participant_id} pipeline cleaned up")

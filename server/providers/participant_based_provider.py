"""Participant-based provider router for per-participant provider instances."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..config import Config
from ..core.event_bus import EventBus, HandlerConfig
from ..core.queues import OverflowPolicy
from ..models.provider_events import ProviderInputEvent
from .provider_factory import ProviderFactory

logger = logging.getLogger(__name__)


class ParticipantBasedProvider:
    """
    Composable provider that routes audio to independent providers per participant.

    This provider:
    1. Creates a dedicated provider instance for each participant on first message
    2. Routes audio events to the participant-specific provider instance
    3. Shares a common inbound bus for translated events

    Configuration example:
        providers:
          live_interpreter:
            type: live_interpreter
            region: eastus2
            api_key: ${LIVE_INTERPRETER_API_KEY}
            settings:
              languages: [en-US, es-ES]
              voice: es-ES-ElviraNeural

          participant_based:
            type: participant_based
            settings:
              provider: live_interpreter
    """

    def __init__(
        self,
        *,
        config: Config,
        provider_name: str,
        outbound_bus: EventBus,
        inbound_bus: EventBus,
        session_metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize participant-based provider router.

        Args:
            config: Service configuration
            provider_name: Provider name to instantiate per participant
            outbound_bus: Bus to consume audio events from
            inbound_bus: Bus to publish translation events to (shared by all providers)
            session_metadata: Session-level metadata
        """
        self.config = config
        self.provider_name = provider_name
        self.outbound_bus = outbound_bus
        self.inbound_bus = inbound_bus
        self.session_metadata = session_metadata or {}

        # Participant tracking
        self._providers: Dict[str, Any] = {}
        self._internal_buses: Dict[str, EventBus] = {}

        self._closed = False

        logger.info(
            "👥 ParticipantBasedProvider initialized: provider=%s",
            provider_name,
        )

    async def start(self) -> None:
        """Register router handler on shared outbound bus."""
        if self._closed:
            raise RuntimeError("Cannot start closed provider")

        await self.outbound_bus.register_handler(
            HandlerConfig(
                name="participant_based_router",
                queue_max=1000,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1,
            ),
            self._route_provider_input_event,
        )

        logger.info("✅ ParticipantBasedProvider started")

    async def _route_provider_input_event(self, event: ProviderInputEvent) -> None:
        """
        Route events from shared outbound bus to participant-specific internal bus.

        Args:
            event: Provider input event from SessionPipeline
        """
        if self._closed:
            logger.debug("Provider closed; skipping audio routing")
            return

        participant_key = event.participant_id or "unknown"
        provider = self._providers.get(participant_key)

        if provider is None:
            provider = await self._create_provider_for_participant(participant_key)

        internal_bus = self._internal_buses.get(participant_key)
        logger.debug(
            "📨 Routing audio: participant=%s, commit=%s",
            participant_key,
            event.commit_id,
        )
        await internal_bus.publish(event)

    async def _create_provider_for_participant(self, participant_key: str) -> Any:
        """Create a provider instance and internal bus for a participant."""
        if self._closed:
            raise RuntimeError("Cannot create provider for closed router")

        logger.info(
            "🔧 Creating provider for participant '%s': %s",
            participant_key,
            self.provider_name,
        )

        internal_bus = EventBus(f"participant_based_{participant_key}")
        self._internal_buses[participant_key] = internal_bus

        provider = ProviderFactory.create_provider(
            config=self.config,
            provider_name=self.provider_name,
            outbound_bus=internal_bus,
            inbound_bus=self.inbound_bus,
            session_metadata=self.session_metadata,
        )
        await provider.start()

        self._providers[participant_key] = provider

        logger.info(
            "✅ Provider for participant '%s' started: %s",
            participant_key,
            self.provider_name,
        )

        return provider

    async def close(self) -> None:
        """Close all sub-providers and shutdown internal buses."""
        self._closed = True

        logger.info(
            "🔒 Closing ParticipantBasedProvider with %s providers",
            len(self._providers),
        )

        for participant_key, provider in self._providers.items():
            try:
                await provider.close()
                logger.info("✅ Provider for participant '%s' closed", participant_key)
            except Exception as exc:
                logger.exception(
                    "Error closing provider for participant '%s': %s",
                    participant_key,
                    exc,
                )

        for participant_key, bus in self._internal_buses.items():
            try:
                await bus.shutdown()
                logger.info("✅ Internal bus for participant '%s' shutdown", participant_key)
            except Exception as exc:
                logger.exception(
                    "Error shutting down bus for participant '%s': %s",
                    participant_key,
                    exc,
                )

        self._providers.clear()
        self._internal_buses.clear()

        logger.info("✅ ParticipantBasedProvider closed")

    async def health(self) -> str:
        """
        Check health of all sub-providers.

        Returns:
            Health status: "ok" if all providers healthy, "degraded" if any degraded
        """
        if self._closed:
            return "degraded"

        if not self._providers:
            return "initializing"

        for participant_key, provider in self._providers.items():
            try:
                health = await provider.health()
                if health != "ok":
                    logger.warning(
                        "Provider for participant '%s' health: %s",
                        participant_key,
                        health,
                    )
                    return "degraded"
            except Exception as exc:
                logger.exception(
                    "Error checking health for participant '%s': %s",
                    participant_key,
                    exc,
                )
                return "degraded"

        return "ok"

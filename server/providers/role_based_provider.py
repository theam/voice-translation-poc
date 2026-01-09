"""Role-based provider router for composable multi-provider sessions."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..config import Config
from ..core.event_bus import EventBus, HandlerConfig
from ..core.queues import OverflowPolicy
from ..models.provider_events import ProviderInputEvent
from .provider_factory import ProviderFactory

logger = logging.getLogger(__name__)


class RoleBasedProvider:
    """
    Composable provider that routes audio to different providers based on participant role.

    This provider acts as a smart router that:
    1. Assigns roles to participants based on arrival order
    2. Routes audio events to role-specific provider instances
    3. Each provider instance can have different configuration (voices, languages, etc.)

    Configuration example:
        providers:
          live_interpreter_spanish:
            type: live_interpreter
            settings:
              target_audio_language: es

          live_interpreter_english:
            type: live_interpreter
            settings:
              target_audio_language: en

          role_based:
            type: role_based
            settings:
              role_providers:
                agent: live_interpreter_spanish
                caller: live_interpreter_english

    Benefits:
    - Solves single audio language limitation per provider
    - Keeps individual providers simple
    - Composable - mix any provider types
    - No race conditions - each provider instance is isolated
    """

    def __init__(
        self,
        *,
        config: Config,
        role_providers: Dict[str, str],
        outbound_bus: EventBus,
        inbound_bus: EventBus,
        session_metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize role-based provider router.

        Args:
            config: Service configuration
            role_providers: Mapping of role → provider_name (e.g., {"agent": "live_interpreter_spanish"})
            outbound_bus: Bus to consume audio events from
            inbound_bus: Bus to publish translation events to (shared by all providers)
            session_metadata: Session-level metadata
        """
        self.config = config
        self.role_providers_config = role_providers
        self.outbound_bus = outbound_bus
        self.inbound_bus = inbound_bus
        self.session_metadata = session_metadata or {}

        # Role tracking
        self._participant_roles: Dict[str, str] = {}  # participant_id → role
        self._participant_order: list[str] = []  # Track arrival order
        self._role_order: list[str] = list(role_providers.keys())  # Role assignment order

        # Provider instances (created in start())
        self._providers: Dict[str, Any] = {}  # role → provider_instance

        # Internal buses for routing (created in start())
        self._internal_buses: Dict[str, EventBus] = {}  # role → internal outbound bus

        self._closed = False
        self._egress_task = None

        logger.info(
            f"🎭 RoleBasedProvider initialized: roles={self._role_order}, "
            f"providers={role_providers}"
        )

    async def start(self) -> None:
        """Initialize sub-providers with internal buses and register router handler."""
        if self._closed:
            raise RuntimeError("Cannot start closed provider")

        # Step 1: Create internal bus and provider for each role
        for role, provider_name in self.role_providers_config.items():
            logger.info(f"🔧 Creating internal bus for role '{role}'")

            # Create dedicated internal outbound bus for this role
            internal_bus = EventBus(f"role_based_{role}")
            self._internal_buses[role] = internal_bus

            logger.info(f"🔧 Creating provider for role '{role}': {provider_name}")

            # Create provider with INTERNAL outbound bus
            provider = ProviderFactory.create_provider(
                config=self.config,
                provider_name=provider_name,
                outbound_bus=internal_bus,       # ← INTERNAL bus (isolated)
                inbound_bus=self.inbound_bus,    # ← SHARED bus (results go here)
                session_metadata=self.session_metadata,
            )

            # Start provider (registers handler on INTERNAL bus only)
            await provider.start()
            self._providers[role] = provider

            logger.info(f"✅ Provider for role '{role}' started: {provider_name}")

        # Step 2: Register router handler on SHARED outbound bus
        await self.outbound_bus.register_handler(
            HandlerConfig(
                name="role_based_router",
                queue_max=1000,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1,
            ),
            self._route_provider_input_event,
        )

        logger.info(f"✅ RoleBasedProvider started with {len(self._providers)} provider instances")

    async def _route_provider_input_event(self, event: ProviderInputEvent) -> None:
        """
        Route events from shared outbound bus to role-specific internal bus.

        This handler consumes events from the shared outbound bus and publishes
        to the appropriate internal bus based on participant role.

        Args:
            event: Provider input event from SessionPipeline
        """
        if self._closed:
            logger.debug("Provider closed; skipping audio routing")
            return

        participant_id = event.participant_id

        # Assign role based on arrival order (cached if already assigned)
        role = self._get_role(participant_id)

        # Get internal bus for this role
        internal_bus = self._internal_buses.get(role)
        if internal_bus:
            logger.debug(
                f"📨 Routing audio: participant={participant_id}, role={role}, "
                f"commit={event.commit_id}"
            )
            # Publish to internal bus (provider's handler will consume it)
            await internal_bus.publish(event)
        else:
            logger.warning(
                f"⚠️ No internal bus configured for role '{role}', participant={participant_id}"
            )

    def _get_role(self, participant_id: Optional[str]) -> str:
        """
        Assign role to participant based on arrival order.

        Role assignment:
        - First participant → First role in config
        - Second participant → Second role in config
        - Additional participants → Last role (fallback)

        Args:
            participant_id: Participant identifier

        Returns:
            Assigned role name
        """
        # Return cached role if already assigned
        if participant_id and participant_id in self._participant_roles:
            return self._participant_roles[participant_id]

        # Track arrival order
        if participant_id and participant_id not in self._participant_order:
            self._participant_order.append(participant_id)

        # Determine index in arrival order
        if participant_id:
            index = self._participant_order.index(participant_id)
        else:
            index = len(self._participant_order)

        # Assign role from role_order based on index
        if index < len(self._role_order):
            role = self._role_order[index]
        else:
            # Fallback to last role for additional participants
            role = self._role_order[-1]
            logger.warning(
                f"⚠️ More than {len(self._role_order)} participants detected. "
                f"Participant {participant_id} assigned to fallback role '{role}'"
            )

        # Cache role assignment
        if participant_id:
            self._participant_roles[participant_id] = role
            logger.info(
                f"👤 Assigned role '{role}' to participant {participant_id} (arrival order: {index})"
            )

        return role

    async def close(self) -> None:
        """Close all sub-providers and shutdown internal buses."""
        self._closed = True

        logger.info(f"🔒 Closing RoleBasedProvider with {len(self._providers)} providers")

        # Step 1: Close all provider instances
        for role, provider in self._providers.items():
            try:
                await provider.close()
                logger.debug(f"✅ Provider for role '{role}' closed")
            except Exception as exc:
                logger.exception(f"Error closing provider for role '{role}': {exc}")

        # Step 2: Shutdown all internal buses
        for role, bus in self._internal_buses.items():
            try:
                await bus.shutdown()
                logger.debug(f"✅ Internal bus for role '{role}' shutdown")
            except Exception as exc:
                logger.exception(f"Error shutting down bus for role '{role}': {exc}")

        # Step 3: Clear state
        self._providers.clear()
        self._internal_buses.clear()

        logger.info("✅ RoleBasedProvider closed")

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

        # Check health of all provider instances
        for role, provider in self._providers.items():
            try:
                health = await provider.health()
                if health != "ok":
                    logger.warning(f"Provider for role '{role}' health: {health}")
                    return "degraded"
            except Exception as exc:
                logger.exception(f"Error checking health for role '{role}': {exc}")
                return "degraded"

        return "ok"

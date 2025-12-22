"""Factory for creating translation adapters based on configuration."""

from __future__ import annotations

import logging
from typing import Optional

from ..config import Config
from ..core.event_bus import EventBus
from .mock_adapter import MockAdapter
from .voicelive_adapter import VoiceLiveAdapter

logger = logging.getLogger(__name__)


class TranslationAdapter:
    """
    Base interface for translation adapters.
    All adapters should implement these methods.
    """

    async def start(self) -> None:
        """Start the adapter (connect, start loops)."""
        raise NotImplementedError

    async def close(self) -> None:
        """Close the adapter and cleanup resources."""
        raise NotImplementedError

    async def health(self) -> str:
        """Check adapter health status."""
        raise NotImplementedError


class AdapterFactory:
    """
    Factory for creating translation adapters.

    Supports dynamic adapter selection based on configuration.
    Future enhancement: Per-session adapter selection based on ACS metadata.
    """

    @staticmethod
    def create_adapter(
        config: Config,
        provider_type: str,
        outbound_bus: EventBus,
        inbound_bus: EventBus,
    ) -> TranslationAdapter:
        """
        Create translation adapter based on provider type.

        Args:
            config: Service configuration
            provider_type: Provider type to create (e.g., "mock", "voicelive")
            outbound_bus: Bus to consume AudioRequest from
            inbound_bus: Bus to publish TranslationResponse to

        Returns:
            Configured translation adapter

        Raises:
            ValueError: If adapter type is unknown
        """
        adapter_type = provider_type.lower()

        logger.info("Creating translation adapter: type=%s", adapter_type)

        if adapter_type == "mock":
            return MockAdapter(
                outbound_bus=outbound_bus,
                inbound_bus=inbound_bus,
                delay_ms=50,  # Configurable if needed
            )

        elif adapter_type == "voicelive":
            endpoint = config.providers.voicelive.endpoint
            api_key = config.providers.voicelive.api_key

            if not endpoint:
                raise ValueError("VoiceLive endpoint not configured")

            return VoiceLiveAdapter(
                endpoint=endpoint,
                api_key=api_key or "",
                outbound_bus=outbound_bus,
                inbound_bus=inbound_bus,
            )

        elif adapter_type == "live_interpreter":
            # Future: Implement LiveInterpreterAdapter
            logger.warning("LiveInterpreter adapter not yet implemented, using Mock")
            return MockAdapter(
                outbound_bus=outbound_bus,
                inbound_bus=inbound_bus,
                delay_ms=50,
            )

        else:
            raise ValueError(f"Unknown adapter type: {adapter_type}")


# Future enhancement: Dynamic per-session adapter selection
class SessionBasedAdapterFactory:
    """
    Future enhancement: Factory that selects adapters based on session metadata.

    Example usage:
        # Extract provider from ACS envelope metadata
        provider = envelope.payload.get("provider", "default")

        # Get or create adapter for this session
        adapter = factory.get_adapter_for_session(
            session_id=envelope.session_id,
            provider=provider
        )

    This would allow:
    - Different customers using different translation services
    - A/B testing different providers
    - Fallback to different providers on failure
    """

    def __init__(self):
        self._session_adapters = {}  # session_id → adapter
        self._default_adapter = None

    async def get_adapter_for_session(
        self,
        session_id: str,
        provider: Optional[str] = None
    ) -> TranslationAdapter:
        """Get or create adapter for specific session."""
        # TODO: Implement session-based selection
        raise NotImplementedError("Session-based adapter selection not yet implemented")

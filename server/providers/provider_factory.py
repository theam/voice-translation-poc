"""Factory for creating translation adapters based on configuration."""

from __future__ import annotations

import logging
from typing import Optional

from ..config import Config
from ..core.event_bus import EventBus
from .mock_provider import MockProvider
from .voice_live import VoiceLiveProvider

logger = logging.getLogger(__name__)


class TranslationProvider:
    """
    Base interface for translation providers.
    All providers should implement these methods.
    """

    async def start(self) -> None:
        """Start the provider (connect, start loops)."""
        raise NotImplementedError

    async def close(self) -> None:
        """Close the provider and cleanup resources."""
        raise NotImplementedError

    async def health(self) -> str:
        """Check provider health status."""
        raise NotImplementedError


class ProviderFactory:
    """
    Factory for creating translation providers.

    Supports dynamic provider selection based on configuration.
    Future enhancement: Per-session provider selection based on ACS metadata.
    """

    @staticmethod
    def create_provider(
        config: Config,
        provider_name: str,
        outbound_bus: EventBus,
        inbound_bus: EventBus,
        session_metadata: Optional[dict] = None,
        provider_capabilities=None,
    ) -> TranslationProvider:
        """
        Create translation provider based on provider type.

        Args:
            config: Service configuration
            provider_name: Provider name in configuration (e.g., "mock", "demo-voicelive")
            outbound_bus: Bus to consume ProviderInputEvent from
            inbound_bus: Bus to publish ProviderOutputEvent to
            session_metadata: Session-level metadata (e.g., languages, audio format)

        Returns:
            Configured translation provider

        Raises:
            ValueError: If provider type is unknown or configuration missing
        """
        provider_config = config.providers.get(provider_name)
        provider_type = (provider_config.type or "mock").lower()
        provider_capabilities = provider_capabilities or None

        logger.info(
            "Creating translation provider: name=%s type=%s",
            provider_name,
            provider_type,
        )

        if provider_type == "mock":
            return MockProvider(
                outbound_bus=outbound_bus,
                inbound_bus=inbound_bus,
                delay_ms=50,  # Configurable if needed
            )

        elif provider_type == "voice_live":
            endpoint = provider_config.endpoint
            api_key = provider_config.api_key

            if not endpoint:
                raise ValueError("VoiceLive endpoint not configured")

            return VoiceLiveProvider(
                endpoint=endpoint,
                api_key=api_key or "",
                region=provider_config.region,
                resource=provider_config.resource,
                outbound_bus=outbound_bus,
                inbound_bus=inbound_bus,
                settings=provider_config.settings,
                session_metadata=session_metadata,
                log_wire=config.system.log_wire,
                capabilities=provider_capabilities,
            )

        elif provider_type == "live_interpreter":
            from .live_interpreter import LiveInterpreterProvider

            endpoint = provider_config.endpoint
            api_key = provider_config.api_key

            if not api_key:
                raise ValueError("Live Interpreter api_key not configured")
            if not endpoint and not provider_config.resource:
                raise ValueError("Live Interpreter requires either endpoint or resource configuration")

            return LiveInterpreterProvider(
                endpoint=endpoint,
                api_key=api_key,
                region=provider_config.region,
                resource=provider_config.resource,
                outbound_bus=outbound_bus,
                inbound_bus=inbound_bus,
                session_metadata=session_metadata,
            )

        else:
            raise ValueError(f"Unknown adapter type: {provider_type}")


# Future enhancement: Dynamic per-session provider selection
class SessionBasedProviderFactory:
    """
    Future enhancement: Factory that selects providers based on session metadata.

    Example usage:
        # Extract provider from ACS envelope metadata
        provider = envelope.payload.get("provider", "default")

        # Get or create adapter for this session
        adapter = factory.get_adapter_for_session(
            session_id=envelope.session_id,
            provider=provider
        )

    This would allow:
    - Different customers using different translation providers
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
    ) -> TranslationProvider:
        """Get or create adapter for specific session."""
        # TODO: Implement session-based selection
        raise NotImplementedError("Session-based provider selection not yet implemented")

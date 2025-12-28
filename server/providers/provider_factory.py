"""Factory for creating translation adapters based on configuration."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

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

    Supports dynamic provider selection based on session metadata and configuration.
    """

    @staticmethod
    def select_provider_name(
        config: Config,
        session_metadata: Optional[Dict[str, Any]] = None,
        translation_settings: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Select provider name dynamically based on session metadata and configuration.

        Selection priority:
        1. Test settings (translation_settings["provider"]) - from test framework
        2. Session metadata (metadata["provider"]) - from ACS
        3. Customer routing (metadata["customer_id"]) - future enhancement
        4. Feature flags (metadata["feature_flags"]["use_voicelive"]) - legacy
        5. Default from config (config.dispatch.default_provider)

        Args:
            config: Service configuration
            session_metadata: Session-level metadata from ACS messages
            translation_settings: Runtime settings from test control messages

        Returns:
            Provider name to use
        """
        # Strategy 0: Test control settings override (HIGHEST PRIORITY)
        if translation_settings:
            settings_provider = translation_settings.get("provider")
            if isinstance(settings_provider, str) and settings_provider:
                logger.info("Provider selected from test settings: %s", settings_provider)
                return settings_provider

        # Strategy 1: Explicit provider in session metadata
        if session_metadata and "provider" in session_metadata:
            provider = session_metadata["provider"]
            if isinstance(provider, str) and provider:
                logger.info("Provider selected from session metadata: %s", provider)
                return provider

        # Strategy 2: Customer/tenant-based routing (future enhancement)
        if session_metadata and "customer_id" in session_metadata:
            # Could implement per-customer provider mapping
            # customer_provider_map = config.customer_providers
            # return customer_provider_map.get(metadata["customer_id"], config.dispatch.default_provider)
            pass

        # Strategy 3: Feature flags (legacy support)
        if session_metadata and session_metadata.get("feature_flags", {}).get("use_voicelive"):
            logger.info("Provider selected from feature flag: voicelive")
            return "voicelive"

        # Default: use configured default provider
        default_provider = config.dispatch.default_provider
        logger.info("Using default provider from config: %s", default_provider)
        return default_provider

    @staticmethod
    def create_provider(
        config: Config,
        provider_name: Optional[str],
        outbound_bus: EventBus,
        inbound_bus: EventBus,
        session_metadata: Optional[dict] = None,
        translation_settings: Optional[dict] = None,
        provider_capabilities=None,
    ) -> TranslationProvider:
        """
        Create translation provider based on provider type.

        Args:
            config: Service configuration
            provider_name: Provider name in configuration (e.g., "mock", "voice_live").
                          If None, will be selected dynamically from session metadata.
            outbound_bus: Bus to consume ProviderInputEvent from
            inbound_bus: Bus to publish ProviderOutputEvent to
            session_metadata: Session-level metadata (e.g., languages, audio format)
            translation_settings: Runtime settings from test control messages
            provider_capabilities: Provider capabilities object

        Returns:
            Configured translation provider

        Raises:
            ValueError: If provider type is unknown or configuration missing
        """
        # If provider_name not specified, select it dynamically
        if provider_name is None:
            provider_name = ProviderFactory.select_provider_name(
                config=config,
                session_metadata=session_metadata,
                translation_settings=translation_settings,
            )

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

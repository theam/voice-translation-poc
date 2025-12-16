"""Factory for creating WebSocket clients based on scenario configuration.

Provides a factory function to create the appropriate WebSocket client
implementation (real network client or loopback mock client) based on
the scenario's websocket_client field.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, Union

from production.acs_emulator.websocket_client import WebSocketClient
from production.acs_emulator.websocket_loopback_client import WebSocketLoopbackClient

if TYPE_CHECKING:
    from production.capture.raw_log_sink import RawLogSink
    from production.scenario_engine.models import Scenario
    from production.utils.config import FrameworkConfig

logger = logging.getLogger(__name__)


def create_websocket_client(
    scenario: Scenario,
    config: FrameworkConfig,
    log_sink: Optional[RawLogSink] = None
) -> Union[WebSocketClient, WebSocketLoopbackClient]:
    """Create appropriate WebSocket client based on scenario configuration.

    Factory function that instantiates either a real WebSocket client (for
    connecting to actual translation services) or a loopback client (for
    testing with predetermined responses) based on the scenario's
    websocket_client field.

    Args:
        scenario: Scenario containing websocket_client type specification
        config: Framework configuration with connection parameters
        log_sink: Optional sink for logging WebSocket messages

    Returns:
        WebSocketClient or WebSocketLoopbackClient instance

    Raises:
        ValueError: If websocket_client type is not recognized

    Example:
        >>> # Scenario with real WebSocket connection
        >>> scenario = Scenario(..., websocket_client="websocket")
        >>> client = create_websocket_client(scenario, config, log_sink)
        >>> # Returns WebSocketClient instance
        >>>
        >>> # Scenario with loopback testing
        >>> scenario = Scenario(..., websocket_client="loopback")
        >>> client = create_websocket_client(scenario, config, log_sink)
        >>> # Returns WebSocketLoopbackClient instance
    """
    client_type = scenario.websocket_client.lower()

    if client_type == "websocket":
        logger.info("Creating real WebSocket client for scenario '%s'", scenario.id)
        return WebSocketClient(
            url=config.websocket_url,
            auth_key=config.auth_key,
            connect_timeout=config.connect_timeout,
            debug_wire=config.debug_wire,
            log_sink=log_sink,
        )

    elif client_type == "loopback":
        logger.info("Creating loopback WebSocket client for scenario '%s'", scenario.id)
        return WebSocketLoopbackClient(
            url=config.websocket_url,  # Ignored, kept for interface compatibility
            latency_ms=config.loopback_latency_ms,
            auth_key=config.auth_key,
            connect_timeout=config.connect_timeout,
            debug_wire=config.debug_wire,
            log_sink=log_sink,
        )

    else:
        raise ValueError(
            f"Unknown websocket_client type: '{client_type}'. "
            f"Supported types: 'websocket', 'loopback'"
        )


__all__ = ["create_websocket_client"]

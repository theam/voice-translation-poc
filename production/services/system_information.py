"""System information collection service.

Collects comprehensive system information from both the test runner
and the translation system for storage in evaluation runs.
"""
from __future__ import annotations

import asyncio
import logging
import platform
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from production.utils.config import FrameworkConfig
    from production.acs_emulator.websocket_client import WebSocketClient

logger = logging.getLogger(__name__)


class SystemInformationService:
    """Collects system information from test runner and translation system.

    Example:
        >>> config = load_config()
        >>> service = SystemInformationService(config)
        >>> system_info = await service.collect(websocket_client)
        >>> print(system_info.keys())
        dict_keys(['test_runner', 'translation_system', 'collected_at'])
    """

    def __init__(self, config: FrameworkConfig):
        """Initialize system information service.

        Args:
            config: Framework configuration
        """
        self.config = config

    async def collect(
        self,
        websocket_client: Optional[WebSocketClient] = None,
        timeout: float = 5.0
    ) -> Dict[str, Any]:
        """Collect comprehensive system information.

        Args:
            websocket_client: Optional WebSocket client to query translation system
            timeout: Timeout in seconds for WebSocket query (default: 5.0)

        Returns:
            Dictionary with test_runner and translation_system information
        """
        system_info = {
            "collected_at": datetime.utcnow().isoformat(),
            "test_runner": self._collect_test_runner_info(),
        }

        # Collect translation system info if WebSocket client provided
        if websocket_client:
            translation_info = await self._collect_translation_system_info(
                websocket_client,
                timeout
            )
            if translation_info:
                system_info["translation_system"] = translation_info

        return system_info

    def _collect_test_runner_info(self) -> Dict[str, Any]:
        """Collect information about the test runner environment.

        Returns:
            Dictionary with test runner system information
        """
        return {
            # Python environment
            "python": {
                "version": sys.version,
                "version_info": {
                    "major": sys.version_info.major,
                    "minor": sys.version_info.minor,
                    "micro": sys.version_info.micro,
                },
                "executable": sys.executable,
            },

            # Platform information
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "platform": platform.platform(),
            },

            # Framework configuration
            "framework": {
                "websocket_url": self.config.websocket_url,
                "time_acceleration": self.config.time_acceleration,
                "connect_timeout": self.config.connect_timeout,
                "tail_silence_ms": self.config.tail_silence_ms,
                "debug_wire": self.config.debug_wire,
            },

            # Storage configuration
            "storage": {
                "enabled": self.config.storage_enabled,
                "database": self.config.storage_database if self.config.storage_enabled else None,
                "environment": self.config.environment,
            },

            # LLM configuration
            "llm": {
                "model": self.config.llm_model,
                "base_url": self.config.llm_base_url,
            } if self.config.llm_api_key else None,
        }

    async def _collect_translation_system_info(
        self,
        websocket_client: WebSocketClient,
        timeout: float
    ) -> Optional[Dict[str, Any]]:
        """Collect information from the translation system via WebSocket.

        Sends a system_info message to the translation system and waits
        for a response.

        Args:
            websocket_client: WebSocket client connected to translation system
            timeout: Timeout in seconds for response

        Returns:
            Dictionary with translation system information, or None if failed
        """
        try:
            logger.debug("Requesting system information from translation system")

            # Send system_info request message
            await websocket_client.send_json({
                "type": "system_info",
                "timestamp": datetime.utcnow().isoformat(),
            })

            # Wait for response with timeout
            response = await asyncio.wait_for(
                self._wait_for_system_info_response(websocket_client),
                timeout=timeout
            )

            if response:
                logger.info("Received system information from translation system")
                return response
            else:
                logger.warning("No system_info response received from translation system")
                return None

        except asyncio.TimeoutError:
            logger.warning(
                f"Timeout waiting for system_info response from translation system "
                f"(timeout: {timeout}s)"
            )
            return None
        except Exception as e:
            logger.error(f"Failed to collect translation system info: {e}", exc_info=True)
            return None

    async def _wait_for_system_info_response(
        self,
        websocket_client: WebSocketClient
    ) -> Optional[Dict[str, Any]]:
        """Wait for a system_info response message from the WebSocket.

        Args:
            websocket_client: WebSocket client

        Returns:
            System info response data, or None if not received
        """
        # Note: This is a simplified implementation
        # In practice, you'd need to integrate with the WebSocket client's
        # message handling to properly receive and parse the response.
        # This would typically involve:
        # 1. Registering a response handler
        # 2. Waiting for a message of type "system_info_response"
        # 3. Extracting the system information from the response

        # For now, return None to indicate this needs to be implemented
        # with proper WebSocket message handling
        logger.debug("WebSocket system_info response handling not yet implemented")
        return None


async def collect_system_information(
    config: FrameworkConfig,
    websocket_client: Optional[WebSocketClient] = None,
    timeout: float = 5.0
) -> Dict[str, Any]:
    """Convenience function to collect system information.

    Args:
        config: Framework configuration
        websocket_client: Optional WebSocket client
        timeout: Timeout for WebSocket query

    Returns:
        System information dictionary
    """
    service = SystemInformationService(config)
    return await service.collect(websocket_client, timeout)


__all__ = ["SystemInformationService", "collect_system_information"]

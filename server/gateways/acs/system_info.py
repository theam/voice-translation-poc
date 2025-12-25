from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from ...core.event_bus import EventBus
from ...models.gateway_input_event import GatewayInputEvent

logger = logging.getLogger(__name__)


class SystemInfoMessageHandler:
    """
    Handles system info requests from the test framework.
    Bypasses the translation provider and sends a response directly to ACS.
    """

    def __init__(self, acs_outbound_bus: EventBus):
        self.acs_outbound_bus = acs_outbound_bus

    def can_handle(self, event: GatewayInputEvent) -> bool:
        payload = event.payload or {}
        if not isinstance(payload, dict):
            return False
        return payload.get("type") == "control.test.request.system_info"

    async def handle(self, event: GatewayInputEvent) -> None:
        """Process system info request and send response."""
        logger.info("Handling system info request: %s", event.event_id)

        # Construct response payload
        # Note: This is a minimal implementation based on requirements.
        # In a real scenario, this might pull actual config/runtime stats.
        response_payload = {
            "type": "control.test.response.system_info",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system_info": {
                "service": {
                    "name": "Voice Translation POC",
                    "version": "0.1.0",
                    "provider": "VoiceLive"  # Dynamic based on config? Hardcoded for now.
                },
                "configuration": {
                    "features": {
                        "streaming": True,
                        "system_info_query": True
                    }
                },
                "runtime": {
                    "environment": "poc"
                }
            }
        }

        # Create response envelope
        # We need to target the same session/participant
        await self.acs_outbound_bus.publish(response_payload)
        logger.info("Sent system info response for %s", event.event_id)

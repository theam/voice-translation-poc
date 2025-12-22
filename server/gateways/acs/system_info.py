from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from ...core.event_bus import EventBus
from ...models.envelope import Envelope

logger = logging.getLogger(__name__)


class SystemInfoMessageHandler:
    """
    Handles system info requests from the test framework.
    Bypasses the translation provider and sends a response directly to ACS.
    """

    def __init__(self, acs_outbound_bus: EventBus):
        self.acs_outbound_bus = acs_outbound_bus

    async def handle(self, envelope: Envelope) -> None:
        """Process system info request and send response."""
        logger.info("Handling system info request: %s", envelope.message_id)

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
        response_envelope = {
            "type": "control.test.response.system_info",
            "message_id": f"resp-{envelope.message_id}",
            "reply_to_id": envelope.message_id,
            "session_id": envelope.session_id,
            "participant_id": envelope.participant_id,
            "timestamp_utc": response_payload["timestamp"],
            "payload": response_payload
        }

        # In this specific architecture, the outbound bus expects an object that
        # effectively serializes to the JSON message the ACS client expects.
        # The Envelope class is often used for internal routing, but when sending *out*
        # to ACS (via acs_egress_handler or similar), we usually send a dict or an Envelope
        # that the egress handler converts.
        # Looking at acs_egress_handler.py (from context), it takes a dict.
        # However, checking ParticipantPipeline, it subscribes ACSWebSocketSender to acs_outbound_bus.
        # ACSWebSocketSender logic:
        #             async def handle(self, payload: Dict[str, Any]):
        #                await send_to_acs(payload)
        # So we should publish a Dict.

        await self.acs_outbound_bus.publish(response_payload)
        logger.info("Sent system info response for %s", envelope.message_id)

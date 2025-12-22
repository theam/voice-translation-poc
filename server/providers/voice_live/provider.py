from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from ...core.event_bus import EventBus, HandlerConfig
from ...core.queues import OverflowPolicy
from .inbound_handler import VoiceLiveInboundHandler
from .outbound_handler import VoiceLiveOutboundHandler

logger = logging.getLogger(__name__)


class VoiceLiveProvider:
    """
    Bidirectional streaming provider for VoiceLive.

    Split into:
    - Outbound handler: consumes AudioRequest from provider_outbound_bus and sends to VoiceLive
    - Inbound handler: receives VoiceLive events and dispatches to type-specific handlers
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        region: Optional[str],
        resource: Optional[str],
        outbound_bus: EventBus,
        inbound_bus: EventBus,
    ):
        self.endpoint = endpoint
        self.api_key = api_key
        self.region = region
        self.resource = resource
        self.outbound_bus = outbound_bus
        self.inbound_bus = inbound_bus

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._ingress_task: Optional[asyncio.Task] = None
        self._closed = False

        self._inbound_handler = VoiceLiveInboundHandler(inbound_bus)
        self._outbound_handler: Optional[VoiceLiveOutboundHandler] = None

    async def start(self) -> None:
        """Connect to VoiceLive and start ingress/egress processing."""
        if self._closed:
            raise RuntimeError("Cannot start closed adapter")

        await self._connect()
        if not self._ws:
            raise RuntimeError("VoiceLive WebSocket is not connected")

        self._outbound_handler = VoiceLiveOutboundHandler(self._ws)

        await self._register_outbound_handler()

        self._ingress_task = asyncio.create_task(
            self._ingress_loop(),
            name="voicelive-ingress-loop",
        )
        logger.info("VoiceLive ingress loop started")

    async def _connect(self) -> None:
        """Establish WebSocket connection to VoiceLive."""
        if self._ws is not None and not self._ws.closed:
            logger.debug("VoiceLive WebSocket already connected")
            return

        headers = {
            "api-key": self.api_key,
            "Ocp-Apim-Subscription-Key": self.api_key,
            "x-ms-client-request-id": str(uuid.uuid4()),
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        try:
            self._ws = await websockets.connect(
                self.endpoint,
                extra_headers=headers,
                ping_interval=20,
                ping_timeout=10,
            )
            logger.info(
                "VoiceLive WebSocket connected to %s (region=%s, resource=%s)",
                self.endpoint,
                self.region,
                self.resource,
            )
        except Exception as exc:
            logger.exception("Failed to connect to VoiceLive: %s", exc)
            raise

    async def _register_outbound_handler(self) -> None:
        """Register outbound handler on provider_outbound_bus."""
        if not self._outbound_handler:
            raise RuntimeError("Outbound handler not initialized")

        await self.outbound_bus.register_handler(
            HandlerConfig(
                name="voicelive_egress",
                queue_max=1000,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1,
            ),
            self._outbound_handler.handle,
        )
        logger.info("VoiceLive egress handler registered")

    async def _ingress_loop(self) -> None:
        """Receive VoiceLive messages and dispatch via inbound handler."""
        if not self._ws:
            logger.error("VoiceLive ingress loop started without WebSocket connection")
            return

        try:
            async for raw_message in self._ws:
                try:
                    data = json.loads(raw_message)
                except json.JSONDecodeError as exc:
                    logger.warning("Received non-JSON message from VoiceLive: %s (error: %s)", raw_message, exc)
                    continue

                await self._inbound_handler.handle(data)

        except ConnectionClosed as exc:
            logger.warning("VoiceLive WebSocket closed: code=%s reason=%s", exc.code, exc.reason)
        except WebSocketException as exc:
            logger.error("VoiceLive WebSocket error: %s", exc)
        except Exception as exc:
            logger.exception("VoiceLive ingress loop failed: %s", exc)

    async def close(self) -> None:
        """Close WebSocket and cleanup resources."""
        self._closed = True

        if self._ingress_task and not self._ingress_task.done():
            self._ingress_task.cancel()
            try:
                await self._ingress_task
            except asyncio.CancelledError:
                pass

        if self._ws and not self._ws.closed:
            await self._ws.close()
            logger.info("VoiceLive WebSocket disconnected")

    async def health(self) -> str:
        """Check adapter health status."""
        if self._ws and not self._ws.closed and not self._closed:
            return "ok"
        return "degraded"

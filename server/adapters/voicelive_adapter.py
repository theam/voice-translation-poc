"""VoiceLive translation adapter with bidirectional streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from ..core.event_bus import EventBus
from ..models.messages import AudioRequest, TranslationResponse

logger = logging.getLogger(__name__)


class VoiceLiveAdapter:
    """
    Bidirectional streaming adapter for VoiceLive translation service.

    Architecture (symmetric with ACS adapters):
    - Egress: provider_outbound_bus → VoiceLive WebSocket
    - Ingress: VoiceLive WebSocket → provider_inbound_bus

    Maintains a single persistent WebSocket connection that preserves
    translation context across all audio commits.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        outbound_bus: EventBus,
        inbound_bus: EventBus,
    ):
        """
        Initialize VoiceLive adapter.

        Args:
            endpoint: WebSocket URL for VoiceLive service
            api_key: Authentication key for VoiceLive
            outbound_bus: Bus to consume AudioRequest messages from
            inbound_bus: Bus to publish TranslationResponse messages to
        """
        self.endpoint = endpoint
        self.api_key = api_key
        self.outbound_bus = outbound_bus
        self.inbound_bus = inbound_bus

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._egress_task: Optional[asyncio.Task] = None
        self._ingress_task: Optional[asyncio.Task] = None
        self._closed = False

    async def start(self) -> None:
        """
        Start the adapter: connect WebSocket and launch egress/ingress loops.
        Similar to how ACS adapters work.
        """
        if self._closed:
            raise RuntimeError("Cannot start closed adapter")

        # Connect to VoiceLive
        await self._connect()

        # Start egress loop (bus → WebSocket)
        self._egress_task = asyncio.create_task(
            self._egress_loop(),
            name="voicelive-egress-loop"
        )
        logger.info("VoiceLive egress loop started")

        # Start ingress loop (WebSocket → bus)
        self._ingress_task = asyncio.create_task(
            self._ingress_loop(),
            name="voicelive-ingress-loop"
        )
        logger.info("VoiceLive ingress loop started")

    async def _connect(self) -> None:
        """Establish WebSocket connection to VoiceLive."""
        if self._ws is not None and not self._ws.closed:
            logger.debug("VoiceLive WebSocket already connected")
            return

        try:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            self._ws = await websockets.connect(
                self.endpoint,
                extra_headers=headers,
                ping_interval=20,
                ping_timeout=10,
            )

            logger.info("VoiceLive WebSocket connected to %s", self.endpoint)

        except Exception as e:
            logger.exception("Failed to connect to VoiceLive: %s", e)
            raise

    async def _egress_loop(self) -> None:
        """
        Egress loop: consume AudioRequest from outbound_bus and send to VoiceLive.
        Runs continuously, similar to how ACS egress works.
        """
        try:
            logger.info("VoiceLive egress loop starting")

            # Register handler on outbound bus
            from ..core.event_bus import HandlerConfig
            from ..core.queues import OverflowPolicy

            await self.outbound_bus.register_handler(
                HandlerConfig(
                    name="voicelive_egress",
                    queue_max=1000,
                    overflow_policy=OverflowPolicy.DROP_OLDEST,
                    concurrency=1,
                ),
                self._send_audio,
            )

            logger.info("VoiceLive egress handler registered")

        except Exception as e:
            logger.exception("VoiceLive egress loop failed: %s", e)

    async def _send_audio(self, request: AudioRequest) -> None:
        """
        Send audio request to VoiceLive WebSocket.
        Called by event bus worker for each AudioRequest.
        """
        try:
            message = {
                "type": "translate",
                "commit_id": request.commit_id,
                "session_id": request.session_id,
                "participant_id": request.participant_id,
                "audio_data": request.audio_data.decode('utf-8'),
                "metadata": request.metadata,
            }

            await self._ws.send(json.dumps(message))
            logger.info(
                "Sent audio to VoiceLive: commit=%s session=%s bytes=%s",
                request.commit_id,
                request.session_id,
                len(request.audio_data)
            )

        except Exception as e:
            logger.exception(
                "Failed to send audio to VoiceLive: commit=%s error=%s",
                request.commit_id,
                e
            )

    async def _ingress_loop(self) -> None:
        """
        Ingress loop: receive translations from VoiceLive and publish to inbound_bus.
        Runs continuously, similar to how ACS ingress works.
        """
        try:
            logger.info("VoiceLive ingress loop starting")

            # Main listening loop - runs until WebSocket closes
            async for raw_message in self._ws:
                try:
                    data = json.loads(raw_message)

                    # Create TranslationResponse
                    response = TranslationResponse(
                        commit_id=data.get("commit_id", "unknown"),
                        session_id=data.get("session_id", "unknown"),
                        participant_id=data.get("participant_id"),
                        text=data.get("text", ""),
                        partial=data.get("partial", False),
                    )

                    # Publish to inbound bus
                    await self.inbound_bus.publish(response)

                    logger.debug(
                        "Received translation from VoiceLive: commit=%s partial=%s text=%s",
                        response.commit_id,
                        response.partial,
                        response.text
                    )

                except json.JSONDecodeError as e:
                    logger.warning("Received non-JSON message: %s (error: %s)", raw_message, e)
                except Exception as e:
                    logger.exception("Error processing VoiceLive message: %s", e)

        except ConnectionClosed as e:
            logger.warning("VoiceLive WebSocket closed: code=%s reason=%s", e.code, e.reason)
        except WebSocketException as e:
            logger.error("VoiceLive WebSocket error: %s", e)
        except Exception as e:
            logger.exception("VoiceLive ingress loop failed: %s", e)

    async def close(self) -> None:
        """Close WebSocket and cleanup resources."""
        self._closed = True

        # Cancel tasks
        for task in [self._egress_task, self._ingress_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close WebSocket
        if self._ws and not self._ws.closed:
            await self._ws.close()
            logger.info("VoiceLive WebSocket disconnected")

    async def health(self) -> str:
        """Check adapter health status."""
        if self._ws and not self._ws.closed and not self._closed:
            return "ok"
        return "degraded"

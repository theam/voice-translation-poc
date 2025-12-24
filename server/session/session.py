"""Session: manages one ACS WebSocket connection with a session-scoped pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import websockets
from websockets.server import WebSocketServerProtocol

from ..config import Config
from ..models.gateway_input_event import ConnectionContext, GatewayInputEvent
from ..core.event_bus import HandlerConfig
from ..gateways.base import Handler, HandlerSettings
from ..core.queues import OverflowPolicy
from ..utils.dict_utils import normalize_keys
from .session_pipeline import SessionPipeline

logger = logging.getLogger(__name__)


class Session:
    """Manages one ACS WebSocket connection with a single translation pipeline."""

    def __init__(
        self,
        session_id: str,
        websocket: WebSocketServerProtocol,
        config: Config,
        connection_ctx: ConnectionContext,
    ):
        self.session_id = session_id
        self.websocket = websocket
        self.config = config
        self.connection_ctx = connection_ctx
        self.canonical_session_id = connection_ctx.call_connection_id or connection_ctx.ingress_ws_id

        # Session state
        self.metadata: Dict[str, Any] = {}
        self.translation_settings: Dict[str, Any] = {}

        # Single session-scoped pipeline
        self.pipeline: Optional[SessionPipeline] = None

        # Initialization flag
        self._initialized = False

        # Frame sequencing
        self._sequence = 0

        # Background tasks
        self._receive_task: Optional[asyncio.Task] = None
        self._send_task: Optional[asyncio.Task] = None

    async def run(self):
        """Run session: process messages until disconnect."""
        logger.info(f"Session {self.session_id} started")

        # Start ACS receive/send loops
        self._receive_task = asyncio.create_task(
            self._acs_receive_loop(),
            name=f"session-{self.session_id}-receive"
        )
        self._send_task = asyncio.create_task(
            self._acs_send_loop(),
            name=f"session-{self.session_id}-send"
        )

        try:
            # Wait for both tasks
            await asyncio.gather(
                self._receive_task,
                self._send_task,
                return_exceptions=True
            )
        finally:
            await self.cleanup()

    async def _acs_receive_loop(self):
        """Receive messages from ACS WebSocket and route to the session pipeline."""
        try:
            async for raw_message in self.websocket:
                try:
                    # Parse and normalize keys to lowercase for case-insensitive handling
                    data = json.loads(raw_message)
                    data = normalize_keys(data)

                    # First message: extract metadata and initialize
                    if not self._initialized:
                        await self._initialize_from_first_message(data)

                    # Convert to GatewayInputEvent
                    self._sequence += 1
                    event = GatewayInputEvent.from_acs_frame(
                        data,
                        sequence=self._sequence,
                        ctx=self.connection_ctx,
                    )

                    # Route to the session pipeline
                    await self._route_message(event)

                except json.JSONDecodeError as e:
                    logger.warning(f"Session {self.session_id} invalid JSON: {e}")
                except Exception as e:
                    logger.exception(f"Session {self.session_id} error processing message: {e}")
        except websockets.ConnectionClosed:
            logger.info(f"Session {self.session_id} ACS disconnected")
        except Exception as e:
            logger.exception(f"Session {self.session_id} receive loop error: {e}")

    async def _route_message(self, envelope: GatewayInputEvent):
        """Route message to the session pipeline."""
        if self.pipeline is None:
            logger.warning("Session %s received message before pipeline initialization", self.session_id)
            return

        await self.pipeline.process_message(envelope)

    async def _acs_send_loop(self):
        """Keep send task alive (pipelines send directly to WebSocket)."""
        try:
            # This task just needs to stay alive
            # Actual sending is done by handlers subscribed to pipeline outbound buses
            await asyncio.Future()
        except asyncio.CancelledError:
            logger.debug(f"Session {self.session_id} send loop cancelled")

    async def _initialize_from_first_message(self, data: Dict[str, Any]):
        """Extract metadata and initialize session pipeline from first message."""
        self.metadata = data.get("metadata", {})

        provider_name = self._select_provider(self.metadata)

        # Create single session-scoped pipeline
        self.pipeline = SessionPipeline(
            session_id=self.canonical_session_id,
            config=self.config,
            provider_name=provider_name,
            metadata=self.metadata,
            translation_settings=self.translation_settings
        )
        await self.pipeline.start()

        # Subscribe to its outbound bus
        await self._subscribe_to_pipeline_output(self.pipeline)

        self._initialized = True

    def _select_provider(
        self,
        metadata: Dict[str, Any]
    ) -> str:
        """Select provider based on ACS metadata and participant."""
        # Strategy 0: Test control settings override
        settings_provider = self.translation_settings.get("provider")
        if isinstance(settings_provider, str) and settings_provider:
            return settings_provider
        # Strategy 1: Explicit provider in metadata
        if "provider" in metadata:
            return metadata["provider"]

        # Strategy 2: Customer/tenant-based routing
        if "customer_id" in metadata:
            # Could have per-customer provider mapping
            # customer_provider_map = self.config.customer_providers
            # return customer_provider_map.get(metadata["customer_id"], self.config.dispatch.provider)
            pass

        # Strategy 3: Feature flags
        if metadata.get("feature_flags", {}).get("use_voicelive"):
            return "voicelive"

        # Default: use config
        return self.config.dispatch.provider

    async def _subscribe_to_pipeline_output(self, pipeline: SessionPipeline):
        """Subscribe to pipeline's acs_outbound_bus to forward to ACS."""
        async def send_to_acs(payload: Dict[str, Any]):
            try:
                await self.websocket.send(json.dumps(payload))
                logger.debug(
                    f"Session {self.session_id} sent to ACS: {payload.get('type')}"
                )
            except Exception as e:
                logger.exception(
                    f"Session {self.session_id} failed to send to ACS: {e}"
                )

        # Create inline handler for sending to WebSocket
        class ACSWebSocketSender(Handler):
            def __init__(self, settings: HandlerSettings):
                super().__init__(settings)

            async def handle(self, payload: Dict[str, Any]):
                await send_to_acs(payload)

        # Register handler on pipeline's outbound bus
        await pipeline.acs_outbound_bus.register_handler(
            HandlerConfig(
                name=f"acs_websocket_send_{pipeline.pipeline_id}",
                queue_max=1000,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1
            ),
            ACSWebSocketSender(
                HandlerSettings(
                    name=f"acs_websocket_send_{pipeline.pipeline_id}",
                    queue_max=1000,
                    overflow_policy="DROP_OLDEST"
                )
            )
        )

    async def cleanup(self):
        """Cleanup session resources."""
        logger.info(f"Session {self.session_id} cleanup started")

        # Cancel tasks
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
        if self._send_task and not self._send_task.done():
            self._send_task.cancel()

        # Cleanup pipeline
        if self.pipeline:
            await self.pipeline.cleanup()

        # Close WebSocket
        if not self.websocket.closed:
            await self.websocket.close()

        logger.info(f"Session {self.session_id} cleanup complete")

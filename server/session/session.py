"""Session: manages one ACS WebSocket connection with a session-scoped pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import websockets

from ..config import Config
from ..models.gateway_input_event import ConnectionContext, GatewayInputEvent
from ..core.event_bus import HandlerConfig
from ..gateways.base import Handler, HandlerSettings
from ..core.queues import OverflowPolicy
from ..core.websocket_server import WebSocketServer
from ..utils.dict_utils import normalize_keys
from .session_pipeline import SessionPipeline
from .control_plane import AcsOutboundGateHandler, ControlPlaneBusHandler

logger = logging.getLogger(__name__)


class Session:
    """Manages one ACS WebSocket connection with a single translation pipeline."""

    def __init__(
        self,
        session_id: str,
        websocket: WebSocketServer,
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

        # Frame sequencing
        self._sequence = 0

        # Background tasks
        self._receive_task: Optional[asyncio.Task] = None
        self._send_task: Optional[asyncio.Task] = None

        # Shutdown coordination
        self._shutdown_event = asyncio.Event()
        self._cleanup_started = False

    async def run(self):
        """Run session: process messages until disconnect."""
        logger.info(f"Session {self.session_id} started")

        # Initialize ACS processing immediately (before receiving messages)
        await self._initialize_acs_processing()

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

                    # Extract session metadata if present (any message can contain metadata)
                    if "metadata" in data:
                        new_metadata = data.get("metadata", {})
                        if isinstance(new_metadata, dict):
                            # Merge into session metadata (used for dynamic provider selection)
                            self.metadata.update(new_metadata)

                            # Update pipeline's metadata (shared dict reference)
                            if self.pipeline:
                                self.pipeline.metadata.update(new_metadata)

                            logger.debug(
                                "Session %s updated metadata from message (keys: %s)",
                                self.session_id,
                                list(new_metadata.keys())
                            )

                    # Convert to GatewayInputEvent
                    self._sequence += 1
                    event = GatewayInputEvent.from_acs_frame(
                        data,
                        sequence=self._sequence,
                        ctx=self.connection_ctx,
                    )

                    # Route to the session pipeline (handlers process all messages)
                    await self._route_message(event)

                except json.JSONDecodeError as e:
                    logger.warning(f"Session {self.session_id} invalid JSON: {e}")
                except Exception as e:
                    logger.exception(f"Session {self.session_id} error processing message: {e}")
        except websockets.ConnectionClosed:
            logger.info(f"Session {self.session_id} ACS disconnected")
        except Exception as e:
            logger.exception(f"Session {self.session_id} receive loop error: {e}")
        finally:
            await self._initiate_shutdown("ACS websocket disconnected")

    async def _route_message(self, envelope: GatewayInputEvent):
        """Route message to the session pipeline."""
        if self.pipeline is None:
            logger.warning("Session %s received message before pipeline initialization", self.session_id)
            return

        await self.pipeline.process_message(envelope)

    async def _acs_send_loop(self):
        """Keep send task alive (pipelines send directly to WebSocket)."""
        try:
            # Wait until shutdown is triggered
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            logger.debug(f"Session {self.session_id} send loop cancelled")

    async def _initiate_shutdown(self, reason: str):
        """Trigger session shutdown once when ACS disconnects or errors."""
        if self._shutdown_event.is_set():
            return

        logger.info("Session %s initiating shutdown: %s", self.session_id, reason)
        self._shutdown_event.set()

    async def _initialize_acs_processing(self):
        """Initialize ACS processing stage (before receiving any messages).

        Creates the pipeline and starts ACS handlers. The provider will be
        selected dynamically and started later when AudioMetadata is received.
        """
        # Create single session-scoped pipeline (provider selected dynamically later)
        self.pipeline = SessionPipeline(
            session_id=self.canonical_session_id,
            config=self.config,
            metadata=self.metadata,  # Empty at this point, will be updated as messages arrive
            translation_settings=self.translation_settings  # Empty at this point, will be updated by TestSettingsHandler
        )

        # Start ACS processing (handlers ready to receive and queue messages)
        await self.pipeline.start_acs_processing()

        # Subscribe to its outbound bus
        await self._subscribe_to_pipeline_output(self.pipeline)

        logger.info("Session %s ACS processing initialized", self.session_id)

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
        gate_handler = AcsOutboundGateHandler(
            HandlerSettings(
                name=f"acs_outbound_gate_{pipeline.pipeline_id}",
                queue_max=1000,
                overflow_policy="DROP_OLDEST",
            ),
            send_callable=send_to_acs,
            gate_is_open=pipeline.is_outbound_gate_open,
            control_plane=pipeline.control_plane,
            on_audio_dropped=lambda reason: pipeline.control_plane.mark_playback_inactive(reason or "gate_drop"),
        )

        # Register handler on pipeline's outbound bus
        await pipeline.acs_outbound_bus.register_handler(
            HandlerConfig(
                name=f"acs_websocket_send_{pipeline.pipeline_id}",
                queue_max=1000,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1
            ),
            gate_handler,
        )

        # Tap outbound ACS messages for control plane state
        await pipeline.acs_outbound_bus.register_handler(
            HandlerConfig(
                name=f"control_plane_acs_out_{pipeline.pipeline_id}",
                queue_max=200,
                overflow_policy=OverflowPolicy.DROP_NEWEST,
                concurrency=1,
            ),
            ControlPlaneBusHandler(
                HandlerSettings(
                    name=f"control_plane_acs_out_{pipeline.pipeline_id}",
                    queue_max=200,
                    overflow_policy=str(OverflowPolicy.DROP_NEWEST),
                ),
                control_plane=pipeline.control_plane,
                source="acs_outbound",
            ),
        )

    async def cleanup(self):
        """Cleanup session resources."""
        if self._cleanup_started:
            return

        self._cleanup_started = True
        self._shutdown_event.set()
        logger.info(f"Session {self.session_id} cleanup started")

        # Close WebSocket to unblock receive loop quickly
        if not self.websocket.closed:
            try:
                await self.websocket.close()
            except Exception as e:
                logger.exception("Session %s failed to close WebSocket: %s", self.session_id, e)

        # Cancel tasks
        tasks_to_cancel = []
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            tasks_to_cancel.append(self._receive_task)
        if self._send_task and not self._send_task.done():
            self._send_task.cancel()
            tasks_to_cancel.append(self._send_task)

        for task in tasks_to_cancel:
            try:
                await task
            except asyncio.CancelledError:
                logger.debug("Session %s task %s cancelled", self.session_id, task.get_name())
            except Exception as e:
                logger.exception("Session %s task %s error during cancellation: %s", self.session_id, task.get_name(), e)

        # Cleanup pipeline
        if self.pipeline:
            await self.pipeline.cleanup()

        logger.info(f"Session {self.session_id} cleanup complete")

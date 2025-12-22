"""Session: manages one ACS WebSocket connection with dynamic routing."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import websockets
from websockets.server import WebSocketServerProtocol

from ..config import Config
from ..models.envelope import Envelope
from ..core.event_bus import HandlerConfig
from ..gateways.base import Handler, HandlerSettings
from ..core.queues import OverflowPolicy
from .participant_pipeline import ParticipantPipeline

logger = logging.getLogger(__name__)


class Session:
    """Manages one ACS WebSocket connection with dynamic routing strategies.

    Routing Strategies:
    - "shared": All participants share one pipeline (default, efficient)
    - "per_participant": Each participant gets own pipeline (isolated)

    Strategy determined from first message metadata.
    """

    def __init__(
        self,
        session_id: str,
        websocket: WebSocketServerProtocol,
        config: Config
    ):
        self.session_id = session_id
        self.websocket = websocket
        self.config = config

        # Session state
        self.routing_strategy: Optional[str] = None  # "shared" or "per_participant"
        self.metadata: Dict[str, Any] = {}

        # Routing modes
        # Mode 1: Shared pipeline (all participants share)
        self.shared_pipeline: Optional[ParticipantPipeline] = None

        # Mode 2: Per-participant pipelines
        self.participant_pipelines: Dict[str, ParticipantPipeline] = {}

        # Initialization flag
        self._initialized = False

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
        """Receive messages from ACS WebSocket and route to pipelines."""
        try:
            async for raw_message in self.websocket:
                try:
                    data = json.loads(raw_message)

                    # First message: extract metadata and initialize
                    if not self._initialized:
                        await self._initialize_from_first_message(data)

                    # Convert to Envelope
                    envelope = Envelope.from_acs_frame(
                        data,
                        sequence=0,
                        ingress_ws_id=self.session_id
                    )

                    # Route based on strategy
                    await self._route_message(envelope)

                except json.JSONDecodeError as e:
                    logger.warning(f"Session {self.session_id} invalid JSON: {e}")
                except Exception as e:
                    logger.exception(f"Session {self.session_id} error processing message: {e}")
        except websockets.ConnectionClosed:
            logger.info(f"Session {self.session_id} ACS disconnected")
        except Exception as e:
            logger.exception(f"Session {self.session_id} receive loop error: {e}")

    async def _route_message(self, envelope: Envelope):
        """Route message to appropriate pipeline(s)."""
        if self.routing_strategy == "shared":
            # All participants share one pipeline
            if self.shared_pipeline:
                await self.shared_pipeline.process_message(envelope)

        elif self.routing_strategy == "per_participant":
            # Get or create pipeline for this participant
            participant_id = envelope.participant_id or "default"

            if participant_id not in self.participant_pipelines:
                # Create new pipeline for this participant
                pipeline = await self._create_participant_pipeline(
                    participant_id,
                    envelope
                )
                self.participant_pipelines[participant_id] = pipeline

            # Route to participant's pipeline
            await self.participant_pipelines[participant_id].process_message(envelope)

    async def _acs_send_loop(self):
        """Keep send task alive (pipelines send directly to WebSocket)."""
        try:
            # This task just needs to stay alive
            # Actual sending is done by handlers subscribed to pipeline outbound buses
            await asyncio.Future()
        except asyncio.CancelledError:
            logger.debug(f"Session {self.session_id} send loop cancelled")

    async def _initialize_from_first_message(self, data: Dict[str, Any]):
        """Extract metadata and initialize routing strategy from first message."""
        self.metadata = data.get("metadata", {})

        # Determine routing strategy
        self.routing_strategy = self._select_routing_strategy(self.metadata)

        logger.info(
            f"Session {self.session_id} routing: {self.routing_strategy}"
        )

        if self.routing_strategy == "shared":
            # Create single shared pipeline
            participant_id = "shared"
            provider_name = self._select_provider(self.metadata, participant_id)

            self.shared_pipeline = ParticipantPipeline(
                session_id=self.session_id,
                participant_id=participant_id,
                config=self.config,
                provider_name=provider_name,
                metadata=self.metadata
            )
            await self.shared_pipeline.start()

            # Subscribe to its outbound bus
            await self._subscribe_to_pipeline_output(self.shared_pipeline)

        elif self.routing_strategy == "per_participant":
            # Pipelines created on-demand when participants send messages
            # (see _route_message and _create_participant_pipeline)
            pass

        self._initialized = True

    def _select_routing_strategy(self, metadata: Dict[str, Any]) -> str:
        """Select routing strategy based on ACS metadata."""
        # Strategy 1: Explicit routing in metadata
        if "routing" in metadata:
            routing = metadata["routing"]
            if routing in ["shared", "per_participant"]:
                return routing

        # Strategy 2: Feature flag
        if metadata.get("feature_flags", {}).get("per_participant_pipelines"):
            return "per_participant"

        # Strategy 3: Provider-specific requirements
        # Some providers might require per-participant isolation
        provider = metadata.get("provider", self.config.dispatch.provider)
        if provider in ["provider_requiring_isolation"]:
            return "per_participant"

        # Default: shared pipeline (more efficient)
        return "shared"

    def _select_provider(
        self,
        metadata: Dict[str, Any],
        participant_id: str
    ) -> str:
        """Select provider based on ACS metadata and participant."""
        # Strategy 1: Per-participant provider override
        participant_providers = metadata.get("participant_providers", {})
        if participant_id in participant_providers:
            return participant_providers[participant_id]

        # Strategy 2: Explicit provider in metadata
        if "provider" in metadata:
            return metadata["provider"]

        # Strategy 3: Customer/tenant-based routing
        if "customer_id" in metadata:
            # Could have per-customer provider mapping
            # customer_provider_map = self.config.customer_providers
            # return customer_provider_map.get(metadata["customer_id"], self.config.dispatch.provider)
            pass

        # Strategy 4: Feature flags
        if metadata.get("feature_flags", {}).get("use_voicelive"):
            return "voicelive"

        # Default: use config
        return self.config.dispatch.provider

    async def _create_participant_pipeline(
        self,
        participant_id: str,
        envelope: Envelope
    ) -> ParticipantPipeline:
        """Create pipeline for a new participant (per_participant mode)."""
        # Determine provider for this participant
        provider_type = self._select_provider(self.metadata, participant_id)

        logger.info(
            f"Session {self.session_id} creating pipeline for participant {participant_id}: "
            f"provider={provider_type}"
        )

        # Create pipeline
        pipeline = ParticipantPipeline(
            session_id=self.session_id,
            participant_id=participant_id,
            config=self.config,
            provider_name=provider_type,
            metadata=self.metadata
        )

        # Start pipeline
        await pipeline.start()

        # Subscribe to its outbound bus
        await self._subscribe_to_pipeline_output(pipeline)

        return pipeline

    async def _subscribe_to_pipeline_output(self, pipeline: ParticipantPipeline):
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
            async def handle(self, payload: Dict[str, Any]):
                await send_to_acs(payload)

        # Register handler on pipeline's outbound bus
        await pipeline.acs_outbound_bus.register_handler(
            HandlerConfig(
                name=f"acs_websocket_send_{pipeline.participant_id}",
                queue_max=1000,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1
            ),
            ACSWebSocketSender(
                HandlerSettings(
                    name=f"acs_websocket_send_{pipeline.participant_id}",
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

        # Cleanup pipelines based on routing strategy
        if self.routing_strategy == "shared":
            if self.shared_pipeline:
                await self.shared_pipeline.cleanup()

        elif self.routing_strategy == "per_participant":
            for pipeline in self.participant_pipelines.values():
                await pipeline.cleanup()

        # Close WebSocket
        if not self.websocket.closed:
            await self.websocket.close()

        logger.info(f"Session {self.session_id} cleanup complete")

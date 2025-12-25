"""ACS WebSocket server: listens for incoming ACS connections."""

from __future__ import annotations

import asyncio
import logging
import uuid

import websockets
from websockets.server import WebSocketServerProtocol

from ..config import Config
from ..models.gateway_input_event import ConnectionContext
from ..session.session_manager import SessionManager
from .websocket_server import WebSocketServer
from .wire_log_sink import WireLogSink

logger = logging.getLogger(__name__)


class ACSServer:
    """WebSocket server that listens for incoming ACS connections.

    Each incoming connection creates a Session that handles:
    - Message routing (shared or per-participant)
    - Provider selection
    - Translation pipeline management
    """

    def __init__(
        self,
        config: Config,
        host: str = "0.0.0.0",
        port: int = 8080
    ):
        self.config = config
        self.host = host
        self.port = port
        self.session_manager = SessionManager(config)
        self._server = None

    async def start(self):
        """Start WebSocket server and run forever."""
        logger.info(f"Starting ACS server on {self.host}:{self.port}")

        async with websockets.serve(
            self._handle_connection,
            self.host,
            self.port
        ) as server:
            self._server = server
            logger.info(f"ACS server listening on {self.host}:{self.port}")
            logger.info(f"Provider: {self.config.dispatch.provider} (default)")
            logger.info(f"Routing: dynamic from metadata (default: shared)")

            # Run forever
            await asyncio.Future()

    async def _handle_connection(
        self,
        websocket: WebSocketServerProtocol,
        path: str
    ):
        """Handle incoming ACS WebSocket connection."""
        client_addr = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"New ACS connection from {client_addr}")

        connection_ctx = ConnectionContext(
            ingress_ws_id=str(uuid.uuid4()),
            call_connection_id=websocket.request_headers.get("x-ms-call-connection-id"),
            call_correlation_id=websocket.request_headers.get("x-ms-call-correlation-id"),
        )

        websocket_name = f"acs_server_{connection_ctx.ingress_ws_id}"
        log_sink = WireLogSink(websocket_name) if self.config.system.log_wire else None
        wrapped_websocket = WebSocketServer(
            websocket=websocket,
            name=websocket_name,
            debug_wire=self.config.system.log_wire,
            log_sink=log_sink,
        )

        # Create session
        session = await self.session_manager.create_session(wrapped_websocket, connection_ctx)

        try:
            # Run session (blocks until disconnect)
            await session.run()
        except Exception as e:
            logger.exception(f"Session {session.session_id} error: {e}")
        finally:
            # Remove session
            await self.session_manager.remove_session(session.session_id)
            logger.info(f"ACS connection from {client_addr} closed")

    async def shutdown(self):
        """Shutdown server and all sessions."""
        logger.info("Shutting down ACS server")
        await self.session_manager.shutdown_all()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("ACS server shut down")

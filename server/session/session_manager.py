"""Session manager: tracks active ACS WebSocket sessions."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Dict

from websockets.server import WebSocketServerProtocol

from ..config import Config
from ..models.gateway_input_event import ConnectionContext
from .session import Session

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages active ACS WebSocket sessions.

    Responsibilities:
    - Create sessions for new ACS connections
    - Track active sessions
    - Remove sessions on disconnect
    - Shutdown all sessions on server shutdown
    """

    def __init__(self, config: Config):
        self.config = config
        self.sessions: Dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        websocket: WebSocketServerProtocol,
        connection_ctx: ConnectionContext
    ) -> Session:
        """Create new session for ACS connection."""
        async with self._lock:
            session_id = connection_ctx.ingress_ws_id or str(uuid.uuid4())
            session = Session(
                session_id=session_id,
                websocket=websocket,
                config=self.config,
                connection_ctx=connection_ctx,
            )
            self.sessions[session_id] = session
            logger.info(f"Created session {session_id}")
            return session

    async def remove_session(self, session_id: str):
        """Remove session and cleanup."""
        async with self._lock:
            session = self.sessions.pop(session_id, None)
            if session:
                await session.cleanup()
                logger.info(f"Removed session {session_id}")

    async def shutdown_all(self):
        """Shutdown all active sessions."""
        logger.info("Shutting down all sessions")
        async with self._lock:
            for session in list(self.sessions.values()):
                await session.cleanup()
            self.sessions.clear()
        logger.info("All sessions shut down")

    def get_active_count(self) -> int:
        """Get count of active sessions."""
        return len(self.sessions)

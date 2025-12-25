"""WebSocket server wrapper with optional wire logging."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Optional

from websockets.server import WebSocketServerProtocol

from .wire_log_sink import WireLogSink

logger = logging.getLogger(__name__)


class WebSocketServer:
    """Lightweight wrapper that adds debug logging for server-side WebSockets."""

    def __init__(
        self,
        websocket: WebSocketServerProtocol,
        name: str,
        debug_wire: bool = False,
        log_sink: Optional[WireLogSink] = None,
    ) -> None:
        self.websocket = websocket
        self.name = name
        self.debug_wire = debug_wire
        self.log_sink = log_sink

    def __aiter__(self) -> AsyncIterator[Any]:
        return self

    async def __anext__(self):
        message = await self.recv()
        return message

    async def send(self, message: str) -> None:
        self._record("outbound", message)
        await self.websocket.send(message)

    async def recv(self) -> Any:
        message = await self.websocket.recv()
        self._record("inbound", message)
        return message

    async def close(self) -> None:
        await self.websocket.close()

    @property
    def closed(self) -> bool:
        return self.websocket.closed

    def _record(self, direction: str, message: Any) -> None:
        if not self.debug_wire:
            return

        logger.debug("WS[%s] %s: %s", self.name, direction, message)

        if not self.log_sink:
            return

        normalized = self._normalize_message(message)
        self.log_sink.append_message(
            {"direction": direction, "message": normalized, "name": self.name}
        )

    @staticmethod
    def _normalize_message(message: Any) -> Any:
        if isinstance(message, str):
            try:
                return json.loads(message)
            except json.JSONDecodeError:
                return message
        return message


__all__ = ["WebSocketServer"]

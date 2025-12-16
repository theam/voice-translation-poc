"""Async WebSocket client wrapper used by the ACS emulator."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

import websockets
from websockets.client import WebSocketClientProtocol

from production.capture.raw_log_sink import RawLogSink

logger = logging.getLogger(__name__)


class WebSocketClient:
    """Lightweight wrapper around `websockets` for JSON messaging."""

    def __init__(
        self,
        url: str,
        auth_key: Optional[str] = None,
        connect_timeout: float = 10.0,
        debug_wire: bool = False,
        log_sink: Optional[RawLogSink] = None
    ) -> None:
        self.url = url
        self.auth_key = auth_key
        self.connect_timeout = connect_timeout
        self.debug_wire = debug_wire
        self.log_sink = log_sink
        self._conn: Optional[WebSocketClientProtocol] = None

    async def __aenter__(self) -> "WebSocketClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        await self.close()

    async def connect(self) -> None:
        headers = {"Authorization": self.auth_key} if self.auth_key else None
        logger.info("Connecting to translation service at %s", self.url)
        # Increase max_size to 10MB to handle large translation responses
        # Default is 1MB which can be exceeded by long audio translations
        self._conn = await asyncio.wait_for(
            websockets.connect(
                self.url,
                extra_headers=headers,
                max_size=10 * 1024 * 1024  # 10MB limit
            ),
            timeout=self.connect_timeout
        )

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def send_json(self, payload: Dict[str, Any]) -> None:
        if not self._conn:
            raise RuntimeError("WebSocket connection not established")
        message = json.dumps(payload)
        if self.debug_wire and self.log_sink:
            self.log_sink.append_message({"direction": "outbound", "message": payload})
        await self._conn.send(message)

    async def receive_json(self) -> Dict[str, Any]:
        if not self._conn:
            raise RuntimeError("WebSocket connection not established")
        raw = await self._conn.recv()
        parsed = json.loads(raw)
        if self.debug_wire and self.log_sink:
            self.log_sink.append_message({"direction": "inbound", "message": parsed})
        return parsed

    async def iter_messages(self) -> AsyncIterator[Dict[str, Any]]:
        if not self._conn:
            raise RuntimeError("WebSocket connection not established")
        async for raw in self._conn:
            parsed = json.loads(raw)
            if self.debug_wire and self.log_sink:
                self.log_sink.append_message({"direction": "inbound", "message": parsed})
            yield parsed


__all__ = ["WebSocketClient"]

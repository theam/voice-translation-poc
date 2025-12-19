from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import websockets

logger = logging.getLogger(__name__)


class ACSEgressAdapter:
    def __init__(self, url: str, reconnect_delay: float = 1.0):
        self.url = url
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._lock = asyncio.Lock()
        self._reconnect_delay = reconnect_delay

    async def connect(self) -> None:
        async with self._lock:
            if self._ws is not None and not self._ws.closed:
                return
            self._ws = await websockets.connect(self.url)
            logger.info("Connected to ACS egress WebSocket")

    async def send(self, payload: dict) -> None:
        attempt = 0
        while True:
            try:
                await self.connect()
                assert self._ws is not None
                await self._ws.send(json.dumps(payload))
                return
            except Exception:
                attempt += 1
                logger.exception("Failed to send to egress; attempt=%s", attempt)
                await asyncio.sleep(min(self._reconnect_delay * attempt, 10))

    async def close(self) -> None:
        async with self._lock:
            if self._ws:
                await self._ws.close()
                logger.info("Closed ACS egress WebSocket")


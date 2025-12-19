from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import AsyncIterator, Dict, Optional

import websockets

from ..envelope import Envelope

logger = logging.getLogger(__name__)


class ACSIngressAdapter:
    def __init__(self, url: str, reconnect, *, ingress_id: Optional[str] = None):
        self.url = url
        self.reconnect = reconnect
        self.ingress_id = ingress_id or str(uuid.uuid4())
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._sequence = 0

    async def connect(self) -> websockets.WebSocketClientProtocol:
        if self._ws and not self._ws.closed:
            return self._ws
        self._ws = await websockets.connect(self.url)
        logger.info("Connected to ACS ingress WebSocket id=%s", self.ingress_id)
        return self._ws

    async def _receive_loop(self) -> AsyncIterator[Dict]:
        backoff = self.reconnect.initial_delay_ms / 1000
        while True:
            try:
                ws = await self.connect()
                async for raw in ws:
                    try:
                        frame = json.loads(raw)
                        yield frame
                    except json.JSONDecodeError:
                        logger.warning("Skipping non-JSON frame: %s", raw)
            except websockets.ConnectionClosed:
                logger.warning("ACS connection closed; reconnecting")
            except Exception:
                logger.exception("ACS ingress receive loop error")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.reconnect.max_delay_ms / 1000)

    async def envelopes(self) -> AsyncIterator[Envelope]:
        async for frame in self._receive_loop():
            self._sequence += 1
            envelope = Envelope.from_acs_frame(frame, sequence=self._sequence, ingress_ws_id=self.ingress_id)
            yield envelope

    async def close(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
            logger.info("Closed ACS ingress WebSocket id=%s", self.ingress_id)


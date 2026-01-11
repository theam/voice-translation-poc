from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict

import websockets

logger = logging.getLogger(__name__)


class UpstreamConnection:
    def __init__(
        self,
        url: str,
        headers: Dict[str, str] | None,
        on_message: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._url = url
        self._headers = headers or {}
        self._on_message = on_message
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._tasks: list[asyncio.Task] = []
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        async with self._lock:
            if self._ws:
                return
            import time
            start_time = time.time()
            logger.info("Connecting upstream websocket: %s", self._url)
            try:
                # Add timeout to websockets.connect and asyncio.wait_for for double protection
                self._ws = await asyncio.wait_for(
                    websockets.connect(
                        self._url,
                        extra_headers=self._headers,
                        open_timeout=3.0,  # Timeout for opening handshake
                        close_timeout=2.0   # Timeout for closing handshake
                    ),
                    timeout=5.0  # Overall timeout
                )
                elapsed = time.time() - start_time
                logger.info("Upstream websocket connected successfully in %.2fs", elapsed)
                self._tasks = [
                    asyncio.create_task(self._send_loop(), name="upstream-send"),
                    asyncio.create_task(self._receive_loop(), name="upstream-receive"),
                ]
            except asyncio.TimeoutError:
                elapsed = time.time() - start_time
                logger.error("Upstream websocket connection timeout after %.2fs: %s", elapsed, self._url)
                raise
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error("Upstream websocket connection failed after %.2fs: %s", elapsed, e)
                raise

    async def close(self) -> None:
        async with self._lock:
            tasks = list(self._tasks)
            self._tasks.clear()
            if self._ws:
                await self._ws.close()
            self._ws = None

        for task in tasks:
            task.cancel()

    async def send_json(self, payload: Dict[str, Any]) -> None:
        await self._queue.put(json.dumps(payload))

    async def _send_loop(self) -> None:
        while True:
            message = await self._queue.get()
            if not self._ws:
                continue
            await self._ws.send(message)

    async def _receive_loop(self) -> None:
        if not self._ws:
            return
        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    logger.debug("Ignoring upstream binary message")
                    continue
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    logger.warning("Ignoring non-JSON upstream message")
                    continue
                await self._on_message(payload)
        except websockets.ConnectionClosed:
            logger.info("Upstream websocket closed")

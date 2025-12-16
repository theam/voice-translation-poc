from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, Optional

from production.capture.raw_log_sink import RawLogSink

logger = logging.getLogger(__name__)


class WebSocketLoopbackClient:
    """WebSocket client that echoes messages with configurable latency.

    Latency is applied on send, not receive, to better simulate network /
    service processing delays and avoid consumer-side timing artifacts.
    """

    def __init__(
        self,
        url: str,
        latency_ms: int = 100,
        auth_key: Optional[str] = None,
        connect_timeout: float = 10.0,
        debug_wire: bool = False,
        log_sink: Optional[RawLogSink] = None,
    ) -> None:
        self.url = url
        self.latency_ms = latency_ms
        self.auth_key = auth_key
        self.connect_timeout = connect_timeout
        self.debug_wire = debug_wire
        self.log_sink = log_sink

        self._connected = False
        self._response_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._pending_tasks: set[asyncio.Task] = set()

    async def __aenter__(self) -> "WebSocketLoopbackClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        await self.close()

    async def connect(self) -> None:
        logger.info("Loopback client 'connecting' (no actual network connection)")
        self._connected = True

    async def close(self) -> None:
        if not self._connected:
            return

        logger.info("Loopback client 'closing'")
        self._connected = False

        # Cancel any pending delayed-send tasks
        for task in self._pending_tasks:
            task.cancel()
        self._pending_tasks.clear()

    async def send_json(self, payload: Dict[str, Any]) -> None:
        """Send JSON message by echoing it back after simulated latency."""
        if not self._connected:
            raise RuntimeError("WebSocket connection not established")

        if self.debug_wire and self.log_sink:
            self.log_sink.append_message(
                {"direction": "outbound", "message": payload}
            )

        await self._response_queue.put(payload)

    async def receive_json(self) -> Dict[str, Any]:
        """Receive a JSON message (blocking, no artificial delay)."""
        if not self._connected:
            raise RuntimeError("WebSocket connection not established")

        response = await self._response_queue.get()

        if self.debug_wire and self.log_sink:
            self.log_sink.append_message(
                {"direction": "inbound", "message": response}
            )

        return response

    async def iter_messages(self) -> AsyncIterator[Dict[str, Any]]:
        """Iterate over incoming messages."""
        if not self._connected:
            raise RuntimeError("WebSocket connection not established")

        while self._connected:
            try:
                response = await asyncio.wait_for(
                    self._response_queue.get(),
                    timeout=0.1,
                )

                if self.debug_wire and self.log_sink:
                    self.log_sink.append_message(
                        {"direction": "inbound", "message": response}
                    )

                yield response

            except asyncio.TimeoutError:
                continue


__all__ = ["WebSocketLoopbackClient"]

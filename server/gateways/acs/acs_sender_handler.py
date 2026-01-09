from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from ..base import Handler


class AcsWebsocketSendHandler(Handler):
    def __init__(self, send_callable: Callable[[Dict[str, Any]], Awaitable[None]]):
        self._send = send_callable

    def can_handle(self, event: Dict[str, Any]) -> bool:
        return isinstance(event, dict)

    async def handle(self, event: Dict[str, Any]) -> None:
        await self._send(event)

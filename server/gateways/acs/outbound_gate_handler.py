from __future__ import annotations

import logging
from typing import Awaitable, Callable, Dict, Optional

from ..base import Handler, HandlerSettings

logger = logging.getLogger(__name__)


class AcsOutboundGateHandler(Handler):
    """Choke point for outbound ACS messages controlled by the control plane."""

    def __init__(
        self,
        settings: HandlerSettings,
        *,
        send_callable: Callable[[Dict[str, Any]], Awaitable[None]],
        gate_is_open: Callable[[], bool],
        session_id: str,
        on_audio_dropped: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(settings)
        self._send = send_callable
        self._gate_is_open = gate_is_open
        self._session_id = session_id
        self._on_audio_dropped = on_audio_dropped

    async def handle(self, payload: Dict[str, Any]) -> None:  # type: ignore[override]
        is_audio = self._is_audio_payload(payload)

        if is_audio and not self._gate_is_open():
            logger.info(
                "outbound_gate_closed session=%s dropping_audio=True",
                self._session_id,
            )
            if self._on_audio_dropped:
                self._on_audio_dropped("gate_closed")
            return

        await self._send(payload)

    @staticmethod
    def _is_audio_payload(payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        kind = payload.get("kind") or payload.get("type")
        if kind in {"audioData", "audio.data"}:
            return True
        audio_data = payload.get("audioData") or payload.get("audio_data")
        return isinstance(audio_data, dict) and "data" in audio_data


__all__ = ["AcsOutboundGateHandler"]

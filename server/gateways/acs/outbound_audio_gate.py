from __future__ import annotations

import logging
from collections import deque
from enum import Enum
from typing import Any, Awaitable, Callable, Deque, Dict, Optional

from ..base import Handler, HandlerSettings
from ...session.control.input_state import InputState, InputStatus

logger = logging.getLogger(__name__)


class OutboundGateMode(str, Enum):
    PLAY_THROUGH = "play_through"
    PAUSE_AND_BUFFER = "pause_and_buffer"
    PAUSE_AND_DROP = "pause_and_drop"

    @classmethod
    def from_value(cls, value: Optional[str]) -> "OutboundGateMode":
        if not value:
            return cls.PLAY_THROUGH
        normalized = str(value).strip().lower()
        for mode in cls:
            if mode.value == normalized:
                return mode
        return cls.PLAY_THROUGH


class OutboundAudioGate(Handler):
    """Choke point for outbound ACS audio governed by input state."""

    DEFAULT_BUFFER_LIMIT_BYTES = 5 * 1024 * 1024

    def __init__(
        self,
        settings: HandlerSettings,
        *,
        send_callable: Callable[[Dict[str, Any]], Awaitable[None]],
        input_state: InputState,
        gate_mode: OutboundGateMode,
        session_id: str,
        buffer_limit_bytes: Optional[int] = None,
    ) -> None:
        super().__init__(settings)
        self._send = send_callable
        self._input_state = input_state
        self._gate_mode = gate_mode
        self._session_id = session_id
        self._buffer: Deque[Dict[str, Any]] = deque()
        self._buffer_bytes = 0
        self._buffer_limit_bytes = (
            self.DEFAULT_BUFFER_LIMIT_BYTES if buffer_limit_bytes is None else buffer_limit_bytes
        )

    async def handle(self, payload: Dict[str, Any]) -> None:  # type: ignore[override]
        if not self._is_audio_payload(payload):
            await self._send(payload)
            return

        if self._gate_mode == OutboundGateMode.PLAY_THROUGH:
            await self._send(payload)
            return

        if self._input_state.status == InputStatus.SPEAKING:
            if self._gate_mode == OutboundGateMode.PAUSE_AND_DROP:
                logger.info("outbound_gate_drop session=%s", self._session_id)
                return
            self._buffer_payload(payload)
            return

        await self._flush_buffer()
        await self._send(payload)

    async def on_input_state_changed(self, input_state: InputState) -> None:
        if (
            input_state.status == InputStatus.SILENCE
            and self._gate_mode == OutboundGateMode.PAUSE_AND_BUFFER
        ):
            await self._flush_buffer()

    def _buffer_payload(self, payload: Dict[str, Any]) -> None:
        self._buffer.append(payload)
        self._buffer_bytes += self._payload_size(payload)
        if self._buffer_limit_bytes and self._buffer_bytes > self._buffer_limit_bytes:
            dropped = self._buffer.popleft()
            self._buffer_bytes -= self._payload_size(dropped)
            logger.info(
                "outbound_gate_buffer_overflow session=%s buffer_bytes=%s limit=%s",
                self._session_id,
                self._buffer_bytes,
                self._buffer_limit_bytes,
            )

    async def _flush_buffer(self) -> None:
        if not self._buffer:
            return
        logger.info("outbound_gate_flush session=%s buffered_frames=%s", self._session_id, len(self._buffer))
        while self._buffer:
            await self._send(self._buffer.popleft())
        self._buffer_bytes = 0

    @staticmethod
    def _payload_size(payload: Dict[str, Any]) -> int:
        audio_data = payload.get("audioData") or payload.get("audio_data") or {}
        if isinstance(audio_data, dict):
            data = audio_data.get("data")
            if isinstance(data, str):
                return len(data)
        return 0

    @staticmethod
    def _is_audio_payload(payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        kind = payload.get("kind") or payload.get("type")
        if kind in {"audioData", "audio.data"}:
            return True
        audio_data = payload.get("audioData") or payload.get("audio_data")
        return isinstance(audio_data, dict) and "data" in audio_data


__all__ = ["OutboundAudioGate", "OutboundGateMode"]

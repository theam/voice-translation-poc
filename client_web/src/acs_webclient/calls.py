from __future__ import annotations

import asyncio
import logging
import secrets
import string
from dataclasses import dataclass, field
from typing import Any, Dict

from fastapi import WebSocket

from .config import Settings
from .protocol.acs import build_audio_message, build_audio_metadata, build_test_settings
from .upstream import UpstreamConnection

logger = logging.getLogger(__name__)

_CALL_ALPHABET = string.ascii_uppercase + string.digits


def _generate_call_code(length: int = 6) -> str:
    return "".join(secrets.choice(_CALL_ALPHABET) for _ in range(length))


@dataclass
class CallState:
    call_code: str
    provider: str
    barge_in: str
    settings: Settings
    participants: Dict[str, WebSocket] = field(default_factory=dict)
    upstream: UpstreamConnection | None = None
    subscription_id: str = field(default_factory=lambda: secrets.token_hex(8))
    metadata_sent: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def ensure_upstream(self) -> None:
        if self.upstream:
            return

        async def _broadcast(payload: Dict[str, Any]) -> None:
            await self.broadcast(payload)

        self.upstream = UpstreamConnection(
            url=self.settings.upstream_url,
            headers=self.settings.upstream_headers,
            on_message=_broadcast,
        )
        await self.upstream.connect()
        await self.upstream.send_json(
            build_test_settings(
                {
                    "provider": self.provider,
                    "outbound_gate_mode": self.barge_in,
                }
            )
        )

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        inactive = []
        for participant_id, websocket in self.participants.items():
            try:
                await websocket.send_json(payload)
            except Exception:
                logger.info("Dropping disconnected participant %s", participant_id)
                inactive.append(participant_id)
        for participant_id in inactive:
            self.participants.pop(participant_id, None)

    async def send_audio_metadata(self, sample_rate: int, channels: int, frame_bytes: int) -> None:
        if self.metadata_sent or not self.upstream:
            return
        payload = build_audio_metadata(sample_rate, channels, frame_bytes, self.subscription_id)
        await self.upstream.send_json(payload)
        self.metadata_sent = True

    async def send_audio(self, participant_id: str, pcm_bytes: bytes, timestamp_ms: int | None) -> None:
        if not self.upstream:
            return
        payload = build_audio_message(participant_id, pcm_bytes, timestamp_ms)
        await self.upstream.send_json(payload)


class CallManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._calls: Dict[str, CallState] = {}

    def create_call(self, provider: str, barge_in: str) -> CallState:
        call_code = _generate_call_code()
        call_state = CallState(
            call_code=call_code,
            provider=provider,
            barge_in=barge_in,
            settings=self._settings,
        )
        self._calls[call_code] = call_state
        return call_state

    def get_call(self, call_code: str) -> CallState | None:
        return self._calls.get(call_code)

    async def add_participant(self, call_code: str, participant_id: str, websocket: WebSocket) -> CallState:
        call_state = self._calls[call_code]
        call_state.participants[participant_id] = websocket
        await call_state.ensure_upstream()
        return call_state

    async def remove_participant(self, call_state: CallState, participant_id: str) -> None:
        call_state.participants.pop(participant_id, None)
        if not call_state.participants and call_state.upstream:
            await call_state.upstream.close()
            call_state.upstream = None
            call_state.metadata_sent = False

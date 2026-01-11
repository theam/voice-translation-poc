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
    service: str
    service_url: str
    provider: str
    barge_in: str
    settings: Settings
    participants: Dict[str, WebSocket] = field(default_factory=dict)
    upstream: UpstreamConnection | None = None
    subscription_id: str = field(default_factory=lambda: secrets.token_hex(8))
    metadata_sent: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def ensure_upstream(self) -> None:
        async with self.lock:
            if self.upstream:
                return

            logger.info("Establishing upstream connection for call %s to %s", self.call_code, self.service_url)

            async def _broadcast(payload: Dict[str, Any]) -> None:
                await self.broadcast(payload)

            self.upstream = UpstreamConnection(
                url=self.service_url,
                headers=self.settings.upstream_headers,
                on_message=_broadcast,
            )
            await self.upstream.connect()
            logger.info("Upstream connection established for call %s", self.call_code)
            await self.upstream.send_json(
                build_test_settings(
                    {
                        "provider": self.provider,
                        "outbound_gate_mode": self.barge_in,
                    }
                )
            )
            logger.info("Test settings sent to upstream for call %s", self.call_code)

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

    async def broadcast_participant_joined(self, participant_id: str) -> None:
        """Broadcast to all participants that a new participant joined."""
        await self.broadcast({
            "type": "participant.joined",
            "participant_id": participant_id,
            "participants": list(self.participants.keys()),
        })

    async def broadcast_participant_left(self, participant_id: str) -> None:
        """Broadcast to remaining participants that someone left."""
        await self.broadcast({
            "type": "participant.left",
            "participant_id": participant_id,
            "participants": list(self.participants.keys()),
        })

    async def send_participant_list(self, websocket: WebSocket) -> None:
        """Send current participant list to a specific participant."""
        await websocket.send_json({
            "type": "participant.list",
            "participants": list(self.participants.keys()),
        })

    async def send_audio_metadata(self, sample_rate: int, channels: int, frame_bytes: int) -> None:
        async with self.lock:
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
        await self.broadcast_audio_to_others(participant_id, payload)

    async def broadcast_audio_to_others(self, sender_participant_id: str, payload: Dict[str, Any]) -> None:
        inactive = []
        for participant_id, websocket in self.participants.items():
            if participant_id == sender_participant_id:
                continue
            try:
                await websocket.send_json(payload)
            except Exception:
                logger.info("Failed to send audio to participant %s", participant_id)
                inactive.append(participant_id)
        for participant_id in inactive:
            self.participants.pop(participant_id, None)


class CallManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._calls: Dict[str, CallState] = {}

    def create_call(self, service: str, service_url: str, provider: str, barge_in: str) -> CallState:
        call_code = _generate_call_code()
        call_state = CallState(
            call_code=call_code,
            service=service,
            service_url=service_url,
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

        # Send current participant list to the new participant
        await call_state.send_participant_list(websocket)

        # Broadcast to all participants that someone joined
        await call_state.broadcast_participant_joined(participant_id)
        logger.info("Participant %s joined call %s (%d total participants)",
                   participant_id, call_code, len(call_state.participants))

        return call_state

    async def remove_participant(self, call_state: CallState, participant_id: str) -> None:
        call_state.participants.pop(participant_id, None)
        logger.info("Participant %s left call %s (%d remaining participants)",
                   participant_id, call_state.call_code, len(call_state.participants))

        # Broadcast to remaining participants that someone left
        if call_state.participants:
            await call_state.broadcast_participant_left(participant_id)

        # Clean up upstream connection if last participant left
        if not call_state.participants and call_state.upstream:
            logger.info("Last participant left call %s, closing upstream connection", call_state.call_code)
            await call_state.upstream.close()
            call_state.upstream = None
            call_state.metadata_sent = False

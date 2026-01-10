from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import WebSocket

from .upstream import UpstreamConfig, UpstreamConnection, decode_audio_payload

logger = logging.getLogger(__name__)


@dataclass
class ParticipantConnection:
    participant_id: str
    display_name: str
    websocket: WebSocket
    muted: bool = False
    send_queue: asyncio.Queue[Dict[str, Any]] = field(default_factory=asyncio.Queue)
    send_task: asyncio.Task | None = None


class CallSession:
    def __init__(
        self,
        call_code: str,
        provider: str,
        barge_in: str,
        upstream_config: UpstreamConfig,
    ) -> None:
        self.call_code = call_code
        self.provider = provider
        self.barge_in = barge_in
        self.upstream = UpstreamConnection(
            call_id=call_code,
            provider=provider,
            barge_in=barge_in,
            config=upstream_config,
            on_event=self._handle_upstream_event,
        )
        self.participants: dict[str, ParticipantConnection] = {}
        self._last_empty_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        await self.upstream.start()

    async def add_participant(self, websocket: WebSocket, display_name: str) -> str:
        participant_id = _generate_participant_id()
        connection = ParticipantConnection(
            participant_id=participant_id,
            display_name=display_name,
            websocket=websocket,
        )
        async with self._lock:
            self.participants[participant_id] = connection
            self._last_empty_at = None
        connection.send_task = asyncio.create_task(self._send_loop(connection))
        await self._notify_existing_participants(connection)
        await self.broadcast_json({
            "type": "participant.joined",
            "participant_id": participant_id,
            "display_name": display_name,
        })
        return participant_id

    async def remove_participant(self, participant_id: str) -> None:
        async with self._lock:
            connection = self.participants.pop(participant_id, None)
            if not self.participants:
                self._last_empty_at = datetime.now(timezone.utc)
        if connection and connection.send_task:
            connection.send_task.cancel()
        await self.broadcast_json({
            "type": "participant.left",
            "participant_id": participant_id,
        })

    async def set_muted(self, participant_id: str, muted: bool) -> None:
        connection = self.participants.get(participant_id)
        if connection:
            connection.muted = muted

    async def handle_audio(self, participant_id: str, pcm_bytes: bytes) -> None:
        connection = self.participants.get(participant_id)
        if not connection or connection.muted:
            return
        await self.upstream.enqueue_audio(participant_id, pcm_bytes)
        await self._broadcast_audio(
            pcm_bytes,
            source="participant",
            participant_id=participant_id,
            exclude_participant=participant_id,
        )

    async def broadcast_json(self, payload: Dict[str, Any]) -> None:
        for connection in self.participants.values():
            connection.send_queue.put_nowait({"type": "json", "payload": payload})

    async def close(self) -> None:
        for participant_id in list(self.participants.keys()):
            await self.remove_participant(participant_id)
        await self.upstream.close()

    def is_expired(self, now: datetime, ttl: timedelta) -> bool:
        if self.participants:
            return False
        if not self._last_empty_at:
            return False
        return now - self._last_empty_at > ttl

    async def _send_loop(self, connection: ParticipantConnection) -> None:
        while True:
            message = await connection.send_queue.get()
            if message["type"] == "json":
                await connection.websocket.send_json(message["payload"])
            else:
                await connection.websocket.send_bytes(message["payload"])

    async def _notify_existing_participants(self, connection: ParticipantConnection) -> None:
        for participant in self.participants.values():
            if participant.participant_id == connection.participant_id:
                continue
            connection.send_queue.put_nowait({
                "type": "json",
                "payload": {
                    "type": "participant.joined",
                    "participant_id": participant.participant_id,
                    "display_name": participant.display_name,
                },
            })

    async def _handle_upstream_event(self, payload: Dict[str, Any]) -> None:
        kind = payload.get("kind")
        if kind == "AudioData":
            audio_bytes = decode_audio_payload(payload)
            if audio_bytes:
                await self._broadcast_audio(
                    audio_bytes,
                    source="service",
                    participant_id=None,
                )
            return

        await self.broadcast_json({
            "type": "acs.event",
            "event": payload,
        })

    async def _broadcast_audio(
        self,
        pcm_bytes: bytes,
        source: str,
        participant_id: Optional[str],
        exclude_participant: Optional[str] = None,
    ) -> None:
        header = {
            "type": "audio.play",
            "source": source,
            "participant_id": participant_id,
            "codec": "pcm16",
            "sample_rate_hz": 16000,
            "channels": 1,
        }
        for connection in self.participants.values():
            if exclude_participant and connection.participant_id == exclude_participant:
                continue
            connection.send_queue.put_nowait({"type": "json", "payload": header})
            connection.send_queue.put_nowait({"type": "bytes", "payload": pcm_bytes})


class CallRegistry:
    def __init__(self, upstream_config: UpstreamConfig, ttl_minutes: int) -> None:
        self._calls: Dict[str, CallSession] = {}
        self._upstream_config = upstream_config
        self._ttl = timedelta(minutes=ttl_minutes)
        self._lock = asyncio.Lock()

    async def create_call(self, provider: str, barge_in: str) -> CallSession:
        async with self._lock:
            call_code = _generate_call_code()
            while call_code in self._calls:
                call_code = _generate_call_code()
            session = CallSession(call_code, provider, barge_in, self._upstream_config)
            self._calls[call_code] = session
        await session.start()
        return session

    async def get_call(self, call_code: str) -> Optional[CallSession]:
        async with self._lock:
            return self._calls.get(call_code)

    async def cleanup_expired(self) -> None:
        now = datetime.now(timezone.utc)
        async with self._lock:
            expired = [
                code for code, call in self._calls.items()
                if call.is_expired(now, self._ttl)
            ]
        for code in expired:
            call = await self.get_call(code)
            if call:
                await call.close()
                async with self._lock:
                    self._calls.pop(code, None)
                logger.info("Cleaned up expired call %s", code)


def _generate_call_code() -> str:
    return secrets.token_hex(3).upper()


def _generate_participant_id() -> str:
    return f"participant-{secrets.token_hex(4)}"


__all__ = ["CallRegistry", "CallSession", "ParticipantConnection"]

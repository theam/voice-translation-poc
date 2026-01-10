from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from production.acs_emulator.media_engine import FRAME_DURATION_MS, calculate_frame_size
from production.acs_emulator.websocket_client import WebSocketClient

from .protocol.acs import AcsAudioMessage, ProtocolAdapter

logger = logging.getLogger(__name__)

OutboundPayload = Dict[str, Any]
InboundHandler = Callable[[OutboundPayload], Awaitable[None]]


@dataclass
class UpstreamConfig:
    websocket_url: str
    auth_key: Optional[str]
    connect_timeout: float
    debug_wire: bool


class UpstreamConnection:
    def __init__(
        self,
        call_id: str,
        provider: str,
        barge_in: str,
        config: UpstreamConfig,
        on_event: InboundHandler,
    ) -> None:
        self.call_id = call_id
        self.provider = provider
        self.barge_in = barge_in
        self.config = config
        self.on_event = on_event
        self._adapter = ProtocolAdapter(call_id=call_id)
        self._client: WebSocketClient | None = None
        self._send_queue: asyncio.Queue[OutboundPayload] = asyncio.Queue()
        self._send_task: asyncio.Task | None = None
        self._recv_task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._closed = False

    async def start(self) -> None:
        if self._client:
            return
        self._client = WebSocketClient(
            url=self.config.websocket_url,
            auth_key=self.config.auth_key,
            connect_timeout=self.config.connect_timeout,
            debug_wire=self.config.debug_wire,
        )
        await self._client.connect()
        await self._send_initial_messages()
        self._send_task = asyncio.create_task(self._send_loop())
        self._recv_task = asyncio.create_task(self._recv_loop())
        self._ready.set()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._send_task:
            self._send_task.cancel()
        if self._recv_task:
            self._recv_task.cancel()
        if self._client:
            await self._client.close()
            self._client = None

    async def wait_ready(self) -> None:
        await self._ready.wait()

    async def enqueue_audio(self, participant_id: str, pcm_bytes: bytes) -> None:
        timestamp_ms = int(time.time() * 1000)
        payload = self._adapter.build_audio_message(
            participant_id=participant_id,
            pcm_bytes=pcm_bytes,
            timestamp_ms=timestamp_ms,
        )
        await self._send_queue.put(payload)

    async def _send_initial_messages(self) -> None:
        if not self._client:
            raise RuntimeError("Upstream client not connected")
        settings = {
            "provider": self.provider,
            "outbound_gate_mode": self.barge_in,
        }
        await self._send_payload(self._adapter.build_test_settings(settings))

        frame_bytes = calculate_frame_size(
            sample_rate=16000,
            channels=1,
            sample_width=2,
            duration_ms=FRAME_DURATION_MS,
        )
        metadata = self._adapter.build_audio_metadata(
            sample_rate=16000,
            channels=1,
            frame_bytes=frame_bytes,
        )
        await self._send_payload(metadata)

    async def _send_loop(self) -> None:
        while True:
            payload = await self._send_queue.get()
            await self._send_payload(payload)

    async def _send_payload(self, payload: OutboundPayload) -> None:
        if not self._client:
            raise RuntimeError("Upstream client not connected")
        if not _is_allowed_outbound(payload):
            raise ValueError(f"Unsupported outbound ACS message: {payload}")
        await self._client.send_json(payload)

    async def _recv_loop(self) -> None:
        if not self._client:
            raise RuntimeError("Upstream client not connected")
        async for message in self._client.iter_messages():
            if _is_allowed_inbound(message):
                await self.on_event(message)
            else:
                logger.info("Ignoring unsupported inbound ACS event: %s", message)


def decode_audio_payload(payload: Dict[str, Any]) -> bytes | None:
    try:
        audio_message = AcsAudioMessage.from_dict(payload)
        return audio_message.data
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to decode ACS audio payload: %s", exc)
        return None


def _is_allowed_outbound(payload: Dict[str, Any]) -> bool:
    kind = payload.get("kind")
    if kind in {"AudioMetadata", "AudioData"}:
        return True
    return payload.get("type") == "control.test.settings"


def _is_allowed_inbound(payload: Dict[str, Any]) -> bool:
    kind = payload.get("kind")
    if kind in {"AudioData", "AudioMetadata"}:
        return True
    inbound_type = payload.get("type")
    return inbound_type in {
        "control.test.response.text",
        "control.test.response.text_delta",
        "system_info_response",
    }


__all__ = ["UpstreamConfig", "UpstreamConnection", "decode_audio_payload"]

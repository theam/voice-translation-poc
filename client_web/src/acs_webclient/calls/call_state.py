from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from typing import Any, Dict

from fastapi import WebSocket

from ..config import Settings
from ..protocol.acs import build_audio_message, build_audio_metadata, build_test_settings
from ..upstream import UpstreamConnection

logger = logging.getLogger(__name__)


@dataclass
class CallState:
    """
    Represents the state of a single call, including participants and upstream connection.

    Manages:
    - Participant WebSocket connections
    - Optional upstream translation service connection
    - Audio metadata and message routing
    - Participant join/leave notifications
    """
    call_code: str
    settings: Settings
    service: str | None = None
    service_url: str | None = None
    provider: str | None = None
    barge_in: str | None = None
    participants: Dict[str, WebSocket] = field(default_factory=dict)
    upstream: UpstreamConnection | None = None
    subscription_id: str = field(default_factory=lambda: secrets.token_hex(8))
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def ensure_upstream(self) -> None:
        """
        Establish upstream connection to translation service if not already connected.
        Sends test settings and audio metadata immediately after connection.
        Does nothing if translation service is not configured.
        """
        async with self.lock:
            if self.upstream:
                return

            # Skip if no translation service configured
            if not self.service_url:
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

            # Send test settings
            await self.upstream.send_json(
                build_test_settings(
                    {
                        "provider": self.provider,
                        "outbound_gate_mode": self.barge_in,
                    }
                )
            )

            # Send audio metadata with enforced ACS format
            await self.upstream.send_json(build_audio_metadata(self.subscription_id))
            logger.info("Upstream configured for call %s (16kHz mono PCM16)", self.call_code)

    async def connect_translation_service(self, service: str, service_url: str, provider: str, barge_in: str) -> None:
        """
        Connect a translation service to this call.
        Closes any existing upstream connection first.
        """
        # Notify participants that connection is starting
        await self.broadcast({
            "type": "translation.connecting",
            "message": f"Connecting translation service ({service}, {provider})..."
        })

        async with self.lock:
            # Close existing upstream connection if any
            if self.upstream:
                logger.info("Closing existing upstream connection for call %s", self.call_code)
                await self.upstream.close()
                self.upstream = None

            # Update translation service configuration
            self.service = service
            self.service_url = service_url
            self.provider = provider
            self.barge_in = barge_in
            self.subscription_id = secrets.token_hex(8)  # New subscription ID

        # Establish new connection (releases lock first)
        await self.ensure_upstream()

        # Notify participants that connection is established
        await self.broadcast({
            "type": "translation.connected",
            "message": f"Translation service connected ({service}, {provider})"
        })

    async def disconnect_translation_service(self) -> None:
        """
        Disconnect the translation service from this call.
        Participants can continue talking to each other.
        """
        async with self.lock:
            if self.upstream:
                logger.info("Disconnecting translation service from call %s", self.call_code)
                await self.upstream.close()
                self.upstream = None

            # Clear translation service configuration
            self.service = None
            self.service_url = None
            self.provider = None
            self.barge_in = None

        # Notify participants that translation service was disconnected
        await self.broadcast({
            "type": "translation.disconnected",
            "message": "Translation service disconnected"
        })

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        """
        Broadcast a message to all participants in the call concurrently.
        Uses asyncio tasks for fan-out to minimize latency.

        Injects 'vt-translation-service' as participantRawID for translation
        service audio responses that don't have a participant ID.
        """
        if not self.participants:
            return

        # Always tag translation service audio with consistent participant ID
        # Check both "AudioData" (what we send) and "audioData" (what upstream might return)
        kind = payload.get("kind", "")
        if kind in ("AudioData", "audioData") and "audioData" in payload:
            payload["audioData"]["participantRawID"] = "vt-translation-service"

        async def _send_to_participant(participant_id: str, websocket: WebSocket) -> str | None:
            """Send to one participant, return participant_id if failed."""
            try:
                await websocket.send_json(payload)
                return None
            except Exception:
                logger.info("Dropping disconnected participant %s", participant_id)
                return participant_id

        # Fan out to all participants concurrently
        tasks = [
            _send_to_participant(participant_id, websocket)
            for participant_id, websocket in self.participants.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Clean up inactive participants
        inactive = [pid for pid in results if pid is not None and isinstance(pid, str)]
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

    async def send_audio(self, participant_id: str, pcm_bytes: bytes, timestamp_ms: int | None) -> None:
        """
        Send audio to upstream translation service and broadcast to other participants concurrently.
        Audio from sender is excluded from broadcast (no echo).
        """
        payload = build_audio_message(participant_id, pcm_bytes, timestamp_ms)

        tasks = [self.broadcast_audio_to_others(participant_id, payload)]
        if self.upstream:
            tasks.append(self.upstream.send_json(payload))

        # Send to upstream (if configured) and broadcast to participants concurrently for minimal latency
        await asyncio.gather(*tasks, return_exceptions=True)

    async def broadcast_audio_to_others(self, sender_participant_id: str, payload: Dict[str, Any]) -> None:
        """
        Broadcast audio to all participants except the sender concurrently (prevents echo).
        Uses asyncio tasks for fan-out to minimize latency - critical for audio.
        """
        # Filter out sender to prevent echo
        recipients = {
            pid: ws for pid, ws in self.participants.items()
            if pid != sender_participant_id
        }

        if not recipients:
            return

        async def _send_to_participant(participant_id: str, websocket: WebSocket) -> str | None:
            """Send to one participant, return participant_id if failed."""
            try:
                await websocket.send_json(payload)
                return None
            except Exception:
                logger.info("Failed to send audio to participant %s", participant_id)
                return participant_id

        # Fan out to all recipients concurrently
        tasks = [
            _send_to_participant(participant_id, websocket)
            for participant_id, websocket in recipients.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Clean up inactive participants
        inactive = [pid for pid in results if pid is not None and isinstance(pid, str)]
        for participant_id in inactive:
            self.participants.pop(participant_id, None)

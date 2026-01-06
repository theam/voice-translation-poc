from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, Type

from ..gateways.base import Handler, HandlerSettings
from ..models.gateway_input_event import GatewayInputEvent
from ..models.provider_events import ProviderOutputEvent

logger = logging.getLogger(__name__)


@dataclass
class ControlEvent:
    """Normalized control-plane event extracted from internal envelopes."""

    session_id: str
    kind: str
    payload: Dict[str, Any]
    participant_id: Optional[str] = None
    provider_response_id: Optional[str] = None
    commit_id: Optional[str] = None
    timestamp_ms: Optional[int] = None


def _now_ms() -> int:
    return int(time.time() * 1000)


def control_event_from_gateway(event: GatewayInputEvent) -> ControlEvent:
    payload = event.payload or {}
    participant_id = None
    if isinstance(payload, dict):
        audio_data = payload.get("audiodata") or {}
        if isinstance(audio_data, dict):
            participant_id = audio_data.get("participantrawid")

    return ControlEvent(
        session_id=event.session_id,
        kind="gateway.input",
        payload=payload,
        participant_id=participant_id,
        timestamp_ms=_now_ms(),
    )


def control_event_from_provider(event: ProviderOutputEvent) -> ControlEvent:
    kind = f"provider.{event.event_type}" if event.event_type else "provider.unknown"
    return ControlEvent(
        session_id=event.session_id,
        participant_id=event.participant_id,
        kind=kind,
        payload=event.payload or {},
        provider_response_id=event.provider_response_id or event.stream_id,
        commit_id=event.commit_id,
        timestamp_ms=event.timestamp_ms,
    )


def control_event_from_acs_outbound(session_id: str, payload: Dict[str, Any]) -> Optional[ControlEvent]:
    if not isinstance(payload, dict):
        return None

    kind = payload.get("kind")
    if kind not in {"audioData", "audio.data"}:
        return None

    audio_data = payload.get("audioData") or payload.get("audio_data") or {}
    participant_id = None
    if isinstance(audio_data, dict):
        participant_id = audio_data.get("participant") or audio_data.get("participantrawid")

    return ControlEvent(
        session_id=session_id,
        participant_id=participant_id,
        kind="acs_outbound.audio",
        payload=payload,
        timestamp_ms=_now_ms(),
    )


class SessionControlPlane:
    """Per-session control plane consuming internal events and issuing actions."""

    def __init__(
        self,
        session_id: str,
        pipeline_actuator: "SessionPipelineProtocol",
        *,
        queue_max: int = 256,
    ) -> None:
        self.session_id = session_id
        self._pipeline = pipeline_actuator
        self._queue: asyncio.Queue[ControlEvent] = asyncio.Queue(maxsize=queue_max)
        self._task: Optional[asyncio.Task] = None
        self.playback_active: bool = False
        self.active_speaker_id: Optional[str] = None
        self.current_provider_response_id: Optional[str] = None
        self.barge_in_armed: bool = False
        self._dropped_events: int = 0

    @property
    def dropped_events(self) -> int:
        return self._dropped_events

    def publish_event(self, event: ControlEvent) -> bool:
        """Enqueue control event without blocking. Drops on overflow."""

        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            self._dropped_events += 1
            logger.warning(
                "control_event_dropped session=%s kind=%s dropped=%s",
                self.session_id,
                event.kind,
                self._dropped_events,
            )
            return False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name=f"control-plane-{self.session_id}")
        logger.info("control_plane_started session=%s", self.session_id)

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        logger.info("control_plane_stopped session=%s", self.session_id)

    async def _run(self) -> None:
        try:
            while True:
                event = await self._queue.get()
                await self._process_event(event)
        except asyncio.CancelledError:
            logger.debug("Control plane run loop cancelled for session=%s", self.session_id)

    async def _process_event(self, event: ControlEvent) -> None:
        """Update control state and issue actions."""

        if event.kind.startswith("provider.audio"):
            self.playback_active = True
            self.current_provider_response_id = event.provider_response_id or event.commit_id
        elif event.kind in {"provider.audio.done", "provider.control", "acs_outbound.audio"}:
            self.playback_active = False

        if event.kind == "command.outbound_gate":
            enabled = bool(event.payload.get("enabled", True))
            reason = event.payload.get("reason", "control_event")
            correlation_id = event.provider_response_id or event.commit_id
            self._pipeline.set_outbound_gate(enabled=enabled, reason=reason, correlation_id=correlation_id)

        if event.kind == "command.drop_outbound_audio":
            reason = event.payload.get("reason", "control_event")
            correlation_id = event.provider_response_id or event.commit_id
            await self._pipeline.drop_outbound_audio(reason=reason, correlation_id=correlation_id)

        if event.kind == "command.cancel_provider_response" and event.provider_response_id:
            await self._pipeline.cancel_provider_response(
                provider_response_id=event.provider_response_id,
                reason=event.payload.get("reason", "control_event"),
            )

        if event.kind == "command.flush_inbound_buffers":
            await self._pipeline.flush_inbound_buffers(
                participant_id=event.participant_id,
                keep_after_ts_ms=event.payload.get("keep_after_ts_ms"),
            )


class ControlPlaneTapHandler(Handler):
    """Lightweight tap that forwards internal events into the control plane."""

    def __init__(
        self,
        settings: HandlerSettings,
        control_plane: SessionControlPlane,
        *,
        session_id: str,
        allow_outbound_payloads: bool = False,
    ) -> None:
        super().__init__(settings)
        self.control_plane = control_plane
        self.session_id = session_id
        self.allow_outbound_payloads = allow_outbound_payloads
        self._event_types: Tuple[Type[Any], ...] = (GatewayInputEvent, ProviderOutputEvent)

    def can_handle(self, event: object) -> bool:  # type: ignore[override]
        if isinstance(event, self._event_types):
            return True
        if self.allow_outbound_payloads and isinstance(event, dict):
            return True
        return False

    async def handle(self, event: object) -> None:  # type: ignore[override]
        control_event: Optional[ControlEvent] = None

        if isinstance(event, GatewayInputEvent):
            control_event = control_event_from_gateway(event)
        elif isinstance(event, ProviderOutputEvent):
            control_event = control_event_from_provider(event)
        elif self.allow_outbound_payloads and isinstance(event, dict):
            control_event = control_event_from_acs_outbound(self.session_id, event)

        if not control_event:
            return

        self.control_plane.publish_event(control_event)


class AcsOutboundGateHandler(Handler):
    """Choke point for outbound ACS messages controlled by the control plane."""

    def __init__(
        self,
        settings: HandlerSettings,
        *,
        send_callable: Callable[[Dict[str, Any]], Awaitable[None]],
        gate_is_open: Callable[[], bool],
        control_plane: SessionControlPlane,
    ) -> None:
        super().__init__(settings)
        self._send = send_callable
        self._gate_is_open = gate_is_open
        self._control_plane = control_plane

    async def handle(self, payload: Dict[str, Any]) -> None:  # type: ignore[override]
        is_audio = self._is_audio_payload(payload)

        if is_audio and not self._gate_is_open():
            logger.info(
                "outbound_gate_closed session=%s dropping_audio=True",
                self._control_plane.session_id,
            )
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


class SessionPipelineProtocol:
    """Protocol subset used by the control plane (runtime duck typing)."""

    def set_outbound_gate(self, enabled: bool, reason: str, correlation_id: Optional[str] = None) -> None: ...

    async def drop_outbound_audio(self, reason: str, correlation_id: Optional[str] = None) -> None: ...

    async def cancel_provider_response(self, provider_response_id: str, reason: str) -> None: ...

    async def flush_inbound_buffers(self, participant_id: Optional[str], keep_after_ts_ms: Optional[int]) -> None: ...

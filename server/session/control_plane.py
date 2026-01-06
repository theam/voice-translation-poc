from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from ..gateways.base import Handler, HandlerSettings
from ..models.gateway_input_event import GatewayInputEvent
from ..models.provider_events import ProviderOutputEvent
from ..utils.time_utils import MonotonicClock

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
        timestamp_ms=MonotonicClock.now_ms(),
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
        timestamp_ms=MonotonicClock.now_ms(),
    )


class SessionControlPlane:
    """Per-session control plane consuming internal events and issuing actions."""

    def __init__(
        self,
        session_id: str,
        pipeline_actuator: "SessionPipelineProtocol",
    ) -> None:
        self.session_id = session_id
        self._pipeline = pipeline_actuator
        self.playback_active: bool = False
        self.active_speaker_id: Optional[str] = None
        self.current_provider_response_id: Optional[str] = None
        self.barge_in_armed: bool = False
        self._last_audio_sent_ms: Optional[int] = None

    async def process_gateway(self, event: GatewayInputEvent) -> None:
        control_event = control_event_from_gateway(event)
        self._log_debug_unhandled(control_event.kind)

    async def process_provider(self, event: ProviderOutputEvent) -> None:
        control_event = control_event_from_provider(event)
        kind = control_event.kind

        if kind == "provider.audio.delta":
            self.current_provider_response_id = control_event.provider_response_id or control_event.commit_id
            self._set_playback_active(True, "provider_audio_delta", control_event.provider_response_id)
            return

        if kind == "provider.audio.done":
            self._set_playback_active(False, "provider_audio_done", control_event.provider_response_id)
            return

        if kind == "provider.control":
            action = control_event.payload.get("action") if isinstance(control_event.payload, dict) else None
            if action == "stop_audio":
                self._set_playback_active(False, "provider_stop_audio", control_event.provider_response_id)
            else:
                self._log_debug_unhandled(f"{kind}:{action}")
            return

        self._log_debug_unhandled(kind)

    async def process_outbound_payload(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            self._log_debug_unhandled("acs_outbound.unknown")
            return

        if self._is_audio_payload(payload):
            self._last_audio_sent_ms = MonotonicClock.now_ms()
            self._set_playback_active(True, "acs_outbound_audio", self.current_provider_response_id)
            return

        payload_type = payload.get("type")
        if payload_type in {"control.stop_audio", "control.test.response.audio_done"}:
            self._set_playback_active(False, payload_type, payload.get("stream_id") or payload.get("commit_id"))
            return

        self._log_debug_unhandled(f"acs_outbound:{payload_type}")

    def mark_playback_inactive(self, reason: str, correlation_id: Optional[str] = None) -> None:
        self._set_playback_active(False, reason, correlation_id or self.current_provider_response_id)

    def _set_playback_active(self, active: bool, reason: str, correlation_id: Optional[str]) -> None:
        if active:
            if not self.playback_active:
                logger.info(
                    "playback_active_started session=%s reason=%s correlation_id=%s",
                    self.session_id,
                    reason,
                    correlation_id,
                )
            self.playback_active = True
            return

        if self.playback_active:
            logger.info(
                "playback_active_stopped session=%s reason=%s correlation_id=%s",
                self.session_id,
                reason,
                correlation_id,
            )
        self.playback_active = False

    def _log_debug_unhandled(self, kind: str) -> None:
        logger.debug("control_plane_ignored session=%s kind=%s", self.session_id, kind)

    @staticmethod
    def _is_audio_payload(payload: Dict[str, Any]) -> bool:
        kind = payload.get("kind") or payload.get("type")
        if kind in {"audioData", "audio.data"}:
            return True
        audio_data = payload.get("audioData") or payload.get("audio_data")
        return isinstance(audio_data, dict) and "data" in audio_data


class ControlPlaneBusHandler(Handler):
    """EventBus handler that forwards envelopes to the session control plane."""

    def __init__(
        self,
        settings: HandlerSettings,
        *,
        control_plane: SessionControlPlane,
        source: str,
    ) -> None:
        super().__init__(settings)
        self._control_plane = control_plane
        self._source = source

    async def handle(self, envelope: object) -> None:  # type: ignore[override]
        if isinstance(envelope, GatewayInputEvent):
            await self._control_plane.process_gateway(envelope)
            return

        if isinstance(envelope, ProviderOutputEvent):
            await self._control_plane.process_provider(envelope)
            return

        if isinstance(envelope, dict):
            await self._control_plane.process_outbound_payload(envelope)
            return

        logger.debug(
            "control_plane_unknown_envelope session=%s source=%s type=%s",
            self._control_plane.session_id,
            self._source,
            type(envelope),
        )


class AcsOutboundGateHandler(Handler):
    """Choke point for outbound ACS messages controlled by the control plane."""

    def __init__(
        self,
        settings: HandlerSettings,
        *,
        send_callable: Callable[[Dict[str, Any]], Awaitable[None]],
        gate_is_open: Callable[[], bool],
        control_plane: SessionControlPlane,
        on_audio_dropped: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(settings)
        self._send = send_callable
        self._gate_is_open = gate_is_open
        self._control_plane = control_plane
        self._on_audio_dropped = on_audio_dropped

    async def handle(self, payload: Dict[str, Any]) -> None:  # type: ignore[override]
        is_audio = self._is_audio_payload(payload)

        if is_audio and not self._gate_is_open():
            logger.info(
                "outbound_gate_closed session=%s dropping_audio=True",
                self._control_plane.session_id,
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


class SessionPipelineProtocol:
    """Protocol subset used by the control plane (runtime duck typing)."""

    def set_outbound_gate(self, enabled: bool, reason: str, correlation_id: Optional[str] = None) -> None: ...

    async def drop_outbound_audio(self, reason: str, correlation_id: Optional[str] = None) -> None: ...

    async def cancel_provider_response(self, provider_response_id: str, reason: str) -> None: ...

    async def flush_inbound_buffers(self, participant_id: Optional[str], keep_after_ts_ms: Optional[int]) -> None: ...

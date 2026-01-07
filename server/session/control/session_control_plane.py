from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ...models.gateway_input_event import GatewayInputEvent
from ...models.provider_events import ProviderOutputEvent
from ...utils.time_utils import MonotonicClock
from .control_event import ControlEvent

logger = logging.getLogger(__name__)


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
        control_event = ControlEvent.from_gateway(event)
        self._log_debug_unhandled(control_event.kind)

    async def process_provider(self, event: ProviderOutputEvent) -> None:
        control_event = ControlEvent.from_provider(event)
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


class SessionPipelineProtocol:
    """Protocol subset used by the control plane (runtime duck typing)."""

    def set_outbound_gate(self, enabled: bool, reason: str, correlation_id: Optional[str] = None) -> None: ...

    async def drop_outbound_audio(self, reason: str, correlation_id: Optional[str] = None) -> None: ...

    async def cancel_provider_response(self, provider_response_id: str, reason: str) -> None: ...

    async def flush_inbound_buffers(self, participant_id: Optional[str], keep_after_ts_ms: Optional[int]) -> None: ...


__all__ = ["SessionControlPlane", "SessionPipelineProtocol"]

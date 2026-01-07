from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ...models.gateway_input_event import GatewayInputEvent
from ...models.provider_events import ProviderInputEvent, ProviderOutputEvent
from ...utils.time_utils import MonotonicClock
from .control_event import ControlEvent
from .input_state import InputState, InputStatus
from .playback_state import PlaybackState, PlaybackStatus

logger = logging.getLogger(__name__)


class SessionControlPlane:
    """Per-session control plane consuming internal events and issuing actions."""

    PLAYBACK_IDLE_TIMEOUT_MS = 500
    INPUT_SILENCE_TIMEOUT_MS = 350

    def __init__(
        self,
        session_id: str,
        pipeline_actuator: "SessionPipelineProtocol",
    ) -> None:
        self.session_id = session_id
        self._pipeline = pipeline_actuator
        self.playback = PlaybackState()
        self.input_state = InputState()
        self.active_speaker_id: Optional[str] = None
        self.current_provider_response_id: Optional[str] = None
        self.barge_in_armed: bool = False

    async def process_gateway(self, event: GatewayInputEvent) -> None:
        now_ms = MonotonicClock.now_ms()
        self._check_idle_timeout(now_ms)
        self._check_input_silence_timeout(now_ms)
        control_event = ControlEvent.from_gateway(event)
        self._maybe_update_input_state(control_event, now_ms)
        self._log_debug_unhandled(control_event.kind)

    async def process_provider(self, event: ProviderOutputEvent) -> None:
        now_ms = MonotonicClock.now_ms()
        self._check_idle_timeout(now_ms)
        control_event = ControlEvent.from_provider(event)
        kind = control_event.kind

        if kind == "provider.audio.delta":
            self.current_provider_response_id = control_event.provider_response_id or control_event.commit_id
            return

        if kind == "provider.audio.done":
            self._transition_playback(
                lambda: self.playback.on_provider_done(control_event.provider_response_id),
                reason="provider_audio_done",
                response_id=control_event.provider_response_id,
            )
            return

        if kind == "provider.control":
            action = control_event.payload.get("action") if isinstance(control_event.payload, dict) else None
            if action == "stop_audio":
                self._transition_playback(
                    lambda: self.playback.on_explicit_playback_end(
                        reason="provider_stop_audio",
                        response_id=control_event.provider_response_id,
                    ),
                    reason="provider_stop_audio",
                    response_id=control_event.provider_response_id,
                )
            else:
                self._log_debug_unhandled(f"{kind}:{action}")
            return

        self._log_debug_unhandled(kind)

    async def process_provider_input(self, event: ProviderInputEvent) -> None:
        now_ms = MonotonicClock.now_ms()
        self._check_idle_timeout(now_ms)
        self._log_debug_unhandled("provider_input")

    async def process_outbound_payload(self, payload: Dict[str, Any]) -> None:
        now_ms = MonotonicClock.now_ms()
        self._check_idle_timeout(now_ms)
        if not isinstance(payload, dict):
            self._log_debug_unhandled("acs_outbound.unknown")
            return

        if self._is_audio_payload(payload):
            self._transition_playback(
                lambda: self.playback.on_outbound_audio_sent(
                    now_ms,
                    response_id=self.current_provider_response_id,
                ),
                reason="acs_outbound_audio",
                response_id=self.current_provider_response_id,
            )
            return

        payload_type = payload.get("type")
        if payload_type in {"control.stop_audio", "control.test.response.audio_done"}:
            response_id = payload.get("stream_id") or payload.get("commit_id")
            self._transition_playback(
                lambda: self.playback.on_explicit_playback_end(
                    reason=payload_type,
                    response_id=response_id,
                ),
                reason=payload_type,
                response_id=response_id,
            )
            return

        self._log_debug_unhandled(f"acs_outbound:{payload_type}")

    def mark_playback_inactive(self, reason: str, correlation_id: Optional[str] = None) -> None:
        response_id = correlation_id or self.current_provider_response_id
        self._transition_playback(
            lambda: self.playback.on_explicit_playback_end(reason=reason, response_id=response_id),
            reason=reason,
            response_id=response_id,
        )

    def on_gate_closed(self) -> None:
        self._transition_playback(
            self.playback.on_gate_closed,
            reason="gate_closed",
            response_id=self.current_provider_response_id,
        )

    def on_gate_opened(self) -> None:
        self._transition_playback(
            self.playback.on_gate_opened,
            reason="gate_opened",
            response_id=self.current_provider_response_id,
        )

    def _transition_playback(self, updater, *, reason: str, response_id: Optional[str]) -> None:
        old_status = self.playback.status
        updater()
        new_status = self.playback.status
        if old_status != new_status:
            self._log_playback_transition(old_status, new_status, reason, response_id)

    def _check_idle_timeout(self, now_ms: int) -> None:
        old_status = self.playback.status
        timed_out = self.playback.maybe_timeout_idle(now_ms, self.PLAYBACK_IDLE_TIMEOUT_MS)
        if timed_out:
            logger.info(
                "playback_idle_timeout session=%s last_audio_sent_ms=%s response_id=%s",
                self.session_id,
                self.playback.last_audio_sent_ms,
                self.playback.current_response_id,
            )
            if old_status != self.playback.status:
                self._log_playback_transition(old_status, self.playback.status, "idle_timeout", self.playback.current_response_id)

    def _check_input_silence_timeout(self, now_ms: int) -> None:
        old_status = self.input_state.status
        timed_out = self.input_state.maybe_timeout_silence(now_ms, self.INPUT_SILENCE_TIMEOUT_MS)
        if timed_out and old_status != self.input_state.status:
            logger.info(
                "input_state_changed session=%s from=%s to=%s reason=timeout last_voice_ms=%s timeout_ms=%s",
                self.session_id,
                old_status,
                self.input_state.status,
                self.input_state.last_voice_ms,
                self.INPUT_SILENCE_TIMEOUT_MS,
            )

    def _maybe_update_input_state(self, event: ControlEvent, now_ms: int) -> None:
        old_status = self.input_state.status
        if self._detect_voice_signal(event.payload):
            self.input_state.on_voice_detected(now_ms)
        if old_status != self.input_state.status:
            logger.info(
                "input_state_changed session=%s from=%s to=%s reason=voice_detected participant_id=%s",
                self.session_id,
                old_status,
                self.input_state.status,
                event.participant_id,
            )

    def _log_playback_transition(
        self,
        old_status: PlaybackStatus,
        new_status: PlaybackStatus,
        reason: str,
        response_id: Optional[str],
    ) -> None:
        logger.info(
            "playback_status_changed session=%s from=%s to=%s reason=%s response_id=%s",
            self.session_id,
            old_status,
            new_status,
            reason,
            response_id,
        )

    def _log_debug_unhandled(self, kind: str) -> None:
        logger.debug("control_plane_ignored session=%s kind=%s", self.session_id, kind)

    @staticmethod
    def _is_audio_payload(payload: Dict[str, Any]) -> bool:
        kind = payload.get("kind") or payload.get("type")
        if kind in {"audioData", "audio.data"}:
            return True
        audio_data = payload.get("audioData") or payload.get("audio_data")
        return isinstance(audio_data, dict) and "data" in audio_data

    @staticmethod
    def _detect_voice_signal(payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        audio_data = payload.get("audiodata") or payload.get("audioData") or {}
        if isinstance(audio_data, dict):
            speech_flag = audio_data.get("speech")
            if isinstance(speech_flag, bool):
                return speech_flag
            vad_flag = audio_data.get("vad")
            if isinstance(vad_flag, bool):
                return vad_flag
            is_silent = audio_data.get("issilent")
            if isinstance(is_silent, bool):
                return not is_silent
        return False


class SessionPipelineProtocol:
    """Protocol subset used by the control plane (runtime duck typing)."""

    def set_outbound_gate(self, enabled: bool, reason: str, correlation_id: Optional[str] = None) -> None: ...

    async def drop_outbound_audio(self, reason: str, correlation_id: Optional[str] = None) -> None: ...

    async def cancel_provider_response(self, provider_response_id: str, reason: str) -> None: ...

    async def flush_inbound_buffers(self, participant_id: Optional[str], keep_after_ts_ms: Optional[int]) -> None: ...


__all__ = ["SessionControlPlane", "SessionPipelineProtocol"]

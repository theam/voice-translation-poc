import pytest

from server.gateways.base import HandlerSettings
from server.models.provider_events import ProviderOutputEvent
from server.gateways.acs.outbound_gate_handler import AcsOutboundGateHandler
from server.models.gateway_input_event import GatewayInputEvent, Trace
from server.session.control import PlaybackStatus, SessionControlPlane
from server.session.control.input_state import InputState, InputStatus
from server.session.control.playback_state import PlaybackState


class _StubActuator:
    def set_outbound_gate(self, enabled: bool, reason: str, correlation_id=None):
        return None

    async def drop_outbound_audio(self, reason: str, correlation_id=None):
        return None

    async def cancel_provider_response(self, provider_response_id: str, reason: str):
        return None

    async def flush_inbound_buffers(self, participant_id=None, keep_after_ts_ms=None):
        return None


def _provider_event(event_type: str, payload=None, provider_response_id: str | None = None):
    return ProviderOutputEvent(
        commit_id="c1",
        session_id="session-1",
        participant_id="p1",
        event_type=event_type,
        payload=payload or {},
        provider="mock",
        stream_id="s1",
        provider_response_id=provider_response_id or "resp-1",
    )


def _gateway_event(payload: dict) -> GatewayInputEvent:
    trace = Trace(sequence=1, ingress_ws_id="ingress", received_at_utc="now", call_correlation_id=None)
    return GatewayInputEvent(
        event_id="e1",
        source="acs",
        content_type="application/json",
        session_id="session-1",
        received_at_utc="now",
        payload=payload,
        trace=trace,
    )


@pytest.mark.asyncio
async def test_playback_state_transitions_on_provider_audio_events():
    control_plane = SessionControlPlane("session-1", _StubActuator())

    await control_plane.process_outbound_payload({"kind": "audioData", "audioData": {"data": "abc"}})
    assert control_plane.playback.status == PlaybackStatus.PLAYING

    await control_plane.process_provider(_provider_event("audio.done"))
    assert control_plane.playback.status == PlaybackStatus.DRAINING


@pytest.mark.asyncio
async def test_outbound_gate_drops_audio_and_marks_inactive():
    sent = []
    gate_open = False

    async def _send(payload):
        sent.append(payload)

    control_plane = SessionControlPlane("session-1", _StubActuator())
    await control_plane.process_outbound_payload({"kind": "audioData", "audioData": {"data": "abc"}})
    assert control_plane.playback.is_active is True

    handler = AcsOutboundGateHandler(
        HandlerSettings(name="gate", queue_max=10, overflow_policy="DROP_OLDEST"),
        send_callable=_send,
        gate_is_open=lambda: gate_open,
        session_id="session-1",
        on_audio_dropped=control_plane.mark_playback_inactive,
    )

    payload = {"kind": "audioData", "audioData": {"data": "abc"}}
    await handler.handle(payload)
    assert sent == []
    assert control_plane.playback.status == PlaybackStatus.IDLE

    gate_open = True
    await handler.handle(payload)
    assert sent == [payload]


def test_playback_state_transitions_and_timeout():
    state = PlaybackState()
    assert state.status == PlaybackStatus.IDLE

    state.on_outbound_audio_sent(1, response_id="r1")
    assert state.status == PlaybackStatus.PLAYING

    state.on_provider_done(response_id="r1")
    assert state.status == PlaybackStatus.DRAINING

    timed_out = state.maybe_timeout_idle(1000, idle_timeout_ms=500)
    assert timed_out is True
    assert state.status == PlaybackStatus.IDLE


def test_input_state_transitions_and_timeout():
    state = InputState()
    assert state.status == InputStatus.SILENCE

    state.on_voice_detected(100)
    assert state.status == InputStatus.SPEAKING

    timed_out = state.maybe_timeout_silence(1000, silence_timeout_ms=350)
    assert timed_out is True
    assert state.status == InputStatus.SILENCE


@pytest.mark.asyncio
async def test_control_plane_updates_input_state_on_voice_signal():
    control_plane = SessionControlPlane("session-1", _StubActuator())
    payload = {"kind": "AudioData", "audioData": {"participantRawId": "p1", "speech": True}}
    await control_plane.process_gateway(_gateway_event(payload))
    assert control_plane.input_state.is_speaking is True

import pytest

from server.gateways.base import HandlerSettings
from server.models.provider_events import ProviderOutputEvent
from server.session.control_plane import AcsOutboundGateHandler, SessionControlPlane


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


@pytest.mark.asyncio
async def test_playback_state_transitions_on_provider_audio_events():
    control_plane = SessionControlPlane("session-1", _StubActuator())

    await control_plane.process_provider(_provider_event("audio.delta"))
    assert control_plane.playback_active is True

    await control_plane.process_provider(_provider_event("audio.done"))
    assert control_plane.playback_active is False


@pytest.mark.asyncio
async def test_outbound_gate_drops_audio_and_marks_inactive():
    sent = []
    gate_open = False

    async def _send(payload):
        sent.append(payload)

    control_plane = SessionControlPlane("session-1", _StubActuator())
    await control_plane.process_outbound_payload({"kind": "audioData", "audioData": {"data": "abc"}})
    assert control_plane.playback_active is True

    handler = AcsOutboundGateHandler(
        HandlerSettings(name="gate", queue_max=10, overflow_policy="DROP_OLDEST"),
        send_callable=_send,
        gate_is_open=lambda: gate_open,
        control_plane=control_plane,
        on_audio_dropped=control_plane.mark_playback_inactive,
    )

    payload = {"kind": "audioData", "audioData": {"data": "abc"}}
    await handler.handle(payload)
    assert sent == []
    assert control_plane.playback_active is False

    gate_open = True
    await handler.handle(payload)
    assert sent == [payload]

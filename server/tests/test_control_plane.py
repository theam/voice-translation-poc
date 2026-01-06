import asyncio
import pytest

from server.gateways.base import HandlerSettings
from server.models.gateway_input_event import GatewayInputEvent, Trace
from server.session.control_plane import (
    AcsOutboundGateHandler,
    ControlPlaneTapHandler,
    SessionControlPlane,
)


class _StubActuator:
    def set_outbound_gate(self, enabled: bool, reason: str, correlation_id=None):
        return None

    async def drop_outbound_audio(self, reason: str, correlation_id=None):
        return None

    async def cancel_provider_response(self, provider_response_id: str, reason: str):
        return None

    async def flush_inbound_buffers(self, participant_id=None, keep_after_ts_ms=None):
        return None


def _gateway_event(seq: int = 1) -> GatewayInputEvent:
    trace = Trace(sequence=seq, ingress_ws_id="ingress", received_at_utc="now", call_correlation_id=None)
    return GatewayInputEvent(
        event_id=f"e{seq}",
        source="acs",
        content_type="application/json",
        session_id="session-1",
        received_at_utc="now",
        payload={"kind": "AudioData", "audioData": {"participantRawId": "p1", "data": "abc"}},
        trace=trace,
    )


@pytest.mark.asyncio
async def test_control_plane_tap_drops_on_full_queue():
    control_plane = SessionControlPlane("session-1", _StubActuator(), queue_max=1)
    handler = ControlPlaneTapHandler(
        HandlerSettings(name="tap", queue_max=1, overflow_policy="DROP_NEWEST"),
        control_plane=control_plane,
        session_id="session-1",
    )

    await handler.handle(_gateway_event(1))
    await asyncio.wait_for(handler.handle(_gateway_event(2)), timeout=0.1)

    assert control_plane.dropped_events == 1
    assert control_plane._queue.qsize() == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_outbound_gate_drops_audio_when_closed():
    sent = []
    gate_open = False

    async def _send(payload):
        sent.append(payload)

    control_plane = SessionControlPlane("session-1", _StubActuator(), queue_max=4)
    handler = AcsOutboundGateHandler(
        HandlerSettings(name="gate", queue_max=10, overflow_policy="DROP_OLDEST"),
        send_callable=_send,
        gate_is_open=lambda: gate_open,
        control_plane=control_plane,
    )

    payload = {"kind": "audioData", "audioData": {"data": "abc"}}
    await handler.handle(payload)
    assert sent == []

    gate_open = True
    await handler.handle(payload)
    assert sent == [payload]

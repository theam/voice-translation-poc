import pytest

from production.capture.collector import CollectedEvent
from production.capture.conversation_manager import ConversationManager
from production.utils.time_utils import Clock


def test_start_turn_uses_explicit_start_time_and_sets_previous_end():
    clock = Clock(time_fn=lambda: 0.0)
    manager = ConversationManager(clock=clock, scenario_started_at_ms=0)

    first = manager.start_turn("turn-1", {"type": "play_audio"}, turn_start_ms=100)
    second = manager.start_turn("turn-2", {"type": "play_audio"}, turn_start_ms=500)

    assert first.turn_start_ms == 100
    assert first.turn_end_ms == 500
    assert second.turn_start_ms == 500


def test_resolve_turn_id_prefers_event_timestamp_over_wall_clock():
    current_time_ms = 10_000
    clock = Clock(time_fn=lambda: current_time_ms / 1000.0)
    manager = ConversationManager(clock=clock, scenario_started_at_ms=0)

    manager.start_turn("turn-1", {"type": "play_audio"}, turn_start_ms=0)
    manager.start_turn("turn-2", {"type": "play_audio"}, turn_start_ms=2000)

    early_event = CollectedEvent(event_type="translated_audio", timestamp_ms=1500, participant_id="p1")
    late_event = CollectedEvent(event_type="translated_audio", timestamp_ms=2500, participant_id="p1")

    manager.register_incoming(early_event)
    manager.register_incoming(late_event)

    assert manager.get_turn("turn-1").inbound_events == [early_event]
    assert manager.get_turn("turn-2").inbound_events == [late_event]

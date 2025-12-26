import pytest

from production.acs_emulator.media_engine import FRAME_DURATION_MS
from production.capture.arrival_queue_assembler import ArrivalQueueAssembler
from production.capture.collector import EventCollector
from production.capture.conversation_manager import ConversationManager
from production.capture.conversation_tape import ConversationTape
from production.scenario_engine.engine import ScenarioEngine
from production.scenario_engine.models import Participant
from production.utils.config import FrameworkConfig
from production.utils.time_utils import Clock


class _FakeWebSocket:
    def __init__(self, messages=None):
        self.sent = []
        self._messages = messages or []

    async def send_json(self, payload):
        self.sent.append(payload)

    async def iter_messages(self):
        for message in self._messages:
            yield message


class _FakeAdapter:
    def __init__(self, participant_id: str = "turn-1"):
        self.participant_id = participant_id

    def build_audio_message(self, participant_id, pcm_bytes, timestamp_ms, silent=False):
        return {
            "participant_id": participant_id,
            "timestamp_ms": timestamp_ms,
            "silent": silent,
            "payload": pcm_bytes,
        }

    def decode_inbound(self, message):
        return _FakeProtocolEvent(self.participant_id)


class _FakeProtocolEvent:
    def __init__(self, participant_id: str):
        self.event_type = "translated_audio"
        self.audio_payload = b"\x00" * 4
        self.participant_id = participant_id
        self.raw = {}
        self.text = None
        self.source_language = None
        self.target_language = None
        self.arrival_ms = None


class _TapeStub:
    def __init__(self):
        self.added = []

    def add_pcm(self, start_ms, pcm_bytes):
        self.added.append((start_ms, pcm_bytes))


@pytest.mark.asyncio
async def test_stream_silence_advances_media_clock():
    config = FrameworkConfig(time_acceleration=1_000.0)
    engine = ScenarioEngine(config)
    engine.clock = Clock(acceleration=1_000.0, time_fn=lambda: 0.0)

    conversation_manager = ConversationManager(clock=engine.clock, scenario_started_at_ms=0)
    participants = [Participant(name="speaker-1", source_language="en", target_language="es")]
    ws = _FakeWebSocket()
    adapter = _FakeAdapter()
    tape = ConversationTape(sample_rate=16000)

    current_time = await engine._stream_silence_until(
        ws,
        adapter,
        participants,
        0,
        FRAME_DURATION_MS * 2,
        16000,
        1,
        tape,
        conversation_manager,
    )

    assert current_time == FRAME_DURATION_MS * 2
    assert conversation_manager.latest_outgoing_media_ms >= FRAME_DURATION_MS
    # Two frames of silence for a single participant
    assert len(ws.sent) == 2


@pytest.mark.asyncio
async def test_listen_schedules_inbound_from_arrival_queue():
    config = FrameworkConfig()
    engine = ScenarioEngine(config)
    engine.clock = Clock(time_fn=lambda: 0.0)

    conversation_manager = ConversationManager(clock=engine.clock, scenario_started_at_ms=0)
    conversation_manager.start_turn("turn-1", {"type": "play_audio"}, turn_start_ms=0)

    collector = EventCollector()
    raw_messages = []
    inbound = ArrivalQueueAssembler(sample_rate=16000, channels=1)
    adapter = _FakeAdapter(participant_id="turn-1")
    ws = _FakeWebSocket(messages=[{"type": "translated_audio"}])
    tape = _TapeStub()

    await engine._listen(
        ws,
        adapter,
        collector,
        conversation_manager,
        raw_messages,
        tape,
        started_at_ms=0,
        inbound_assembler=inbound,
    )

    assert tape.added[0][0] >= 0.0
    assert collector.events[0].timestamp_ms == tape.added[0][0]

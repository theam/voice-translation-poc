import asyncio
import base64
import pytest

from server.audio import AudioFormat, PcmConverter, UnsupportedAudioFormatError
from server.core.event_bus import EventBus, HandlerConfig
from server.core.queues import OverflowPolicy
from server.gateways.provider.audio import (
    AcsAudioPublisher,
    AcsFormatResolver,
    AudioDeltaDecoder,
    AudioDecodingError,
    AudioTranscoder,
    AudioTranscodingError,
    PacedPlayoutEngine,
    PlayoutConfig,
    PlayoutState,
    PlayoutStore,
    ProviderFormatResolver,
    StreamKeyBuilder,
)
import server.gateways.provider.audio.playout_engine as playout_engine_module
from server.models.provider_events import ProviderOutputEvent


def _provider_event(**kwargs):
    return ProviderOutputEvent(
        commit_id=kwargs.get("commit_id", "c1"),
        session_id=kwargs.get("session_id", "s1"),
        participant_id=kwargs.get("participant_id", "p1"),
        event_type=kwargs.get("event_type", "audio.delta"),
        payload=kwargs.get("payload", {}),
        provider=kwargs.get("provider", "mock"),
        stream_id=kwargs.get("stream_id", "stream-1"),
    )


def test_stream_key_builder_builds_expected_key():
    builder = StreamKeyBuilder()
    event = _provider_event(participant_id=None, stream_id=None, commit_id="cX")
    assert builder.build(event) == "s1:unknown:cX"


def test_acs_format_resolver_defaults_and_sanitizes():
    resolver = AcsFormatResolver({})
    fmt = resolver.get_target_format()
    frame_bytes = resolver.get_frame_bytes(fmt)
    assert fmt.sample_rate_hz == 16000
    assert fmt.channels == 1
    assert fmt.sample_format == "pcm16"
    assert frame_bytes == 640  # 20ms of 16k mono pcm16


def test_acs_format_resolver_uses_metadata_and_aligns():
    session_metadata = {"acs_audio": {"format": {"sample_rate_hz": 8000, "channels": 1, "encoding": "pcm16", "frame_bytes": 481}}}
    resolver = AcsFormatResolver(session_metadata)
    fmt = resolver.get_target_format()
    frame_bytes = resolver.get_frame_bytes(fmt)
    assert fmt.sample_rate_hz == 8000
    assert frame_bytes % fmt.bytes_per_frame() == 0


def test_provider_format_resolver_falls_back_to_target():
    target = AudioFormat(sample_rate_hz=16000, channels=1, sample_format="pcm16")
    resolver = ProviderFormatResolver()
    fmt = resolver.resolve(_provider_event(), target)
    assert fmt == target


def test_audio_delta_decoder_handles_invalid_base64():
    decoder = AudioDeltaDecoder()
    good = base64.b64encode(b"ab").decode("ascii")
    assert decoder.decode(good) == b"ab"
    with pytest.raises(AudioDecodingError):
        decoder.decode("!!invalid!!")


def test_audio_transcoder_passes_through_and_wraps_errors():
    converter = PcmConverter()
    transcoder = AudioTranscoder(converter)
    fmt = AudioFormat(sample_rate_hz=16000, channels=1, sample_format="pcm16")
    audio = b"abcd"
    assert transcoder.transcode(audio, fmt, fmt) == audio

    class FailingConverter(PcmConverter):
        def convert(self, pcm, src, dst):
            raise UnsupportedAudioFormatError("bad")

    failing = AudioTranscoder(FailingConverter())
    with pytest.raises(AudioTranscodingError):
        failing.transcode(audio, fmt, AudioFormat(8000, 1, "pcm16"))


def test_playout_store_lifecycle():
    store = PlayoutStore()
    key = "k1"
    fmt = AudioFormat(sample_rate_hz=16000, channels=1, sample_format="pcm16")
    state = store.get_or_create(key, fmt, 640)
    assert store.get(key) is state
    store.remove(key)
    assert store.get(key) is None


@pytest.mark.asyncio
async def test_acs_audio_publisher_shapes_payload():
    bus = EventBus("test_bus")
    captured = []
    async def _capture(payload):
        captured.append(payload)
    await bus.register_handler(
        HandlerConfig(name="capture", queue_max=10, overflow_policy=OverflowPolicy.DROP_OLDEST, concurrency=1),
        _capture,
    )
    publisher = AcsAudioPublisher(bus)
    event = _provider_event()
    await publisher.publish_audio_chunk(b"ab")
    await publisher.publish_audio_done(event, reason="completed", error=None)
    await asyncio.sleep(0.05)
    assert captured[0]["kind"] == "audioData"
    assert base64.b64decode(captured[0]["audioData"]["data"]) == b"ab"
    assert captured[1]["type"] == "audio.done"
    assert captured[1]["reason"] == "completed"
    await bus.shutdown()


class _DummyPublisher:
    def __init__(self):
        self.chunks = []

    async def publish_audio_chunk(self, audio_bytes: bytes) -> None:
        self.chunks.append(audio_bytes)


@pytest.mark.asyncio
async def test_paced_playout_engine_publishes_with_pacing(monkeypatch):
    publisher = _DummyPublisher()
    engine = PacedPlayoutEngine(publisher, PlayoutConfig(frame_ms=20, warmup_frames=0))
    state = PlayoutState(
        buffer=bytearray(b"a" * 8),
        frame_bytes=4,
        fmt=AudioFormat(sample_rate_hz=16000, channels=1, sample_format="pcm16"),
    )

    sleeps = []

    async def fake_sleep(duration):
        sleeps.append(duration)

    monkeypatch.setattr(playout_engine_module.asyncio, "sleep", fake_sleep)
    times = [0.0, 0.0, 0.01, 0.01, 0.02, 0.02]
    monkeypatch.setattr(playout_engine_module.time, "monotonic", lambda: times.pop(0) if times else 0.06)

    engine.ensure_task("k1", state)
    await engine.mark_done(state)
    await engine.wait(state)

    assert len(publisher.chunks) == 2
    assert all(len(c) == 4 for c in publisher.chunks)
    assert any(s > 0 for s in sleeps)


@pytest.mark.asyncio
async def test_paced_playout_engine_respects_warmup(monkeypatch):
    publisher = _DummyPublisher()
    engine = PacedPlayoutEngine(publisher, PlayoutConfig(frame_ms=20, warmup_frames=2))
    state = PlayoutState(
        buffer=bytearray(b"a" * 4),
        frame_bytes=4,
        fmt=AudioFormat(sample_rate_hz=16000, channels=1, sample_format="pcm16"),
    )

    async def fake_sleep(_):
        return None

    monkeypatch.setattr(playout_engine_module.asyncio, "sleep", fake_sleep)
    times = [0.0, 0.0, 0.02, 0.02, 0.04, 0.04, 0.06, 0.06]
    monkeypatch.setattr(playout_engine_module.time, "monotonic", lambda: times.pop(0) if times else 0.08)

    engine.ensure_task("k2", state)
    await asyncio.sleep(0.05)
    assert not publisher.chunks  # not enough buffered yet

    state.buffer.extend(b"b" * 4)
    state.data_ready.set()
    await engine.mark_done(state)
    await engine.wait(state)

    assert len(publisher.chunks) == 2

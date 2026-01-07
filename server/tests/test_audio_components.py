import asyncio
import base64
import json
import numpy as np
import pytest

from server.audio import AudioFormat, Base64AudioCodec, PcmConverter, StreamingPcmResampler, UnsupportedAudioFormatError
from server.core.event_bus import EventBus, HandlerConfig
from server.core.queues import OverflowPolicy
from server.gateways.provider.audio_delta_handler import AudioDeltaHandler
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
from server.models.provider_events import ProviderInputEvent, ProviderOutputEvent
from server.providers.capabilities import ProviderAudioCapabilities
from server.providers.voice_live.outbound_handler import VoiceLiveOutboundHandler


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


class RecordingConverter(PcmConverter):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.last_output = None

    def convert(self, pcm, src, dst, resampler=None, *, streaming: bool = False):
        self.calls.append((src, dst, len(pcm)))
        self.last_output = super().convert(pcm, src, dst, resampler=resampler, streaming=streaming)
        return self.last_output


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


def test_provider_format_resolver_prefers_provider_defaults():
    target = AudioFormat(sample_rate_hz=16000, channels=1, sample_format="pcm16")
    provider_fmt = AudioFormat(sample_rate_hz=24000, channels=1, sample_format="pcm16")
    resolver = ProviderFormatResolver(provider_output_format=provider_fmt)
    fmt = resolver.resolve(_provider_event(), target)
    assert fmt.sample_rate_hz == provider_fmt.sample_rate_hz
    assert fmt.channels == provider_fmt.channels


def test_streaming_resampler_preserves_continuity():
    src_rate = 24000
    dst_rate = 16000
    channels = 1
    chunk_samples = int(src_rate * 0.02)  # 20ms

    def _sine_chunk(start_sample: int) -> bytes:
        t = (np.arange(chunk_samples) + start_sample) / src_rate
        wave = 12000 * np.sin(2 * np.pi * 440 * t)
        return wave.astype("<i2").tobytes()

    resampler = StreamingPcmResampler(src_rate, dst_rate, channels)
    out1 = resampler.process(_sine_chunk(0))
    out2 = resampler.process(_sine_chunk(chunk_samples))

    arr1 = np.frombuffer(out1, dtype="<i2")
    arr2 = np.frombuffer(out2, dtype="<i2")
    assert arr1.size > 0 and arr2.size > 0
    boundary_diff = abs(int(arr1[-1]) - int(arr2[0]))
    assert boundary_diff < 1500


def test_streaming_resampler_matches_full_buffer_on_uneven_deltas():
    src_fmt = AudioFormat(sample_rate_hz=24000, channels=1, sample_format="pcm16")
    dst_fmt = AudioFormat(sample_rate_hz=16000, channels=1, sample_format="pcm16")

    duration_seconds = 0.1
    samples = int(src_fmt.sample_rate_hz * duration_seconds)
    t = np.arange(samples) / src_fmt.sample_rate_hz
    sine = (12000 * np.sin(2 * np.pi * 330 * t)).astype("<i2").tobytes()

    chunk_sizes = [1500, 1700]
    deltas = []
    cursor = 0
    for size in chunk_sizes:
        deltas.append(sine[cursor:cursor + size])
        cursor += size
    deltas.append(sine[cursor:])

    converter = PcmConverter()
    resampler = StreamingPcmResampler(src_fmt.sample_rate_hz, dst_fmt.sample_rate_hz, dst_fmt.channels)

    streaming_parts = [
        converter.convert(delta, src_fmt, dst_fmt, resampler=resampler, streaming=True) for delta in deltas
    ]
    streaming_parts.append(resampler.flush())
    streaming_out = b"".join(streaming_parts)

    full_out = converter.convert(sine, src_fmt, dst_fmt)

    assert len(streaming_out) == len(full_out)
    assert streaming_out == full_out


@pytest.mark.asyncio
async def test_audio_delta_handler_resamples_from_provider_format():
    session_metadata = {"acs_audio": {"format": {"sample_rate_hz": 16000, "channels": 1, "encoding": "pcm16"}}}
    capabilities = ProviderAudioCapabilities(
        provider_input_format=AudioFormat(sample_rate_hz=24000, channels=1, sample_format="pcm16"),
        provider_output_format=AudioFormat(sample_rate_hz=24000, channels=1, sample_format="pcm16"),
    )

    class _StubPublisher:
        def __init__(self):
            self.chunks = []

        async def publish_audio_chunk(self, audio_bytes: bytes) -> None:
            self.chunks.append(audio_bytes)

        async def publish_audio_done(self, *args, **kwargs) -> None:
            return None

    class _NoopPlayoutEngine:
        def __init__(self):
            self.keys = []

        def ensure_task(self, key, state):
            self.keys.append(key)

        async def cancel(self, *args, **kwargs):
            return None

        async def mark_done(self, *args, **kwargs):
            return None

    converter = RecordingConverter()
    handler = AudioDeltaHandler(
        acs_outbound_bus=EventBus("test_resample"),
        session_metadata=session_metadata,
        provider_capabilities=capabilities,
        transcoder=AudioTranscoder(converter),
        publisher=_StubPublisher(),
        playout_engine=_NoopPlayoutEngine(),
    )

    audio_bytes = b"\x00\x01" * 480  # 20ms at 24k mono -> 960 bytes
    event = _provider_event(
        payload={"audio_b64": Base64AudioCodec.encode(audio_bytes), "seq": 1, "format": {}},
        provider="voice_live",
        stream_id="stream-test",
    )

    await handler.handle(event)
    buffer_key = handler.stream_key_builder.build(event)
    state = handler.store.get(buffer_key)
    assert converter.calls  # conversion was invoked
    assert state is not None
    assert len(state.buffer) == len(converter.last_output)
    assert len(converter.last_output) < len(audio_bytes)
    await handler.acs_outbound_bus.shutdown()


@pytest.mark.asyncio
async def test_streaming_resampler_handles_multiple_deltas_without_tail_padding():
    session_metadata = {"acs_audio": {"format": {"sample_rate_hz": 16000, "channels": 1, "encoding": "pcm16"}}}
    capabilities = ProviderAudioCapabilities(
        provider_input_format=AudioFormat(sample_rate_hz=24000, channels=1, sample_format="pcm16"),
        provider_output_format=AudioFormat(sample_rate_hz=24000, channels=1, sample_format="pcm16"),
    )

    class _StubPublisher:
        def __init__(self):
            self.chunks = []

        async def publish_audio_chunk(self, audio_bytes: bytes) -> None:
            self.chunks.append(audio_bytes)

        async def publish_audio_done(self, *args, **kwargs) -> None:
            return None

    class _NoopPlayoutEngine:
        def __init__(self):
            self.keys = []

        def ensure_task(self, key, state):
            self.keys.append(key)

        async def cancel(self, *args, **kwargs):
            return None

        async def mark_done(self, *args, **kwargs):
            return None

    handler = AudioDeltaHandler(
        acs_outbound_bus=EventBus("test_streaming_resampler"),
        session_metadata=session_metadata,
        provider_capabilities=capabilities,
        transcoder=AudioTranscoder(PcmConverter()),
        publisher=_StubPublisher(),
        playout_engine=_NoopPlayoutEngine(),
    )

    audio_bytes = b"\x00\x01" * 480  # 20ms at 24k mono -> 960 bytes
    events = [
        _provider_event(
            payload={"audio_b64": Base64AudioCodec.encode(audio_bytes), "seq": seq, "format": {}},
            provider="voice_live",
            stream_id="stream-multi",
        )
        for seq in range(3)
    ]

    for evt in events:
        await handler.handle(evt)

    buffer_key = handler.stream_key_builder.build(events[0])
    state = handler.store.get(buffer_key)
    assert state is not None
    assert isinstance(state.resampler, StreamingPcmResampler)
    source_format = capabilities.provider_output_format
    target_format = handler.target_format
    total_src_frames = (len(audio_bytes) * len(events)) // source_format.bytes_per_frame()
    expected_frames = int(round(total_src_frames * (target_format.sample_rate_hz / source_format.sample_rate_hz)))
    expected_bytes = expected_frames * target_format.bytes_per_frame()
    assert len(state.buffer) == expected_bytes
    assert len(state.buffer) % state.frame_bytes == 0
    await handler.acs_outbound_bus.shutdown()


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
        def convert(self, pcm, src, dst, resampler=None, *, streaming: bool = False):
            raise UnsupportedAudioFormatError("bad")

    failing = AudioTranscoder(FailingConverter())
    with pytest.raises(AudioTranscodingError):
        failing.transcode(audio, fmt, AudioFormat(8000, 1, "pcm16"))


@pytest.mark.asyncio
async def test_voicelive_outbound_handler_resamples_to_provider_input():
    session_metadata = {"acs_audio": {"format": {"sample_rate_hz": 16000, "channels": 1, "encoding": "pcm16"}}}
    capabilities = ProviderAudioCapabilities(
        provider_input_format=AudioFormat(sample_rate_hz=24000, channels=1, sample_format="pcm16"),
        provider_output_format=AudioFormat(sample_rate_hz=24000, channels=1, sample_format="pcm16"),
    )
    converter = RecordingConverter()

    class _StubWebSocket:
        def __init__(self):
            self.sent = []

        async def send(self, payload):
            self.sent.append(payload)

    ws = _StubWebSocket()
    handler = VoiceLiveOutboundHandler(
        ws,
        session_metadata=session_metadata,
        capabilities=capabilities,
        converter=converter,
    )
    audio_bytes = b"\x00\x01" * 320  # 20ms at 16k mono -> 640 bytes
    event = ProviderInputEvent(
        commit_id="commit-x",
        session_id="session-y",
        participant_id=None,
        b64_audio_string=Base64AudioCodec.encode(audio_bytes),
        metadata={},
    )

    await handler.handle(event)
    assert converter.calls
    assert ws.sent
    payload = json.loads(ws.sent[0])
    outbound_audio = Base64AudioCodec.decode(payload["audio"])
    assert len(outbound_audio) > len(audio_bytes)
    assert outbound_audio == converter.last_output


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

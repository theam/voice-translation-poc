import base64

import pytest

from production.acs_emulator.message_handlers.audio_data import AudioDataHandler
from production.capture.playout_assembler import PlayoutAssembler


def _audio_message(data: bytes, timestamp: str | None = None) -> dict:
    payload = {
        "kind": "AudioData",
        "audioData": {
            "data": base64.b64encode(data).decode("ascii"),
        },
    }
    if timestamp:
        payload["audioData"]["timestamp"] = timestamp
    return payload


def test_audio_data_handler_sets_timestamp_none_when_missing():
    handler = AudioDataHandler(adapter=None)
    message = _audio_message(b"\x00\x01")

    event = handler.decode(message)

    assert event.timestamp_ms is None


def test_playout_assembler_handles_variable_chunking_and_jitter():
    assembler = PlayoutAssembler(sample_rate=16000, channels=1, initial_buffer_ms=80)

    start1, dur1 = assembler.add_chunk(
        "stream-1",
        arrival_ms=100.0,
        media_now_ms=100.0,
        pcm_bytes=b"\x00" * 3200,  # 100ms
    )
    start2, dur2 = assembler.add_chunk(
        "stream-1",
        arrival_ms=130.0,
        media_now_ms=130.0,
        pcm_bytes=b"\x00" * 6400,  # 200ms, arrives earlier than cursor
    )
    start3, dur3 = assembler.add_chunk(
        "stream-1",
        arrival_ms=250.0,
        media_now_ms=250.0,
        pcm_bytes=b"\x00" * 16000,  # 500ms
    )

    assert start1 == pytest.approx(180.0)
    assert start2 == pytest.approx(280.0)
    assert start3 == pytest.approx(480.0)

    assert dur1 == pytest.approx(100.0)
    assert dur2 == pytest.approx(200.0)
    assert dur3 == pytest.approx(500.0)


def test_playout_assembler_tracks_independent_streams():
    assembler = PlayoutAssembler(sample_rate=16000, channels=2, initial_buffer_ms=50)

    left_start, _ = assembler.add_chunk(
        "left",
        arrival_ms=20.0,
        media_now_ms=20.0,
        pcm_bytes=b"\x00" * 3200,  # 20ms arrival + 50 buffer
    )
    right_start, _ = assembler.add_chunk(
        "right",
        arrival_ms=100.0,
        media_now_ms=100.0,
        pcm_bytes=b"\x00" * 6400,
    )
    left_next, _ = assembler.add_chunk(
        "left",
        arrival_ms=500.0,
        media_now_ms=500.0,
        pcm_bytes=b"\x00" * 3200,
    )

    assert left_start == pytest.approx(70.0)
    assert right_start == pytest.approx(150.0)
    assert left_next == pytest.approx(550.0)  # media clock advanced well past prior playout


def test_playout_assembler_trims_partial_frames_and_chains_from_media_clock():
    assembler = PlayoutAssembler(sample_rate=8000, channels=1, initial_buffer_ms=30)

    # 8000 Hz, mono, 2 bytes/sample => 160 bytes = 10ms, provide non-multiple to ensure trimming
    start1, dur1 = assembler.add_chunk(
        "stream-2",
        arrival_ms=10.0,
        media_now_ms=10.0,
        pcm_bytes=b"\x00" * 165,  # 165 -> trimmed to 164 => 10.25ms -> expect 10.25
    )
    start2, dur2 = assembler.add_chunk(
        "stream-2",
        arrival_ms=30.0,
        media_now_ms=20.0,  # media clock advanced but still before previous playout finishes
        pcm_bytes=b"\x00" * 320,  # 20ms
    )

    assert start1 == pytest.approx(40.0)  # media_now + buffer
    assert dur1 == pytest.approx(10.25)
    assert start2 == pytest.approx(50.25)  # chained from previous playout end
    assert dur2 == pytest.approx(20.0)

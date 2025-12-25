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

    start1, dur1 = assembler.add_chunk("stream-1", 100.0, b"\x00" * 3200)   # 100ms
    start2, dur2 = assembler.add_chunk("stream-1", 130.0, b"\x00" * 6400)   # 200ms, arrives earlier than cursor
    start3, dur3 = assembler.add_chunk("stream-1", 250.0, b"\x00" * 16000)  # 500ms

    assert start1 == pytest.approx(180.0)
    assert start2 == pytest.approx(280.0)
    assert start3 == pytest.approx(480.0)

    assert dur1 == pytest.approx(100.0)
    assert dur2 == pytest.approx(200.0)
    assert dur3 == pytest.approx(500.0)


def test_playout_assembler_tracks_independent_streams():
    assembler = PlayoutAssembler(sample_rate=16000, channels=2, initial_buffer_ms=50)

    left_start, _ = assembler.add_chunk("left", 20.0, b"\x00" * 3200)   # 20ms arrival + 50 buffer
    right_start, _ = assembler.add_chunk("right", 100.0, b"\x00" * 6400)
    left_next, _ = assembler.add_chunk("left", 500.0, b"\x00" * 3200)

    assert left_start == pytest.approx(70.0)
    assert right_start == pytest.approx(150.0)
    assert left_next == pytest.approx(120.0)

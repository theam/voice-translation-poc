import pytest

from production.capture.arrival_queue_assembler import ArrivalQueueAssembler


def test_chunks_queue_on_same_stream():
    assembler = ArrivalQueueAssembler(sample_rate=16000, channels=1)

    start1, dur1 = assembler.add_chunk("stream-1", arrival_ms=100.0, pcm_bytes=b"\x00" * 3200)  # 100ms
    start2, dur2 = assembler.add_chunk("stream-1", arrival_ms=100.0, pcm_bytes=b"\x00" * 1600)  # 50ms
    start3, dur3 = assembler.add_chunk("stream-1", arrival_ms=120.0, pcm_bytes=b"\x00" * 1600)  # 50ms

    assert start1 == pytest.approx(100.0)
    assert dur1 == pytest.approx(100.0)
    assert start2 == pytest.approx(start1 + dur1)
    assert dur2 == pytest.approx(50.0)
    assert start3 == pytest.approx(start2 + dur2)
    assert dur3 == pytest.approx(50.0)


def test_chunks_with_constant_arrival_do_not_overlap():
    assembler = ArrivalQueueAssembler(sample_rate=8000, channels=2)

    # frame_bytes = 4; 400 bytes = 12.5ms at 8kHz stereo 16-bit
    start1, dur1 = assembler.add_chunk("s", arrival_ms=10.0, pcm_bytes=b"\x00" * 400)
    start2, dur2 = assembler.add_chunk("s", arrival_ms=10.0, pcm_bytes=b"\x00" * 400)

    assert start2 >= start1 + dur1
    assert dur1 == pytest.approx(12.5)
    assert dur2 == pytest.approx(12.5)


def test_independent_streams_keep_separate_playheads():
    assembler = ArrivalQueueAssembler(sample_rate=16000, channels=1)

    left_start, left_dur = assembler.add_chunk("left", arrival_ms=0.0, pcm_bytes=b"\x00" * 3200)
    right_start, right_dur = assembler.add_chunk("right", arrival_ms=0.0, pcm_bytes=b"\x00" * 3200)
    left_next, _ = assembler.add_chunk("left", arrival_ms=10.0, pcm_bytes=b"\x00" * 1600)

    assert left_start == pytest.approx(0.0)
    assert right_start == pytest.approx(0.0)
    assert left_dur == pytest.approx(100.0)
    assert right_dur == pytest.approx(100.0)
    assert left_next == pytest.approx(left_start + left_dur)


def test_empty_payload_does_not_advance_playhead():
    assembler = ArrivalQueueAssembler(sample_rate=16000, channels=1)

    start1, dur1 = assembler.add_chunk("s", arrival_ms=5.0, pcm_bytes=b"")
    start2, dur2 = assembler.add_chunk("s", arrival_ms=10.0, pcm_bytes=b"\x00" * 3200)

    assert dur1 == 0.0
    assert start1 == pytest.approx(5.0)
    assert start2 == pytest.approx(10.0)
    assert dur2 == pytest.approx(100.0)

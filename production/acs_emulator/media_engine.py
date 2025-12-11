"""Media engine to convert audio files into ACS-ready PCM chunks."""
from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Iterator, Tuple


logger = logging.getLogger(__name__)


FRAME_DURATION_MS = 20


@dataclass
class MediaFrame:
    """Represents a single media frame (audio or silence).

    Attributes:
        timestamp_ms: Relative timestamp in milliseconds from stream start
        data: Raw PCM audio bytes (16-bit mono by default)
        is_silence: True if this frame contains only silence
    """
    timestamp_ms: int
    data: bytes
    is_silence: bool = False


def _yield_frames(wav: wave.Wave_read, frame_duration_ms: int) -> Iterator[Tuple[int, bytes]]:
    sample_rate = wav.getframerate()
    frame_size = int(sample_rate * (frame_duration_ms / 1000.0))
    timestamp_ms = 0
    while True:
        data = wav.readframes(frame_size)
        if not data:
            break
        yield timestamp_ms, data
        timestamp_ms += frame_duration_ms


def chunk_audio(file_path: Path, frame_duration_ms: int = FRAME_DURATION_MS) -> Iterator[Tuple[int, bytes]]:
    """Chunk a WAV file into PCM frames with timestamps.

    This uses only the stdlib ``wave`` module to avoid optional dependencies.
    The function expects mono 16-bit PCM input; callers should normalize audio
    before invoking if different formats are required.
    """

    with wave.open(str(file_path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError(
                f"Unsupported audio format: channels={wav.getnchannels()} width={wav.getsampwidth()}"
            )
        yield from _yield_frames(wav, frame_duration_ms)


async def async_chunk_audio(file_path: Path, frame_duration_ms: int = FRAME_DURATION_MS) -> AsyncIterator[Tuple[int, bytes]]:
    for timestamp_ms, data in chunk_audio(file_path, frame_duration_ms):
        yield timestamp_ms, data


def calculate_frame_size(sample_rate: int, channels: int = 1, sample_width: int = 2, duration_ms: int = FRAME_DURATION_MS) -> int:
    """Calculate the size in bytes for a PCM frame.

    Args:
        sample_rate: Sample rate in Hz (e.g., 16000)
        channels: Number of audio channels (1 for mono, 2 for stereo)
        sample_width: Bytes per sample (2 for 16-bit PCM)
        duration_ms: Frame duration in milliseconds

    Returns:
        Frame size in bytes
    """
    return int(sample_rate * (duration_ms / 1000.0) * channels * sample_width)


def generate_silence_frame(sample_rate: int, channels: int = 1, sample_width: int = 2, duration_ms: int = FRAME_DURATION_MS) -> bytes:
    """Generate a single silence frame (zero bytes).

    Args:
        sample_rate: Sample rate in Hz (e.g., 16000)
        channels: Number of audio channels (1 for mono, 2 for stereo)
        sample_width: Bytes per sample (2 for 16-bit PCM)
        duration_ms: Frame duration in milliseconds

    Returns:
        Zero-filled PCM data bytes
    """
    frame_size = calculate_frame_size(sample_rate, channels, sample_width, duration_ms)
    return bytes(frame_size)


async def async_stream_silence(
    duration_ms: int,
    start_time_ms: int = 0,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
    frame_duration_ms: int = FRAME_DURATION_MS
) -> AsyncIterator[MediaFrame]:
    """Stream silence frames for a given duration.

    Args:
        duration_ms: Total duration of silence to generate
        start_time_ms: Starting timestamp for the first frame
        sample_rate: Sample rate in Hz (e.g., 16000)
        channels: Number of audio channels (1 for mono, 2 for stereo)
        sample_width: Bytes per sample (2 for 16-bit PCM)
        frame_duration_ms: Duration of each frame in milliseconds

    Yields:
        MediaFrame objects with silence data
    """
    if duration_ms <= 0:
        return

    current_time = start_time_ms
    end_time = start_time_ms + duration_ms
    frame_size = calculate_frame_size(sample_rate, channels, sample_width, frame_duration_ms)

    while current_time < end_time:
        # Calculate actual chunk duration (may be less than frame_duration_ms for the last frame)
        chunk_ms = min(frame_duration_ms, end_time - current_time)

        # Adjust frame size for partial frames
        if chunk_ms < frame_duration_ms:
            chunk_size = max(1, int(frame_size * (chunk_ms / frame_duration_ms)))
        else:
            chunk_size = frame_size

        silence_data = bytes(chunk_size)
        yield MediaFrame(
            timestamp_ms=current_time,
            data=silence_data
        )

        current_time += chunk_ms


__all__ = [
    "chunk_audio",
    "async_chunk_audio",
    "calculate_frame_size",
    "generate_silence_frame",
    "async_stream_silence",
    "MediaFrame",
    "FRAME_DURATION_MS",
]

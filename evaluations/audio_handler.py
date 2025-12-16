"""Audio processing utilities for evaluation system."""

import base64
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from models import DEFAULT_PARTICIPANT_ID


DEFAULT_CHUNK_DURATION_MS = 100


def read_wav_chunks(wav_path: Path, chunk_duration_ms: int = DEFAULT_CHUNK_DURATION_MS) -> Iterator[bytes]:
    """
    Read WAV file and yield raw PCM chunks of specified duration.

    The chunks are yielded exactly as they appear in the WAV file. It is the
    caller's responsibility to ensure that the Azure Communication Service
    (ACS) metadata matches the actual WAV format so downstream components
    (WebSocket server, playback, resamplers) can handle them correctly.

    Args:
        wav_path: Path to WAV file
        chunk_duration_ms: Duration of each chunk in milliseconds

    Yields:
        Raw PCM audio bytes as stored in the WAV file
    """
    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        channels = wav_file.getnchannels()

        print(f"  WAV format: {sample_rate}Hz, {sample_width*8}-bit, {channels} channel(s)")

        # Calculate frames per chunk based on duration
        frames_per_chunk = int(sample_rate * chunk_duration_ms / 1000)

        print(f"  Chunk size: {frames_per_chunk} frames (~{chunk_duration_ms}ms)")

        total_frames = wav_file.getnframes()
        frames_read = 0

        while frames_read < total_frames:
            frames_to_read = min(frames_per_chunk, total_frames - frames_read)
            chunk = wav_file.readframes(frames_to_read)

            if not chunk:
                break

            frames_read += frames_to_read
            yield chunk


def get_wav_format(wav_path: Path) -> tuple[int, int, int]:
    """
    Inspect a WAV file and return its format as (sample_rate, channels, bits_per_sample).

    This is used by the evaluation sender so we can populate ACS metadata with
    the true format of the file, allowing the WebSocket server to resample
    and play back audio at the correct speed instead of assuming 16 kHz mono
    for all inputs.
    """
    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        bits_per_sample = wav_file.getsampwidth() * 8
    return sample_rate, channels, bits_per_sample


def create_audio_data_message(
    audio_chunk: bytes,
    participant_id: str = DEFAULT_PARTICIPANT_ID,
    silent: bool = False,
    *,
    sample_rate: Optional[int] = None,
    channels: Optional[int] = None,
    bits_per_sample: Optional[int] = None,
) -> dict:
    """
    Create AudioData message in Azure Communication Service format.

    Args:
        audio_chunk: Raw PCM audio bytes
        participant_id: Participant identifier
        silent: Whether this chunk is silent

    Returns:
        Dictionary with AudioData message structure. If sample_rate,
        channels, and bits_per_sample are provided, they are included so
        the server can correctly interpret and, if needed, resample the
        audio. Otherwise, the server will fall back to its defaults.
    """
    # Encode audio data to base64
    audio_base64 = base64.b64encode(audio_chunk).decode('utf-8')

    # Create timestamp in ISO format with timezone
    timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    audio_data: dict = {
        "timestamp": timestamp,
        "participantRawID": participant_id,
        "data": audio_base64,
        "silent": silent,
    }

    # Only attach explicit format fields if we have a complete description.
    if sample_rate is not None and channels is not None and bits_per_sample is not None:
        audio_data.update(
            {
                "sampleRate": sample_rate,
                "channels": channels,
                "bitsPerSample": bits_per_sample,
                "format": "pcm",
            }
        )

    return {
        "kind": "AudioData",
        "audioData": audio_data,
    }

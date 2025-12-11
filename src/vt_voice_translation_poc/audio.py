"""Audio helpers for feeding data into the Azure Speech SDK."""

from __future__ import annotations

import threading
import os
import subprocess
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Deque, Iterator, Optional

import azure.cognitiveservices.speech as speechsdk
from rich.console import Console

try:
    import pyaudio
except Exception:  # pragma: no cover
    pyaudio = None

try:
    import sounddevice as sd
except Exception:  # pragma: no cover
    sd = None

console = Console()

# Default audio format for microphone streaming
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1
DEFAULT_CHUNK_SIZE = 3200  # ~100ms @ 16kHz mono 16-bit
DEFAULT_SAMPLE_WIDTH = 2  # 16-bit PCM


class AudioSourceType(Enum):
    """Type of audio source."""
    FILE = auto()
    MICROPHONE = auto()
    STREAM = auto()


@dataclass
class AudioInput:
    """Represents an audio source for the Speech SDK."""

    source_type: AudioSourceType
    config: speechsdk.audio.AudioConfig
    stream: Optional[speechsdk.audio.PushAudioInputStream] = None
    source_path: Optional[Path] = None
    
    # Internal state for streaming/microphone
    _microphone_stream: Optional[object] = None  # pyaudio.Stream
    _microphone_pyaudio: Optional[object] = None  # pyaudio.PyAudio instance
    _microphone_thread: Optional[threading.Thread] = None
    _audio_queue: Deque[bytes] = field(default_factory=lambda: deque(maxlen=512))
    _stop_capture: Optional[threading.Event] = None
    _custom_format: Optional[tuple[int, int, int]] = None  # (sample_rate, channels, sample_width)

    @property
    def is_microphone(self) -> bool:
        """Check if this is a microphone input."""
        return self.source_type == AudioSourceType.MICROPHONE

    @property
    def is_file(self) -> bool:
        """Check if this is a file-based input."""
        return self.source_type == AudioSourceType.FILE

    @property
    def is_stream(self) -> bool:
        """Check if this is a generic stream input."""
        return self.source_type == AudioSourceType.STREAM

    def write(self, chunk: bytes) -> None:
        """
        Write audio data to the input.
        Only valid for STREAM source type.
        Feeds both the internal queue (for get_audio_chunks) and the SDK stream (if present).
        """
        if self.source_type != AudioSourceType.STREAM:
            raise RuntimeError(f"Cannot write to AudioInput of type {self.source_type}")

        # Feed internal queue for manual consumers (like Voice Live)
        self._audio_queue.append(chunk)

        # Feed SDK stream if configured (for Live Interpreter)
        if self.stream:
            self.stream.write(chunk)

    def get_audio_chunks(self) -> Iterator[bytes]:
        """
        Get audio chunks for streaming providers (e.g., Voice Live).
        For microphone/stream input, yields chunks in real-time.
        For file input, yields chunks from the file.
        """
        if self.source_type in (AudioSourceType.MICROPHONE, AudioSourceType.STREAM):
            while True:
                if self._stop_capture and self._stop_capture.is_set():
                    break
                
                # Check if queue has items before trying to pop
                if len(self._audio_queue) > 0:
                    chunk = self._audio_queue.popleft()
                    if chunk:
                        yield chunk
                else:
                    import time
                    time.sleep(0.002)  # Small delay to avoid busy waiting

        elif self.source_type == AudioSourceType.FILE:
            if self.source_path is None:
                raise RuntimeError("File path not set")
            if self.source_path.suffix.lower() == ".wav":
                # Use wave module to properly read WAV files
                import wave
                with wave.open(str(self.source_path), "rb") as wav_file:
                    sample_rate = wav_file.getframerate()
                    # Calculate frames for ~100ms chunks
                    frames_per_chunk = max(1, sample_rate // 10)  # ~100ms
                    total_frames = wav_file.getnframes()
                    frames_read = 0
                    while frames_read < total_frames:
                        frames_to_read = min(frames_per_chunk, total_frames - frames_read)
                        chunk = wav_file.readframes(frames_to_read)
                        if not chunk:
                            break
                        yield chunk
                        frames_read += frames_to_read
            else:
                # For other formats, read raw bytes
                with self.source_path.open("rb") as f:
                    chunk = f.read(DEFAULT_CHUNK_SIZE)
                    while chunk:
                        yield chunk
                        chunk = f.read(DEFAULT_CHUNK_SIZE)
        else:
            raise RuntimeError(f"Unknown audio source type: {self.source_type}")

    def get_audio_format(self) -> tuple[int, int, int]:
        """
        Get audio format (sample_rate, channels, sample_width).
        Returns defaults for microphone/stream, reads from file for WAV files.
        If _custom_format is set, returns that instead.
        """
        if self._custom_format is not None:
            return self._custom_format
            
        if self.source_type in (AudioSourceType.MICROPHONE, AudioSourceType.STREAM):
            return (DEFAULT_SAMPLE_RATE, DEFAULT_CHANNELS, DEFAULT_SAMPLE_WIDTH)
            
        elif self.source_type == AudioSourceType.FILE and self.source_path:
            if self.source_path.suffix.lower() == ".wav":
                import wave
                with wave.open(str(self.source_path), "rb") as wav_file:
                    return (
                        wav_file.getframerate(),
                        wav_file.getnchannels(),
                        wav_file.getsampwidth(),
                    )
            # Default for other formats
            return (DEFAULT_SAMPLE_RATE, DEFAULT_CHANNELS, DEFAULT_SAMPLE_WIDTH)
            
        return (DEFAULT_SAMPLE_RATE, DEFAULT_CHANNELS, DEFAULT_SAMPLE_WIDTH)

    def close(self) -> None:
        """Close any underlying audio stream."""
        if self._stop_capture:
            self._stop_capture.set()
        if self._microphone_stream:
            try:
                if hasattr(self._microphone_stream, 'stop_stream'):
                    self._microphone_stream.stop_stream()
                if hasattr(self._microphone_stream, 'close'):
                    self._microphone_stream.close()
            except Exception:  # pragma: no cover
                pass
        if self._microphone_pyaudio:
            try:
                if hasattr(self._microphone_pyaudio, 'terminate'):
                    self._microphone_pyaudio.terminate()
            except Exception:  # pragma: no cover
                pass
        if self._microphone_thread and self._microphone_thread.is_alive():
            self._microphone_thread.join(timeout=1.0)
        if self.stream:
            self.stream.close()

    def __enter__(self) -> "AudioInput":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def build_audio_input(source_path: Optional[Path], use_streaming_microphone: bool = False) -> AudioInput:
    """
    Create an `AudioInput` from a file path or microphone.
    
    Args:
        source_path: Optional path to audio file. If None, uses microphone.
        use_streaming_microphone: If True and source_path is None, creates a streaming
            microphone input suitable for Voice Live. If False, uses Azure SDK's default
            microphone (for Live Interpreter).
    """
    if source_path is None:
        if use_streaming_microphone:
            return _build_streaming_microphone_input()
        console.print("[bold green]Using default microphone input[/bold green]")
        return AudioInput(
            source_type=AudioSourceType.MICROPHONE,
            config=speechsdk.audio.AudioConfig(use_default_microphone=True)
        )

    if not source_path.exists():
        raise FileNotFoundError(f"Audio file not found: {source_path}")

    suffix = source_path.suffix.lower()
    if suffix == ".wav":
        console.print(f"[bold green]Using WAV file:[/bold green] {source_path}")
        return AudioInput(
            source_type=AudioSourceType.FILE,
            config=speechsdk.audio.AudioConfig(filename=str(source_path)),
            source_path=source_path,
        )

    if suffix == ".mp3":
        console.print(f"[bold green]Using MP3 file (converted in-memory):[/bold green] {source_path}")
        stream_format = speechsdk.audio.AudioStreamFormat(
            compressed_stream_format=speechsdk.AudioStreamContainerFormat.MP3
        )
        push_stream = speechsdk.audio.PushAudioInputStream(stream_format)
        with source_path.open("rb") as audio_file:
            chunk = audio_file.read(4096)
            while chunk:
                push_stream.write(chunk)
                chunk = audio_file.read(4096)
        push_stream.close()
        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
        return AudioInput(
            source_type=AudioSourceType.FILE,
            config=audio_config,
            stream=push_stream,
            source_path=source_path,
        )

    if suffix in {".m4a", ".aac"}:
        converted_path = _convert_audio_to_wav(source_path)
        console.print(
            f"[bold green]Converted {source_path.name} to WAV:[/bold green] {converted_path}"
        )
        return AudioInput(
            source_type=AudioSourceType.FILE,
            config=speechsdk.audio.AudioConfig(filename=str(converted_path)),
            source_path=converted_path,
        )

    raise ValueError(
        f"Unsupported audio format '{suffix}'. "
        "Supported formats: .wav (native), .mp3 (in-memory conversion), .m4a/.aac (via ffmpeg)."
    )


def _convert_audio_to_wav(
    source_path: Path,
    *,
    target_sample_rate: int = DEFAULT_SAMPLE_RATE,
    target_channels: int = DEFAULT_CHANNELS,
) -> Path:
    """
    Convert compressed audio (e.g., M4A/AAC) to a WAV file using ffmpeg.
    The converted file is written into the project samples directory so it can be reviewed.
    """
    project_root = Path(__file__).resolve().parents[2]
    samples_dir = project_root / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    target_path = samples_dir / f"{source_path.stem}_converted.wav"
    if target_path.exists():
        target_path.unlink()

    ffmpeg_path = os.getenv("FFMPEG_PATH", "ffmpeg")

    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(source_path),
        "-ac",
        str(target_channels),
        "-ar",
        str(target_sample_rate),
        "-sample_fmt",
        "s16",
        str(target_path),
    ]

    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg not found. Install ffmpeg or set the FFMPEG_PATH environment variable."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"ffmpeg failed to convert {source_path.name}: {stderr}") from exc

    console.print(
        f"[bold blue]Converted audio saved to samples:[/bold blue] {target_path}"
    )

    return target_path


def _build_streaming_microphone_input() -> AudioInput:
    """Create a streaming microphone input using pyaudio or sounddevice for Voice Live."""
    if pyaudio is None and sd is None:
        raise RuntimeError(
            "pyaudio or sounddevice is required for microphone streaming. "
            "Install one with: pip install pyaudio (requires PortAudio) or pip install sounddevice"
        )
    
    # Prefer sounddevice as it's easier to install on Apple Silicon
    use_sounddevice = sd is not None

    console.print("[bold green]Using streaming microphone input[/bold green]")
    
    audio_queue: Deque[bytes] = deque(maxlen=512)
    stop_capture = threading.Event()
    
    def _capture_audio():
        """Capture audio from microphone in a separate thread."""
        try:
            if use_sounddevice:
                # Use sounddevice (easier on Apple Silicon)
                import numpy as np
                try:
                    with sd.InputStream(
                        samplerate=DEFAULT_SAMPLE_RATE,
                        channels=DEFAULT_CHANNELS,
                        dtype=np.int16,
                        blocksize=DEFAULT_CHUNK_SIZE // 2,  # frames = bytes / (channels * sample_width)
                    ) as stream:
                        overflow_count = 0
                        while not stop_capture.is_set():
                            try:
                                data, overflowed = stream.read(DEFAULT_CHUNK_SIZE // 2)
                                if overflowed:
                                    overflow_count += 1
                                    # Only log overflow every 10 occurrences to reduce noise
                                    if overflow_count % 10 == 0:
                                        console.print(f"[yellow]Audio buffer overflow (x{overflow_count})[/yellow]")
                                audio_queue.append(data.tobytes())
                            except Exception:  # pragma: no cover
                                break
                except Exception as e:  # pragma: no cover
                    console.print(f"[bold red]Sounddevice stream error: {e}[/bold red]")
                    raise
            else:
                # Use pyaudio (fallback)
                pyaudio_instance = pyaudio.PyAudio()
                pyaudio_stream = pyaudio_instance.open(
                    format=pyaudio.paInt16,
                    channels=DEFAULT_CHANNELS,
                    rate=DEFAULT_SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=DEFAULT_CHUNK_SIZE,
                )
                
                while not stop_capture.is_set():
                    try:
                        data = pyaudio_stream.read(DEFAULT_CHUNK_SIZE, exception_on_overflow=False)
                        audio_queue.append(data)
                    except Exception:  # pragma: no cover
                        break
                
                pyaudio_stream.stop_stream()
                pyaudio_stream.close()
                pyaudio_instance.terminate()
        except Exception as e:  # pragma: no cover
            console.print(f"[bold red]Microphone capture error: {e}[/bold red]")
    
    capture_thread = threading.Thread(target=_capture_audio, daemon=True)
    capture_thread.start()
    
    # Give the thread a moment to initialize
    import time
    time.sleep(0.1)
    
    # Create a dummy AudioConfig (not used for Voice Live, but required by protocol)
    audio_input = AudioInput(
        source_type=AudioSourceType.MICROPHONE,
        config=speechsdk.audio.AudioConfig(use_default_microphone=True),
        _microphone_stream=None,  # Not needed for sounddevice
        _microphone_pyaudio=None,  # Not needed for sounddevice
        _microphone_thread=capture_thread,
        _audio_queue=audio_queue,
        _stop_capture=stop_capture,
    )
    
    return audio_input



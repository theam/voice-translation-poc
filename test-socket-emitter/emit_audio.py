#!/usr/bin/env python3
"""WebSocket client for sending audio data or JSON messages to the translation server."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
import wave
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Optional

import websockets
from websockets.exceptions import ConnectionClosedError, InvalidURI
from urllib.parse import urlparse

# Try to import audio libraries for microphone support
try:
    import sounddevice as sd
    import numpy as np
    AUDIO_AVAILABLE = True
except ImportError:
    sd = None
    np = None
    AUDIO_AVAILABLE = False

# Audio format constants (must match server expectations)
MIC_SAMPLE_RATE = 16000
MIC_CHANNELS = 1
MIC_BITS_PER_SAMPLE = 16
MIC_CHUNK_SIZE = 3200  # ~100ms at 16kHz mono 16-bit


def _get_server_command(uri: str) -> str:
    """Extract host and port from URI to suggest server command."""
    try:
        parsed = urlparse(uri)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8765
        return f"speech-poc serve --host {host} --port {port}"
    except Exception:
        return "speech-poc serve --host localhost --port 8765"


def _convert_to_target_format(
    source_path: Path,
    target_sample_rate: int = 16000,
    target_channels: int = 1,
    verbose: bool = False
) -> Path:
    """
    Convert/resample WAV file to target format (16kHz, 16-bit, mono) if needed.
    
    Args:
        source_path: Path to source WAV file
        target_sample_rate: Target sample rate in Hz (default: 16000)
        target_channels: Target number of channels (default: 1 for mono)
        verbose: Enable verbose output
    
    Returns:
        Path to converted file (or original if no conversion needed)
    """
    # Check current format
    try:
        with wave.open(str(source_path), 'rb') as wav_file:
            current_sample_rate = wav_file.getframerate()
            current_channels = wav_file.getnchannels()
            current_sample_width = wav_file.getsampwidth()
            
            # Check if already in target format
            if (current_sample_rate == target_sample_rate and 
                current_channels == target_channels and 
                current_sample_width == 2):  # 2 bytes = 16 bits
                if verbose:
                    print(f"✓ Audio already in target format: {target_sample_rate}Hz, 16-bit, {target_channels}ch")
                return source_path
            
            if verbose:
                print(f"Converting audio format:")
                print(f"  From: {current_sample_rate}Hz, {current_sample_width*8}-bit, {current_channels}ch")
                print(f"  To: {target_sample_rate}Hz, 16-bit, {target_channels}ch")
    
    except Exception as e:
        print(f"✗ Error reading WAV file: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Create temporary file for converted audio
    temp_fd, temp_path = tempfile.mkstemp(suffix='.wav', prefix='converted_')
    os.close(temp_fd)
    temp_path_obj = Path(temp_path)
    
    ffmpeg_path = os.getenv("FFMPEG_PATH", "ffmpeg")
    
    command = [
        ffmpeg_path,
        "-y",  # Overwrite output file
        "-i", str(source_path),
        "-ac", str(target_channels),  # Audio channels
        "-ar", str(target_sample_rate),  # Audio sample rate
        "-sample_fmt", "s16",  # 16-bit signed PCM
        "-f", "wav",  # Output format
        str(temp_path_obj),
    ]
    
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if verbose:
            print(f"✓ Audio converted successfully")
        return temp_path_obj
        
    except FileNotFoundError:
        print(f"✗ Error: ffmpeg not found. Install ffmpeg or set FFMPEG_PATH environment variable.", file=sys.stderr)
        temp_path_obj.unlink(missing_ok=True)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="ignore").strip()
        print(f"✗ Error: ffmpeg conversion failed: {stderr}", file=sys.stderr)
        temp_path_obj.unlink(missing_ok=True)
        sys.exit(1)


async def send_audio_file(
    uri: str,
    audio_path: Path,
    chunk_size: int = 3200,
    verbose: bool = False,
    participant_id: Optional[str] = None,
) -> None:
    """Send an audio file to the WebSocket server in chunks using ACS JSON format.
    
    The audio is automatically converted to 16kHz, 16-bit, mono PCM if needed.
    
    Args:
        uri: WebSocket server URI
        audio_path: Path to WAV audio file
        chunk_size: Size of audio chunks in bytes
        verbose: Enable verbose output
        participant_id: Optional participant/sender ID for ACS format
    """
    # Convert audio to target format (16kHz, 16-bit, mono)
    converted_path = _convert_to_target_format(audio_path, verbose=verbose)
    converted_is_temp = converted_path != audio_path
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"✓ Connected to {uri}")
            
            with wave.open(str(converted_path), 'rb') as wav_file:
                sample_rate = wav_file.getframerate()
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                frames = wav_file.getnframes()
                
                if verbose:
                    print(f"Audio file info:")
                    print(f"  - Sample rate: {sample_rate} Hz")
                    print(f"  - Channels: {channels}")
                    print(f"  - Sample width: {sample_width} bytes")
                    print(f"  - Total frames: {frames}")
                    print(f"  - Duration: ~{frames / sample_rate:.2f} seconds")
                    print(f"  - Format: ACS JSON with PCM 16-bit")
                
                print(f"Sending audio: {audio_path.name} (format: {sample_rate}Hz, {sample_width*8}-bit, {channels}ch)")
                chunk_count = 0
                total_bytes = 0
                
                # Generate participant ID if not provided
                if not participant_id:
                    # Use format similar to ACS participant IDs (e.g., "4:+34646783858")
                    participant_id = f"4:+{uuid.uuid4().hex[:11]}"
                    if verbose:
                        print(f"  Generated participant ID: {participant_id}")
                
                while True:
                    # Convert chunk_size (bytes) to frames for mono 16-bit audio
                    # For mono: 1 frame = sample_width bytes
                    frames_to_read = chunk_size // sample_width
                    audio_chunk = wav_file.readframes(frames_to_read)
                    if not audio_chunk:
                        break
                    
                    # Send in official ACS format: {"kind": "AudioData", "audioData": {...}}
                    # Note: We include optional format fields for proper audio processing
                    timestamp = datetime.now(timezone.utc).isoformat()
                    
                    acs_message = {
                        "kind": "AudioData",
                        "audioData": {
                            "timestamp": timestamp,
                            "participantRawID": participant_id or "unknown",
                            "data": base64.b64encode(audio_chunk).decode("ascii"),
                            "silent": False,
                            # Optional format fields (not in official spec but needed for proper processing)
                            "sampleRate": sample_rate,
                            "channels": channels,
                            "bitsPerSample": sample_width * 8,
                            "format": "pcm",
                        }
                    }
                    
                    message_json = json.dumps(acs_message)
                    await websocket.send(message_json)
                    
                    if verbose:
                        print(f"  Chunk {chunk_count}: {len(audio_chunk)} bytes (base64: {len(acs_message['audioData']['data'])} chars)")
                    
                    total_bytes += len(audio_chunk)
                    chunk_count += 1
                    
                    # Wait for acknowledgment
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        if verbose:
                            response_str = response.decode() if isinstance(response, bytes) else response
                            print(f"  Chunk {chunk_count}: → {response_str}")
                    except asyncio.TimeoutError:
                        if verbose:
                            print(f"  Chunk {chunk_count}: (no response)")
                
                print(f"✓ Audio transmission complete")
                print(f"  - Total chunks: {chunk_count}")
                print(f"  - Total bytes: {total_bytes}")
                print(f"  - Format: Official ACS JSON with base64-encoded audio")
                
    except FileNotFoundError:
        print(f"✗ Error: Audio file not found: {audio_path}", file=sys.stderr)
        sys.exit(1)
    except wave.Error as e:
        print(f"✗ Error: Invalid WAV file: {e}", file=sys.stderr)
        sys.exit(1)
    except (ConnectionRefusedError, OSError) as e:
        print(f"✗ Error: Cannot connect to server at {uri}", file=sys.stderr)
        print(f"  Connection refused. Is the server running?", file=sys.stderr)
        print(f"  Start the server with: {_get_server_command(uri)}", file=sys.stderr)
        sys.exit(1)
    except ConnectionClosedError as e:
        print(f"✗ Error: Connection closed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        error_msg = str(e)
        if "Connect call failed" in error_msg or "Connection refused" in error_msg:
            print(f"✗ Error: Cannot connect to server at {uri}", file=sys.stderr)
            print(f"  Connection refused. Is the server running?", file=sys.stderr)
            print(f"  Start the server with: {_get_server_command(uri)}", file=sys.stderr)
        else:
            print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Clean up temporary converted file if one was created
        if converted_is_temp and converted_path.exists():
            converted_path.unlink()
            if verbose:
                print(f"Cleaned up temporary converted file")


async def send_microphone_stream(
    uri: str,
    chunk_size: int = MIC_CHUNK_SIZE,
    verbose: bool = False,
    participant_id: Optional[str] = None,
    duration_seconds: Optional[int] = None,
) -> None:
    """Stream microphone audio to the WebSocket server in real-time using ACS JSON format.
    
    Captures audio from the default microphone at 16kHz, 16-bit, mono PCM and sends
    it to the server in chunks using the official ACS format.
    
    Args:
        uri: WebSocket server URI
        chunk_size: Size of audio chunks in bytes
        verbose: Enable verbose output
        participant_id: Optional participant/sender ID for ACS format
        duration_seconds: Optional duration limit in seconds (None = continuous)
    """
    if not AUDIO_AVAILABLE:
        print(f"✗ Error: sounddevice and numpy are required for microphone streaming.", file=sys.stderr)
        print(f"  Install with: pip install sounddevice numpy", file=sys.stderr)
        sys.exit(1)
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"✓ Connected to {uri}")
            
            if verbose:
                print(f"Microphone streaming info:")
                print(f"  - Sample rate: {MIC_SAMPLE_RATE} Hz")
                print(f"  - Channels: {MIC_CHANNELS} (mono)")
                print(f"  - Bits per sample: {MIC_BITS_PER_SAMPLE}")
                print(f"  - Chunk size: {chunk_size} bytes (~{chunk_size / (MIC_SAMPLE_RATE * 2) * 1000:.0f}ms)")
                print(f"  - Format: ACS JSON with PCM 16-bit")
                if duration_seconds:
                    print(f"  - Duration limit: {duration_seconds} seconds")
                else:
                    print(f"  - Duration: Continuous (press Ctrl+C to stop)")
            
            # Generate participant ID if not provided
            if not participant_id:
                participant_id = f"4:+{uuid.uuid4().hex[:11]}"
                if verbose:
                    print(f"  Generated participant ID: {participant_id}")
            
            print(f"Starting microphone capture... (press Ctrl+C to stop)")
            
            # Setup audio queue and stop event
            audio_queue: Deque[bytes] = deque(maxlen=512)
            stop_capture = threading.Event()
            capture_error = []  # Mutable list to capture errors from thread
            
            # Calculate frames per chunk (for sounddevice)
            frames_per_chunk = chunk_size // (MIC_CHANNELS * (MIC_BITS_PER_SAMPLE // 8))
            
            def audio_callback(indata, frames, time_info, status):
                """Callback for sounddevice to capture audio."""
                if status and verbose:
                    print(f"  [Audio callback status: {status}]", file=sys.stderr)
                try:
                    # Convert float32 to int16 and append to queue
                    audio_bytes = indata.tobytes()
                    audio_queue.append(audio_bytes)
                except Exception as e:
                    capture_error.append(str(e))
                    stop_capture.set()
            
            # Start audio stream
            try:
                stream = sd.InputStream(
                    samplerate=MIC_SAMPLE_RATE,
                    channels=MIC_CHANNELS,
                    dtype=np.int16,
                    blocksize=frames_per_chunk,
                    callback=audio_callback,
                )
                stream.start()
                
                if verbose:
                    print(f"✓ Microphone stream started")
            except Exception as e:
                print(f"✗ Error: Could not start microphone: {e}", file=sys.stderr)
                sys.exit(1)
            
            chunk_count = 0
            total_bytes = 0
            start_time = asyncio.get_event_loop().time()
            
            try:
                while not stop_capture.is_set():
                    # Check duration limit
                    if duration_seconds:
                        elapsed = asyncio.get_event_loop().time() - start_time
                        if elapsed >= duration_seconds:
                            print(f"\n✓ Duration limit reached ({duration_seconds}s)")
                            break
                    
                    # Check for capture errors
                    if capture_error:
                        print(f"✗ Error: Audio capture failed: {capture_error[0]}", file=sys.stderr)
                        break
                    
                    # Get audio chunk from queue
                    if len(audio_queue) > 0:
                        audio_chunk = audio_queue.popleft()
                        
                        if not audio_chunk:
                            continue
                        
                        # Send in official ACS format
                        timestamp = datetime.now(timezone.utc).isoformat()
                        
                        acs_message = {
                            "kind": "AudioData",
                            "audioData": {
                                "timestamp": timestamp,
                                "participantRawID": participant_id,
                                "data": base64.b64encode(audio_chunk).decode("ascii"),
                                "silent": False,
                                # Optional format fields for proper processing
                                "sampleRate": MIC_SAMPLE_RATE,
                                "channels": MIC_CHANNELS,
                                "bitsPerSample": MIC_BITS_PER_SAMPLE,
                                "format": "pcm",
                            }
                        }
                        
                        message_json = json.dumps(acs_message)
                        await websocket.send(message_json)
                        
                        if verbose:
                            print(f"  Chunk {chunk_count}: {len(audio_chunk)} bytes (base64: {len(acs_message['audioData']['data'])} chars)")
                        
                        total_bytes += len(audio_chunk)
                        chunk_count += 1
                        
                        # Wait for acknowledgment (with timeout to avoid blocking)
                        try:
                            response = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                            if verbose:
                                response_str = response.decode() if isinstance(response, bytes) else response
                                print(f"  Chunk {chunk_count}: → {response_str}")
                        except asyncio.TimeoutError:
                            if verbose and chunk_count <= 5:
                                print(f"  Chunk {chunk_count}: (no response)")
                    else:
                        # No audio in queue, wait a bit
                        await asyncio.sleep(0.01)
                
                # Print summary
                elapsed = asyncio.get_event_loop().time() - start_time
                print(f"\n✓ Microphone streaming complete")
                print(f"  - Total chunks: {chunk_count}")
                print(f"  - Total bytes: {total_bytes}")
                print(f"  - Duration: {elapsed:.2f} seconds")
                print(f"  - Format: Official ACS JSON with base64-encoded audio")
                
            finally:
                # Stop and close audio stream
                stop_capture.set()
                if stream:
                    stream.stop()
                    stream.close()
                    if verbose:
                        print(f"✓ Microphone stream stopped")
                    
    except KeyboardInterrupt:
        print(f"\n✓ Stopped by user")
        sys.exit(0)
    except (ConnectionRefusedError, OSError) as e:
        print(f"✗ Error: Cannot connect to server at {uri}", file=sys.stderr)
        print(f"  Connection refused. Is the server running?", file=sys.stderr)
        print(f"  Start the server with: {_get_server_command(uri)}", file=sys.stderr)
        sys.exit(1)
    except ConnectionClosedError as e:
        print(f"✗ Error: Connection closed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        error_msg = str(e)
        if "Connect call failed" in error_msg or "Connection refused" in error_msg:
            print(f"✗ Error: Cannot connect to server at {uri}", file=sys.stderr)
            print(f"  Connection refused. Is the server running?", file=sys.stderr)
            print(f"  Start the server with: {_get_server_command(uri)}", file=sys.stderr)
        else:
            print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


async def send_json_message(
    uri: str,
    message_type: str,
    message_data: str,
    verbose: bool = False,
) -> None:
    """Send a JSON message to the WebSocket server."""
    try:
        async with websockets.connect(uri) as websocket:
            print(f"✓ Connected to {uri}")
            
            message = {
                "type": message_type,
                "data": message_data
            }
            
            if verbose:
                print(f"Sending JSON message:")
                print(f"  {json.dumps(message, indent=2)}")
            else:
                print(f"Sending JSON message: type={message_type}")
            
            await websocket.send(json.dumps(message))
            
            # Wait for acknowledgment
            response = await websocket.recv()
            response_data = json.loads(response) if isinstance(response, str) else response
            
            if verbose:
                print(f"Server response:")
                print(f"  {json.dumps(response_data, indent=2) if isinstance(response_data, dict) else response_data}")
            else:
                print(f"✓ Server response: {response_data.get('status', 'received') if isinstance(response_data, dict) else 'received'}")
                
    except (ConnectionRefusedError, OSError) as e:
        print(f"✗ Error: Cannot connect to server at {uri}", file=sys.stderr)
        print(f"  Connection refused. Is the server running?", file=sys.stderr)
        print(f"  Start the server with: {_get_server_command(uri)}", file=sys.stderr)
        sys.exit(1)
    except ConnectionClosedError as e:
        print(f"✗ Error: Connection closed: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"✗ Error: Invalid JSON in response: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        error_msg = str(e)
        if "Connect call failed" in error_msg or "Connection refused" in error_msg:
            print(f"✗ Error: Cannot connect to server at {uri}", file=sys.stderr)
            print(f"  Connection refused. Is the server running?", file=sys.stderr)
            print(f"  Start the server with: {_get_server_command(uri)}", file=sys.stderr)
        else:
            print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Main entry point for the WebSocket client."""
    parser = argparse.ArgumentParser(
        description="Send audio files, microphone stream, or JSON messages to the translation WebSocket server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Send an audio file (automatically converted to 16kHz, 16-bit, mono)
  python emit_audio.py --audio samples/harvard.wav

  # Stream from microphone (16kHz, 16-bit, mono)
  python emit_audio.py --microphone

  # Stream from microphone with duration limit
  python emit_audio.py --microphone --duration 10

  # Send audio with custom participant ID
  python emit_audio.py --audio samples/harvard.wav --participant-id "4:+34646783858"

  # Send a JSON text message
  python emit_audio.py --json --type text_input --data "Hello, translate this"

  # Use custom host and port
  python emit_audio.py --audio samples/harvard.wav --host localhost --port 9000

  # Verbose output (shows conversion details)
  python emit_audio.py --audio samples/harvard.wav --verbose

Note:
  - Audio files are automatically converted to the required format (16kHz, 16-bit, mono PCM)
    if they are not already in that format. Requires ffmpeg to be installed.
  - Microphone streaming requires sounddevice and numpy: pip install sounddevice numpy
        """
    )
    
    parser.add_argument(
        '--host',
        default='localhost',
        help='WebSocket server host (default: localhost)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=8765,
        help='WebSocket server port (default: 8765)'
    )
    
    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        '--audio',
        type=Path,
        metavar='FILE',
        help='Path to WAV audio file to send (auto-converted to 16kHz, 16-bit, mono)'
    )
    mode_group.add_argument(
        '--microphone',
        action='store_true',
        help='Stream audio from microphone (16kHz, 16-bit, mono)'
    )
    mode_group.add_argument(
        '--json',
        action='store_true',
        help='Send a JSON message instead of audio'
    )
    
    # JSON message options
    parser.add_argument(
        '--type',
        default='text_input',
        help='Message type for JSON mode (default: text_input)'
    )
    parser.add_argument(
        '--data',
        help='Message data for JSON mode (required with --json)'
    )
    
    # Audio options
    parser.add_argument(
        '--chunk-size',
        type=int,
        default=3200,
        help='Audio chunk size in bytes (default: 3200 bytes = 100ms at 16kHz, 16-bit, mono)'
    )
    parser.add_argument(
        '--participant-id',
        help='Participant/sender ID (auto-generated if not provided)'
    )
    
    # Microphone options
    parser.add_argument(
        '--duration',
        type=int,
        metavar='SECONDS',
        help='Duration limit for microphone streaming in seconds (default: continuous until Ctrl+C)'
    )
    
    # General options
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Enable verbose output'
    )
    
    args = parser.parse_args()
    
    # Validate JSON mode
    if args.json and not args.data:
        parser.error("--data is required when using --json mode")
    
    # Validate microphone-specific options
    if args.duration and not args.microphone:
        parser.error("--duration can only be used with --microphone mode")
    
    # Build WebSocket URI
    uri = f"ws://{args.host}:{args.port}"
    
    # Validate URI
    try:
        # Basic validation
        if not args.host or args.port < 1 or args.port > 65535:
            raise ValueError("Invalid host or port")
    except Exception as e:
        print(f"✗ Error: Invalid connection parameters: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Execute based on mode
    if args.audio:
        asyncio.run(send_audio_file(
            uri, 
            args.audio, 
            args.chunk_size, 
            args.verbose,
            participant_id=args.participant_id
        ))
    elif args.microphone:
        asyncio.run(send_microphone_stream(
            uri,
            args.chunk_size,
            args.verbose,
            participant_id=args.participant_id,
            duration_seconds=args.duration
        ))
    elif args.json:
        asyncio.run(send_json_message(uri, args.type, args.data, args.verbose))


if __name__ == '__main__':
    main()


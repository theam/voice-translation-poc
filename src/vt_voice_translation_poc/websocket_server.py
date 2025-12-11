"""WebSocket server for receiving audio data from external applications."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
from collections import deque
from datetime import datetime
from typing import Optional

import azure.cognitiveservices.speech as speechsdk
import numpy as np
import websockets
from websockets.server import WebSocketServerProtocol
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
from rich.console import Console
from rich.panel import Panel

from .audio import AudioInput, AudioSourceType
from .config import SpeechServiceSettings
from .providers import create_translator

console = Console()
logger = logging.getLogger(__name__)

# Audio format constants
TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1
TARGET_BITS_PER_SAMPLE = 16


class WebSocketServer:
    """WebSocket server that receives audio data for translation processing."""

    def __init__(
        self,
        settings: SpeechServiceSettings,
        *,
        host: str = "localhost",
        port: int = 8765,
        from_language: str = "en-US",
        to_languages: list[str] | None = None,
        voice: Optional[str] = None,
        play_input_audio: bool = False,
        play_azure_audio: bool = False,
        testing_mode: bool = False,
    ) -> None:
        self.settings = settings
        self.host = host
        self.port = port
        self.from_language = from_language
        self.to_languages = to_languages or ["es"]
        self.voice = voice
        self.play_input_audio = play_input_audio
        self.play_azure_audio = play_azure_audio
        self.testing_mode = testing_mode
        # Per-client session state management
        self._client_sessions: dict[str, dict] = {}

    async def _handle_client(self, ws: WebSocketServerProtocol, path: str) -> None:
        """Handle an incoming WebSocket connection."""
        # Wrap websocket for logging
        from .websocket_logger import WebSocketLogger
        websocket = WebSocketLogger(ws, log_file="acs_messages.log", log_dir="logs")

        client_address = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        client_key = client_address
        console.print(
            Panel.fit(
                f"New WebSocket connection from {client_address}",
                title="Client connected",
                style="bold green",
            )
        )

        # Initialize streaming session
        session = self._initialize_streaming_session(client_key)
        translation_task = None
        playback_task = None

        try:
            # Start continuous translation in background
            translation_task = asyncio.create_task(
                self._run_continuous_translation(websocket, session)
            )
            
            # Start audio playback in background (if enabled)
            playback_task = None
            if self.play_input_audio:
                playback_task = asyncio.create_task(
                    self._play_received_audio(session)
                )
                console.print("[bold cyan]Input audio playback enabled[/bold cyan]")
            else:
                console.print("[dim]Input audio playback disabled[/dim]")

            # Process incoming messages and feed to audio queue
            async for message in websocket:
                await self._process_message(websocket, message, session)
        except ConnectionClosedOK:
            console.print(
                Panel.fit(
                    f"Client {client_address} disconnected cleanly",
                    title="Client disconnected",
                    style="bold blue",
                )
            )
        except ConnectionClosedError as exc:
            console.print(
                Panel.fit(
                    f"Client {client_address} disconnected with error: {exc}",
                    title="Client error",
                    style="bold red",
                )
            )
        except Exception as exc:
            console.print(
                Panel.fit(
                    f"Error handling client {client_address}: {exc}",
                    title="Server error",
                    style="bold red",
                )
            )
            logger.exception("Error in WebSocket handler")
        finally:
            await self._cleanup_client(client_key, session, translation_task, playback_task)

    async def _process_message(
        self, 
        websocket: WebSocketServerProtocol, 
        message: bytes | str,
        session: dict,
    ) -> None:
        """Process an incoming message from the client."""
        if isinstance(message, bytes):
            await self._handle_binary_message(websocket, message)
        elif isinstance(message, str):
            await self._handle_json_message(websocket, message, session)

    async def _handle_binary_message(
        self,
        websocket: WebSocketServerProtocol,
        message: bytes,
    ) -> None:
        """Handle a binary message from the client."""
        message_size = len(message)
        console.print(
            f"[cyan]Received binary message: {message_size} bytes[/cyan]"
        )
        await websocket.send(json.dumps({
            "status": "error",
            "message": "Binary messages not supported. Please use ACS JSON format."
        }))

    async def _handle_json_message(
        self,
        websocket: WebSocketServerProtocol,
        message: str,
        session: dict,
    ) -> None:
        """Handle a JSON message from the client."""
        try:
            data = json.loads(message)
            await self._process_acs_message(websocket, data, session)
        except json.JSONDecodeError as e:
            console.print(f"[red]Invalid JSON: {e}[/red]")
            await websocket.send(json.dumps({
                "status": "error",
                "message": "Invalid JSON format"
            }))
        except Exception as e:
            console.print(f"[red]Error processing message: {e}[/red]")
            logger.exception("Error in message processing")
            await websocket.send(json.dumps({
                "status": "error",
                "message": f"Processing error: {str(e)}"
            }))

    def _initialize_streaming_session(self, client_key: str) -> dict:
        """Initialize a streaming session with audio queue for continuous translation."""
        audio_queue: deque[bytes] = deque(maxlen=512)
        stop_streaming = threading.Event()
        
        # Create streaming AudioInput with both queue (for Voice Live) and stream (for SDK)
        # We initialize with default 16kHz format. If format changes, we might need to recreate stream,
        # but for now we assume 16kHz or rely on SDK's resampling if possible.
        stream_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=TARGET_SAMPLE_RATE, 
            bits_per_sample=TARGET_BITS_PER_SAMPLE, 
            channels=TARGET_CHANNELS
        )
        push_stream = speechsdk.audio.PushAudioInputStream(stream_format)
        
        audio_input = AudioInput(
            source_type=AudioSourceType.STREAM,
            config=speechsdk.audio.AudioConfig(stream=push_stream),
            stream=push_stream,
            _audio_queue=audio_queue,
            _stop_capture=stop_streaming,
        )
        
        session = {
            "audio_queue": audio_queue,
            "playback_queue": deque(maxlen=512),  # Separate queue for playback
            "stop_streaming": stop_streaming,
            "audio_input": audio_input,
            # Buffer for normalising incoming ACS frames to ~100ms 16 kHz mono chunks
            # before feeding them into the streaming pipeline (matches WAV/mic behaviour).
            "stream_buffer": bytearray(),
            "expected_sequence": 0,
            "participant_id": None,
            "audio_format": {
                "sample_rate": TARGET_SAMPLE_RATE,  # Default, will be updated from first chunk
                "channels": TARGET_CHANNELS,
                "bits_per_sample": TARGET_BITS_PER_SAMPLE,
            },
            "last_timestamp": None,
            # Logical 100ms chunks pushed into AudioInput (after resampling/aggregation)
            "chunk_count": 0,
            # Raw ACS frames received (before aggregation), used for resample logging/metrics
            "raw_chunk_count": 0,
            "bytes_received": 0,
            "translator": None,
            "format_initialized": False,  # Track if format was set from actual data
            "format_init_event": asyncio.Event(),  # Event to signal initialization
        }
        
        self._client_sessions[client_key] = session
        return session

    def _cleanup_session(self, session: dict) -> None:
        """Clean up a streaming session."""
        if session.get("stop_streaming"):
            session["stop_streaming"].set()
        if session.get("audio_input"):
            session["audio_input"].close()

    async def _cleanup_client(
        self,
        client_key: str,
        session: dict,
        translation_task: Optional[asyncio.Task],
        playback_task: Optional[asyncio.Task],
    ) -> None:
        """Clean up client connection and cancel tasks."""
        self._cleanup_session(session)
        if translation_task and not translation_task.done():
            translation_task.cancel()
            try:
                await translation_task
            except asyncio.CancelledError:
                pass
        if playback_task and not playback_task.done():
            playback_task.cancel()
            try:
                await playback_task
            except asyncio.CancelledError:
                pass
        if client_key in self._client_sessions:
            del self._client_sessions[client_key]

    def _validate_sequence(self, session: dict, sequence_number: int) -> None:
        """Validate sequence number and update expected sequence."""
        expected = session["expected_sequence"]
        if sequence_number < expected:
            console.print(
                f"[yellow]Out-of-order chunk: got {sequence_number}, expected {expected}[/yellow]"
            )
        elif sequence_number > expected:
            gap = sequence_number - expected
            console.print(
                f"[yellow]Missing {gap} chunk(s): expected {expected}, got {sequence_number}[/yellow]"
            )
        session["expected_sequence"] = sequence_number + 1

    async def _validate_audio_format(
        self,
        websocket: WebSocketServerProtocol,
        audio_data: dict,
        session: dict,
    ) -> bool:
        """Validate and store audio format. Returns True if error occurred."""
        sample_rate = audio_data.get("sampleRate", TARGET_SAMPLE_RATE)
        channels = audio_data.get("channels", TARGET_CHANNELS)
        bits_per_sample = audio_data.get("bitsPerSample", TARGET_BITS_PER_SAMPLE)
        format_type = audio_data.get("format", "pcm")

        if format_type != "pcm":
            console.print(f"[yellow]Unsupported format: {format_type}[/yellow]")
            await websocket.send(json.dumps({
                "status": "error",
                "message": f"Unsupported audio format: {format_type}"
            }))
            return True

        # Check format consistency - use format_initialized flag, not sample_rate value
        if session.get("format_initialized", False):
            # Format already initialized, check for changes
            if session["audio_format"]["sample_rate"] != sample_rate:
                console.print(
                    f"[yellow]Sample rate changed: {session['audio_format']['sample_rate']} -> {sample_rate}[/yellow]"
                )
                session["audio_format"]["sample_rate"] = sample_rate
            if session["audio_format"]["channels"] != channels:
                console.print(
                    f"[yellow]Channels changed: {session['audio_format']['channels']} -> {channels}[/yellow]"
                )
                session["audio_format"]["channels"] = channels
            if session["audio_format"]["bits_per_sample"] != bits_per_sample:
                console.print(
                    f"[yellow]Bits per sample changed: {session['audio_format']['bits_per_sample']} -> {bits_per_sample}[/yellow]"
                )
                session["audio_format"]["bits_per_sample"] = bits_per_sample
        else:
            # First chunk - store format from actual data
            session["audio_format"].update({
                "sample_rate": sample_rate,
                "channels": channels,
                "bits_per_sample": bits_per_sample,
            })
            session["format_initialized"] = True
            # Update AudioInput with the actual format so Voice Live uses it
            sample_width = bits_per_sample // 8
            session["audio_input"]._custom_format = (sample_rate, channels, sample_width)
            console.print(
                f"[cyan]Audio format initialized: {sample_rate}Hz, {channels}ch, {bits_per_sample}bit[/cyan]"
            )
            console.print(
                f"[dim]Note: Audio will be resampled to {TARGET_SAMPLE_RATE}Hz mono for translation[/dim]"
            )
            # Signal initialization immediately
            session.get("format_init_event", asyncio.Event()).set()
        return False

    async def _decode_audio(
        self,
        websocket: WebSocketServerProtocol,
        base64_audio: str,
    ) -> bytes | None:
        """Decode base64 audio. Returns None if error occurred."""
        try:
            audio_bytes = base64.b64decode(base64_audio)
            if not audio_bytes:
                console.print("[yellow]Decoded audio chunk is empty[/yellow]")
                return None
            return audio_bytes
        except Exception as e:
            console.print(f"[red]Base64 decode error: {e}[/red]")
            await websocket.send(json.dumps({
                "status": "error",
                "message": f"Base64 decode failed: {e}"
            }))
            return None

    def _resample_audio(self, audio_bytes: bytes, session: dict) -> bytes | None:
        """Resample and convert audio to mono 16kHz for translation service.
        
        Ensures output is:
        - 16kHz sample rate
        - Mono (1 channel)
        - 16-bit signed PCM
        - Little-endian byte order (required by Azure SDK)
        """
        # Get current format
        src_sample_rate = session["audio_format"]["sample_rate"]
        src_channels = session["audio_format"]["channels"]
        src_bits_per_sample = session["audio_format"]["bits_per_sample"]
        
        # Convert bytes to numpy array - explicitly use little-endian int16
        # Azure expects little-endian, and most WAV files are LE, but be explicit
        if src_bits_per_sample == 16:
            # Use little-endian int16: "<i2" = signed 16-bit integer, little-endian
            audio_array = np.frombuffer(audio_bytes, dtype="<i2")
        else:
            console.print(f"[yellow]Unsupported bits per sample: {src_bits_per_sample}[/yellow]")
            return None
        
        # Convert stereo to mono if needed
        if src_channels == 2:
            # Reshape to (samples, 2) and average the channels
            audio_array = audio_array.reshape(-1, 2)
            # Average channels (produces float64), then convert to int16
            audio_array = audio_array.mean(axis=1).astype("<i2")
        elif src_channels != 1:
            console.print(f"[yellow]Unsupported channel count: {src_channels}[/yellow]")
            return None
        
        # Resample if needed
        if src_sample_rate != TARGET_SAMPLE_RATE:
            audio_array = self._linear_resample(
                audio_array, src_sample_rate, TARGET_SAMPLE_RATE
            )
        
        # Ensure we have little-endian int16 before converting to bytes
        if audio_array.dtype != np.dtype("<i2"):
            audio_array = audio_array.astype("<i2")
        
        # Convert back to bytes (tobytes() preserves the dtype's byte order)
        resampled_audio_bytes = audio_array.tobytes()
        
        # Log resampling details for first few raw chunks
        raw_index = session.get("raw_chunk_count", 0)
        if raw_index < 3:
            console.print(
                f"[dim]Resampled chunk #{raw_index + 1}: "
                f"{len(audio_bytes)} bytes ({src_sample_rate}Hz, {src_channels}ch) → "
                f"{len(resampled_audio_bytes)} bytes ({TARGET_SAMPLE_RATE}Hz, {TARGET_CHANNELS}ch)[/dim]"
            )

        return resampled_audio_bytes

    @staticmethod
    def _linear_resample(
        audio_array: np.ndarray,
        src_sample_rate: int,
        target_sample_rate: int,
    ) -> np.ndarray:
        """Resample audio using linear interpolation.
        
        Returns little-endian int16 array suitable for Azure SDK.
        Values are clamped to int16 range to prevent overflow.
        """
        num_samples = len(audio_array)
        duration = num_samples / src_sample_rate
        target_num_samples = int(duration * target_sample_rate)

        # Create new time axis
        src_time = np.linspace(0, duration, num_samples, endpoint=False)
        target_time = np.linspace(0, duration, target_num_samples, endpoint=False)

        # Interpolate (np.interp returns float64)
        resampled_float = np.interp(target_time, src_time, audio_array.astype(np.float64))
        
        # Clamp to int16 range to prevent overflow/clipping
        resampled_float = np.clip(resampled_float, -32768, 32767)
        
        # Convert to little-endian int16 (required by Azure SDK)
        return resampled_float.astype("<i2")

    def _track_timestamp_from_string(self, timestamp: str, session: dict) -> None:
        """Track timestamp from ISO string and detect gaps."""
        if timestamp:
            if session["last_timestamp"]:
                try:
                    last_dt = datetime.fromisoformat(session["last_timestamp"].replace("Z", "+00:00"))
                    curr_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    gap = (curr_dt - last_dt).total_seconds()
                    if gap > 1.0:  # More than 1 second gap
                        console.print(f"[yellow]Large time gap: {gap:.2f}s[/yellow]")
                except Exception:
                    pass
            session["last_timestamp"] = timestamp

    async def _process_acs_message(
        self,
        websocket: WebSocketServerProtocol,
        data: dict,
        session: dict,
    ) -> None:
        """Process an ACS-format message and feed to streaming audio queue.
        
        Expects official ACS format: {"kind": "AudioData", "audioData": {...}}
        """
        # Step 1: Detect format and extract audio data
        kind = data.get("kind")

        # Handle end-of-stream signal
        if kind == "EndOfStream":
            console.print("[cyan]Received end-of-stream signal, closing audio input[/cyan]")
            # Close the audio input to trigger final commit in Voice Live
            if session.get("audio_input"):
                session["audio_input"].close()
            return

        # Official ACS format: kind: "AudioData"
        if kind == "AudioData":
            audio_data = data.get("audioData")
            if not audio_data:
                console.print("[red]Missing audioData field in official ACS format[/red]")
                await websocket.send(json.dumps({
                    "status": "error",
                    "message": "Missing audioData field"
                }))
                return
            
            # Extract fields from official format
            base64_audio = audio_data.get("data")
            participant_id = audio_data.get("participantRawID") or audio_data.get("participantId", "unknown")
            is_silent = audio_data.get("silent", False)
            timestamp = audio_data.get("timestamp")
            sequence_number = None  # Not present in official format
            
            # Skip silent chunks
            if is_silent:
                console.print("[dim]Skipping silent audio chunk[/dim]")
                await websocket.send(json.dumps({
                    "status": "skipped",
                    "reason": "silent"
                }))
                return
            
            # Check if format info is provided (optional in official format but needed for proper processing)
            # If not provided, use defaults
            if "sampleRate" in audio_data or "channels" in audio_data or "bitsPerSample" in audio_data:
                # Format info is provided, use it
                audio_format_data = {
                    "sampleRate": audio_data.get("sampleRate", TARGET_SAMPLE_RATE),
                    "channels": audio_data.get("channels", TARGET_CHANNELS),
                    "bitsPerSample": audio_data.get("bitsPerSample", TARGET_BITS_PER_SAMPLE),
                    "format": audio_data.get("format", "pcm"),
                }
            else:
                # No format info provided, use defaults
                audio_format_data = {
                    "sampleRate": TARGET_SAMPLE_RATE,
                    "channels": TARGET_CHANNELS,
                    "bitsPerSample": TARGET_BITS_PER_SAMPLE,
                    "format": "pcm",
                }
        else:
            # Unknown format
            console.print(f"[yellow]Ignoring unknown message format: kind={kind}[/yellow]")
            await websocket.send(json.dumps({
                "status": "ignored",
                "message": f"Unknown message format. Expected kind='AudioData'"
            }))
            return

        # Step 2: Validate required fields
        if not base64_audio:
            console.print("[red]Missing audio data field[/red]")
            await websocket.send(json.dumps({
                "status": "error",
                "message": "Missing audio data"
            }))
            return

        # Step 3: Store participant ID if not set
        if not session["participant_id"]:
            session["participant_id"] = participant_id
            console.print(f"[cyan]Participant ID: {participant_id}[/cyan]")

        # Step 4: Validate sequence (if present)
        if sequence_number is not None:
            self._validate_sequence(session, sequence_number)
        else:
            # Auto-increment sequence for official format
            session["expected_sequence"] += 1

        # Step 5: Validate and store audio format
        format_error = await self._validate_audio_format(websocket, audio_format_data, session)
        if format_error:
            return

        # Step 6: Decode base64 audio
        audio_bytes = await self._decode_audio(websocket, base64_audio)
        if audio_bytes is None:
            return

        # Step 7: Resample and convert audio to mono 16kHz for translation service
        resampled_audio_bytes = self._resample_audio(audio_bytes, session)
        if resampled_audio_bytes is None:
            return

        # Track raw bytes and frame count for diagnostics
        session["raw_chunk_count"] = session.get("raw_chunk_count", 0) + 1
        session["bytes_received"] += len(audio_bytes)

        # Step 7b: Aggregate resampled audio into ~100ms chunks (3200 bytes @ 16kHz mono 16-bit)
        # before feeding into the streaming pipeline so Voice Live sees the same temporal chunking
        # as the WAV/microphone test paths.
        stream_buffer: bytearray = session.get("stream_buffer")  # type: ignore[assignment]
        if stream_buffer is None:
            stream_buffer = bytearray()
            session["stream_buffer"] = stream_buffer

        stream_buffer.extend(resampled_audio_bytes)

        CHUNK_SIZE_BYTES = 3200  # ~100ms at 16kHz mono 16-bit
        produced_chunks = 0
        while len(stream_buffer) >= CHUNK_SIZE_BYTES:
            chunk = bytes(stream_buffer[:CHUNK_SIZE_BYTES])
            del stream_buffer[:CHUNK_SIZE_BYTES]
            # Use the write() method to feed both queue and SDK stream with normalised chunks
            session["audio_input"].write(chunk)
            session["chunk_count"] += 1
            produced_chunks += 1
        
        # Also add ORIGINAL audio to playback queue so user can hear what's received (if enabled)
        if self.play_input_audio:
            playback_queue = session.get("playback_queue")
            if playback_queue is not None:
                playback_queue.append(audio_bytes)  # Use original audio for playback

        # Log logical chunk reception periodically (post-aggregation)
        if produced_chunks > 0 and session["chunk_count"] % 10 == 0:
            console.print(
                f"[dim]Received {session['chunk_count']} chunks (~100ms each), "
                f"total raw bytes: {session['bytes_received']}[/dim]"
            )

        # Step 8: Track timestamp
        if timestamp:
            self._track_timestamp_from_string(timestamp, session)

        # Step 9: Send acknowledgment
        ack = {
            "status": "received",
            # Report logical chunks pushed into the streaming pipeline; this is more meaningful
            # for callers than the raw ACS frame count.
            "chunksReceived": session["chunk_count"],
        }
        if sequence_number is not None:
            ack["sequenceNumber"] = sequence_number
        await websocket.send(json.dumps(ack))

    async def _run_continuous_translation(
        self,
        websocket: WebSocketServerProtocol,
        session: dict,
    ) -> None:
        """Run continuous translation in streaming mode (like microphone)."""
        if not await self._wait_for_format_init(session):
                return

        fmt = session["audio_format"]
        console.print(
            f"[bold cyan]Starting continuous translation stream: "
            f"{fmt['sample_rate']}Hz, {fmt['channels']}ch, {fmt['bits_per_sample']}bit[/bold cyan]"
        )

        # Create translator once per session (maintains context)
        translator = create_translator(
            self.settings,
            from_language=self.from_language,
            to_languages=self.to_languages,
            voice_name=self.voice,
            output_audio_path=None,  # Don't save output for WebSocket mode
            terminate_on_completion=False,  # Continuous streaming
            local_audio_playback=self.play_azure_audio,
        )
        session["translator"] = translator

        # Run translation in executor (it's synchronous but long-running)
        loop = asyncio.get_event_loop()
        on_translation_event = self._create_event_callback(websocket, loop, session)
        
        try:
            # The translator.translate() will stream from audio_input.get_audio_chunks()
            # which reads from our audio_queue
            console.print("[dim]Waiting for audio chunks from WebSocket...[/dim]")
            outcome = await loop.run_in_executor(
                None,
                lambda: translator.translate(session["audio_input"], on_event=on_translation_event),
            )

            await self._send_translation_result(websocket, outcome)

        except Exception as e:
            console.print(f"[red]Error in continuous translation: {e}[/red]")
            logger.exception("Error in continuous translation")
            await websocket.send(json.dumps({
                "status": "error",
                "message": f"Translation processing failed: {str(e)}"
            }))

    async def _wait_for_format_init(self, session: dict) -> bool:
        """Wait for audio format to be initialized. Returns False if timeout or stopped."""
        max_wait = 30  # Wait up to 30 seconds for first chunk
        
        # Fast path if already initialized
        if session.get("format_initialized", False):
            return True
            
        # Wait for event with timeout
        format_event = session.get("format_init_event")
        if not format_event:
             # Fallback for older sessions (shouldn't happen)
             waited = 0
             while not session.get("format_initialized", False):
                await asyncio.sleep(0.1)
                waited += 1
                if session["stop_streaming"].is_set() or waited >= max_wait * 10:
                    if waited >= max_wait * 10:
                        console.print("[yellow]Timeout waiting for audio format initialization (fallback)[/yellow]")
                    return False
             return True
             
        try:
            await asyncio.wait_for(format_event.wait(), timeout=max_wait)
            return True
        except asyncio.TimeoutError:
            console.print("[yellow]Timeout waiting for audio format initialization[/yellow]")
            return False

    def _create_event_callback(
        self,
        websocket: WebSocketServerProtocol,
        loop: asyncio.AbstractEventLoop,
        session: dict,
    ):
        """Create callback to forward translation events to the WebSocket client."""

        def on_translation_event(event: dict) -> None:
            """Forward translation events to the WebSocket client.

            This runs in the executor thread, so we need to schedule the send
            on the main event loop using run_coroutine_threadsafe.
            """
            # If the client WebSocket or event loop is already closed, skip sending.
            if websocket.closed or loop.is_closed():
                console.print(f"Client Closed - websocket_closed:{websocket.closed} loop_closed: {loop.is_closed}")
                return

            # Check if event is already in ACS format (from Live Interpreter)
            # If so, forward it directly without conversion
            if event.get("kind") == "AudioData":
                # Live Interpreter already emits events in ACS format
                # Update participant ID if available from session
                if "audioData" in event:
                    participant_id = session.get("participant_id") or event["audioData"].get("participantRawID", "live_interpreter")
                    event["audioData"]["participantRawID"] = participant_id
                    audio_size = len(event["audioData"].get("data", ""))
                    console.print(f"[dim]Forwarding synthesized audio to client: {audio_size} bytes (base64)[/dim]")
                
                payload = json.dumps(event)
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        websocket.send(payload),
                        loop,
                    )
                    future.result(timeout=1.0)
                except Exception as e:
                    if isinstance(e, (ConnectionClosedOK, ConnectionClosedError)) or "Event loop is closed" in str(e):
                        logger.debug(
                            "Dropping translation event after client disconnect/loop close: %s",
                            e,
                        )
                        return
                    console.print(f"[yellow]Failed to send ACS audio event to client: {e}[/yellow]")
                return

            # Convert Voice Live audio deltas into ACS-style AudioData payloads so the
            # same socket can be used to play translated audio back to the caller.
            payload: str
            event_type = event.get("type")

            # Debug: log all events in testing mode
            if self.testing_mode:
                console.print(f"[dim] - Event callback received: type={event_type}[/dim]")

            if event_type == "translation.audio_delta":
                audio_b64_in = event.get("audio")
                if not audio_b64_in:
                    return

                # Decode translation audio, normalise to TARGET_SAMPLE_RATE mono pcm16
                # so that ACS playback uses the correct speed and pitch regardless of
                # the model's native output rate (often 24 kHz).
                try:
                    audio_bytes = base64.b64decode(audio_b64_in)
                except Exception:
                    return

                sample_rate = int(event.get("sample_rate") or TARGET_SAMPLE_RATE)
                channels = int(event.get("channels") or TARGET_CHANNELS)
                bits_per_sample = int(event.get("bits_per_sample") or TARGET_BITS_PER_SAMPLE)

                # Only pcm16 mono is expected from Voice Live, but resample if rate differs.
                if bits_per_sample != 16:
                    console.print(
                        f"[yellow]Unexpected bits_per_sample from translator: {bits_per_sample}[/yellow]"
                    )
                    return

                audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
                if channels == 2:
                    # Downmix stereo to mono if it ever occurs.
                    audio_array = audio_array.reshape(-1, 2).mean(axis=1).astype(np.int16)
                elif channels != 1:
                    console.print(
                        f"[yellow]Unexpected channel count from translator: {channels}[/yellow]"
                    )
                    return

                if sample_rate != TARGET_SAMPLE_RATE and audio_array.size:
                    audio_array = self._linear_resample(
                        audio_array, sample_rate, TARGET_SAMPLE_RATE
                    )
                    sample_rate = TARGET_SAMPLE_RATE

                audio_bytes_out = audio_array.tobytes()
                audio_b64 = base64.b64encode(audio_bytes_out).decode("ascii")

                # Reuse the participant ID we saw on the inbound audio unless a specific
                # bot identity is configured upstream.
                participant_id = session.get("participant_id") or "unknown"
                timestamp = datetime.utcnow().isoformat() + "Z"

                acs_message = {
                    "kind": "AudioData",
                    "audioData": {
                        "timestamp": timestamp,
                        "participantRawID": participant_id,
                        "data": audio_b64,
                        "silent": False,
                        # Format fields mirror the inbound ACS schema so that a single
                        # WebSocket contract can be used for both directions.
                        "sampleRate": sample_rate,
                        "channels": channels,
                        "bitsPerSample": bits_per_sample,
                        "format": "pcm",
                    },
                }
                payload = json.dumps(acs_message)
            elif event_type == "translation.text_delta":
                # In testing mode, forward text transcript events
                if not self.testing_mode:
                    return  # Skip text deltas unless in testing mode

                console.print(f"[bold yellow]TESTING MODE: Sending text delta: {event.get('delta', '')}[/bold yellow]")
                payload = json.dumps(event)
            elif event_type == "translation.complete":
                # Complete translation event from Live Interpreter (when utterance is recognized)
                # This provides real-time interpreter behavior - translation appears as soon as speaker finishes
                console.print(
                    f"[bold green]Translation complete: {event.get('language', 'unknown')} - "
                    f"{event.get('text', '')[:50]}...[/bold green]"
                )
                payload = json.dumps(event)
            else:
                # Other non-audio events are forwarded as-is
                payload = json.dumps(event)

            try:
                # Schedule the send on the main event loop
                future = asyncio.run_coroutine_threadsafe(
                    websocket.send(payload),
                    loop,
                )
                # Wait for it to complete (with timeout to avoid blocking)
                future.result(timeout=1.0)
            except Exception as e:  # pragma: no cover - defensive logging
                # Suppress noisy errors once the connection or loop is shutting down.
                if isinstance(e, (ConnectionClosedOK, ConnectionClosedError)) or "Event loop is closed" in str(e):
                    logger.debug(
                        "Dropping translation event after client disconnect/loop close: %s",
                        e,
                    )
                    return
                console.print(f"[yellow]Failed to send event to client: {e}[/yellow]")

        return on_translation_event

    async def _send_translation_result(
        self,
        websocket: WebSocketServerProtocol,
        outcome,
    ) -> None:
        """Send final translation result back to client."""
        # Print translation results for debugging
        console.print("\n[bold cyan]Translation Result:[/bold cyan]")
        console.print(f"  Recognized text: {outcome.recognized_text or '(none)'}")
        console.print(f"  Translations: {outcome.translations or {}}")
        console.print(f"  Success: {outcome.success}")
        if outcome.error_details:
            console.print(f"  Error: {outcome.error_details}")

        response = {
            "status": "processed",
            "recognized_text": outcome.recognized_text,
            "translations": outcome.translations,
            "success": outcome.success,
        }
        if outcome.error_details:
            response["error"] = outcome.error_details

        await websocket.send(json.dumps(response))

        if outcome.success:
            console.print("[green]Translation stream completed successfully[/green]")
        else:
            console.print(f"[red]Translation stream failed: {outcome.error_details}[/red]")

    async def _play_received_audio(self, session: dict) -> None:
        """Play back received audio chunks so user can hear what's being received."""
        console.print("[dim]Playback task started, waiting for audio format...[/dim]")
        
        # Wait for audio format to be initialized
        if not await self._wait_for_format_init(session):
             console.print("[yellow]Playback task timeout waiting for audio format[/yellow]")
             return

        fmt = session["audio_format"]
        playback_queue = session.get("playback_queue")
        
        if playback_queue is None:
            console.print("[red]ERROR: Playback queue not initialized![/red]")
            return
        
        console.print(
            f"[dim]Playback task ready: format={fmt['sample_rate']}Hz/{fmt['channels']}ch, "
            f"queue_size={len(playback_queue)}[/dim]"
        )

        audio_output_stream = self._initialize_audio_output(fmt)
        if audio_output_stream is None:
            return

        try:
            await self._playback_loop(session, playback_queue, fmt, audio_output_stream)
        finally:
            self._cleanup_audio_output(audio_output_stream)

    def _initialize_audio_output(self, fmt: dict):
        """Initialize sounddevice audio output stream."""
        try:
            import sounddevice as sd
            import numpy as np
            
            sample_rate = fmt["sample_rate"]
            channels = fmt["channels"]
            
            console.print(f"[dim]Initializing sounddevice: {sample_rate}Hz, {channels}ch[/dim]")
            
            audio_output_stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype=np.int16,
                blocksize=sample_rate // 10,  # ~100ms chunks
            )
            audio_output_stream.start()
            
            # Verify stream is active
            if not audio_output_stream.active:
                console.print("[red]ERROR: Audio output stream started but not active![/red]")
                audio_output_stream.close()
                return None
                
            console.print(
                f"[bold cyan]Audio playback enabled: {sample_rate}Hz, {channels}ch, "
                f"active={audio_output_stream.active}[/bold cyan]"
            )
            return audio_output_stream
        except ImportError as e:
            console.print(f"[red]sounddevice not available: {e}. Audio playback disabled.[/red]")
            return None
        except Exception as e:
            console.print(f"[red]Could not initialize audio playback: {e}[/red]")
            logger.exception("Audio playback initialization error")
            return None

    async def _playback_loop(
        self,
        session: dict,
        playback_queue: deque,
        fmt: dict,
        audio_output_stream,
    ) -> None:
        """Main playback loop."""
        import numpy as np
        chunks_played = 0
        empty_iterations = 0
        
        console.print("[dim]Starting playback loop...[/dim]")
        
        while not session["stop_streaming"].is_set():
            # Check if stream is still active
            if audio_output_stream and not audio_output_stream.active:
                console.print("[yellow]Audio output stream became inactive, stopping playback[/yellow]")
                break
            
            if len(playback_queue) > 0:
                empty_iterations = 0
                chunk = playback_queue.popleft()
                if chunk and len(chunk) > 0 and audio_output_stream:
                    try:
                        # Convert bytes to numpy array (16-bit PCM)
                        audio_array = np.frombuffer(chunk, dtype=np.int16)
                        
                        if audio_array.size == 0:
                            console.print("[yellow]Empty audio array from chunk[/yellow]")
                            continue
                        
                        # Reshape for sounddevice: needs to be 2D (samples, channels)
                        # For mono audio, reshape to (samples, 1)
                        if fmt["channels"] == 1:
                            if len(audio_array.shape) == 1:
                                audio_array = audio_array.reshape(-1, 1)
                        # For stereo, ensure it's (samples, 2)
                        elif fmt["channels"] == 2:
                            if len(audio_array.shape) == 1:
                                # For stereo, we need to interleave or reshape correctly
                                # Assuming interleaved stereo in the bytes
                                audio_array = audio_array.reshape(-1, 2)
                        
                        # Write to audio output stream
                        audio_output_stream.write(audio_array)
                        chunks_played += 1
                        
                        # Log first few chunks and periodically
                        if chunks_played <= 5 or chunks_played % 20 == 0:
                            console.print(
                                f"[dim]✓ Played chunk #{chunks_played}: "
                                f"size={len(chunk)} bytes, shape={audio_array.shape}, "
                                f"queue_remaining={len(playback_queue)}[/dim]"
                            )
                    except Exception as e:
                        # Log playback errors with full details
                        console.print(f"[red]Playback error on chunk #{chunks_played}: {e}[/red]")
                        logger.exception("Playback error details")
                        # Continue playing other chunks
            else:
                empty_iterations += 1
                # Log if queue has been empty for a while (might indicate an issue)
                if empty_iterations == 100:  # 1 second of empty queue
                    console.print(
                        f"[dim]Playback queue empty for 1s, waiting for chunks... "
                        f"(played {chunks_played} chunks so far)[/dim]"
                    )
                    empty_iterations = 0  # Reset counter
                await asyncio.sleep(0.01)  # Small delay when queue is empty

    @staticmethod
    def _cleanup_audio_output(audio_output_stream) -> None:
        """Clean up audio output stream."""
        if audio_output_stream:
            try:
                audio_output_stream.stop()
                audio_output_stream.close()
            except Exception:
                pass
        console.print("[dim]Audio playback stopped[/dim]")

    async def start(self) -> None:
        """Start the WebSocket server."""
        server_info = f"ws://{self.host}:{self.port}"
        console.print(
            Panel.fit(
                f"Starting WebSocket server on {server_info}\n"
                f"From language: {self.from_language}\n"
                f"To languages: {', '.join(self.to_languages)}\n"
                f"Voice: {self.voice or 'None'}\n"
                f"Testing mode: {self.testing_mode}",
                title="WebSocket Server",
                style="bold magenta",
            )
        )

        async with websockets.serve(
            self._handle_client,
            self.host,
            self.port,
        ):
            console.print(f"[bold green]WebSocket server running on {server_info}[/bold green]")
            console.print("[yellow]Press Ctrl+C to stop the server[/yellow]")
            await asyncio.Future()  # Run forever


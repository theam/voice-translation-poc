"""Voice Live API integration via WebSockets."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import urlencode, urlparse, urlunparse

import azure.cognitiveservices.speech as speechsdk
import numpy as np
import websockets
from rich.console import Console
from rich.panel import Panel

from .audio import AudioInput
from .config import SpeechServiceSettings
from .models import TranslationOutcome

console = Console()

SUPPORTED_VOICE_LIVE_VOICES = {
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
}


@dataclass
class VoiceLiveConfig:
    """Runtime configuration for Voice Live sessions."""

    websocket_url: str
    api_key: str
    from_language: str
    to_languages: Iterable[str]
    voice_name: Optional[str]
    sample_rate_hz: int
    channels: int
    deployment: Optional[str]
    output_sample_rate_hz: int
    commit_interval: int
    silence_chunks: int
    force_commit_chunks: int


class VoiceLiveTranslator:
    """Translate audio using Azure Voice Live API."""

    def __init__(
        self,
        settings: SpeechServiceSettings,
        *,
        from_language: str,
        to_languages: Iterable[str],
        voice_name: Optional[str],
        output_audio_path: Optional[Path],
        terminate_on_completion: bool = False,
        local_audio_playback: bool = False,
    ) -> None:
        self.settings = settings
        self.from_language = from_language
        self.to_languages = tuple(to_languages)
        self.voice_name = self._resolve_voice_name(voice_name or settings.voice_live_voice)
        self.output_audio_path = output_audio_path
        self.translation_instruction = self._build_instruction()
        self._terminate_on_completion = terminate_on_completion
        self._local_audio_playback = local_audio_playback

        if not self.to_languages:
            raise ValueError("At least one target language must be specified.")

    def translate(
        self, 
        audio_input: AudioInput,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> TranslationOutcome:
        if audio_input.is_file:
            source_path = audio_input.source_path
            if source_path is None:
                raise ValueError("File path is None")
            suffix = source_path.suffix.lower()
            if suffix != ".wav":
                raise ValueError(
                    "Voice Live currently supports WAV input only. "
                    "Please convert MP3/other formats to 16 kHz mono WAV."
                )

            audio_bytes, sample_rate, channels = self._load_wav(source_path)
            console.print(f"Loaded WAV {source_path}, bytes={len(audio_bytes)}, sr={sample_rate}, channels={channels}")
            config = self._build_config(sample_rate=sample_rate, channels=channels)
            is_streaming = False
        elif audio_input.is_microphone or audio_input.is_stream:
            sample_rate, channels, sample_width = audio_input.get_audio_format()
            source_type_name = "microphone" if audio_input.is_microphone else "stream"
            console.print(
                f"[bold cyan]Streaming from {source_type_name}: sr={sample_rate}Hz, "
                f"channels={channels}, width={sample_width} bytes[/bold cyan]"
            )
            config = self._build_config(sample_rate=sample_rate, channels=channels)
            is_streaming = True
            audio_bytes = None  # Will be streamed
        else:
            raise ValueError(f"Unsupported audio input type: {audio_input.source_type}")

        console.print(
            Panel.fit(
                f"Voice Live config\n"
                f"- websocket: {config.websocket_url}\n"
                f"- model: {self.settings.voice_live_model}\n"
                f"- region: {self.settings.service_region}\n"
                f"- deployment: {config.deployment}\n"
                f"- turn_detection: enabled (server-side VAD)",
                title="Voice Live debug",
                style="bold blue",
            )
        )

        try:
            outcome = asyncio.run(self._dispatch(audio_input, audio_bytes, config, is_streaming, on_event))
        except Exception as exc:  # pragma: no cover - safeguard for unexpected runtime issues
            message = f"{exc.__class__.__name__}: {exc}" if str(exc) else repr(exc)
            console.print(Panel(message, title="Voice Live error", style="bold red"))
            return TranslationOutcome(
                recognized_text=None,
                translations={},
                result_reason=speechsdk.ResultReason.Canceled,
                error_details=message,
            )

        if outcome.audio_output_path is None and self.output_audio_path:
            synth_audio = getattr(outcome, "_synth_audio", None)
            if synth_audio:
                outcome.audio_output_path = self._write_wav(
                    audio_bytes=synth_audio,
                    sample_rate=config.output_sample_rate_hz,
                    channels=1,
                    target_path=self.output_audio_path,
                )
                delattr(outcome, "_synth_audio")

        return outcome

    async def _dispatch(
        self,
        audio_input: AudioInput,
        audio_bytes: Optional[bytes],
        config: VoiceLiveConfig,
        is_streaming: bool,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> TranslationOutcome:
        headers = {
            "api-key": config.api_key,
            "Ocp-Apim-Subscription-Key": config.api_key,
            "x-ms-client-request-id": str(uuid.uuid4()),
            "Authorization": f"Bearer {config.api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        console.print(Panel.fit("Connecting to Voice Live...", style="bold cyan"))

        async with websockets.connect(
            config.websocket_url,
            extra_headers=headers,
            max_size=None,
            ping_interval=None,
        ) as ws:
            # Wrap websocket for logging
            from .websocket_logger import WebSocketLogger
            websocket = WebSocketLogger(ws, log_file="voice_live_messages.log", log_dir="logs")

            await self._configure_session(websocket, config)
            
            if is_streaming:
                # For streaming microphone: run audio streaming and response reading concurrently
                # Use shared flags to coordinate shutdown and response state
                streaming_done = asyncio.Event()
                response_in_progress = asyncio.Event()  # Track if a response is being processed
                commit_ack_queue: asyncio.Queue[asyncio.Future] = asyncio.Queue()
                
                async def stream_with_cleanup():
                    try:
                        await self._stream_audio(
                            websocket,
                            audio_input,
                            audio_bytes,
                            config,
                            is_streaming,
                            response_in_progress,
                            commit_ack_queue,
                        )
                    except KeyboardInterrupt:
                        console.print("\n[bold yellow]Interrupted by user[/bold yellow]")
                    finally:
                        streaming_done.set()
                
                streaming_task = asyncio.create_task(stream_with_cleanup())
                responses_task = asyncio.create_task(
                    self._read_responses(
                        websocket,
                        config,
                        play_audio=self._local_audio_playback,
                        streaming_done=streaming_done,
                        response_in_progress=response_in_progress,
                        commit_ack_queue=commit_ack_queue,
                        on_event=on_event,
                    )
                )
                
                # Wait for streaming to complete
                await streaming_task
                
                # Give responses a moment to finish processing
                await asyncio.sleep(2)
                
                # Cancel response reading if still running
                if not responses_task.done():
                    responses_task.cancel()
                    try:
                        await responses_task
                    except asyncio.CancelledError:
                        pass
                
                # Get the outcome
                if responses_task.done():
                    try:
                        return responses_task.result()
                    except Exception as e:
                        console.print(f"[yellow]Response task error: {e}[/yellow]")
                
                # Fallback outcome
                return TranslationOutcome(
                    recognized_text=None,
                    translations={},
                    result_reason=speechsdk.ResultReason.Canceled,
                    error_details="Streaming completed",
                )
            else:
                # For file input: stream first, then read responses
                await self._stream_audio(websocket, audio_input, audio_bytes, config, is_streaming)
                return await self._read_responses(websocket, config, play_audio=self._local_audio_playback, on_event=on_event)

    def _build_instruction(self) -> str:
        return """

You are a **real-time bilingual interpreter**, not a chatbot.  
Your ONLY function is to **detect the language of each spoken segment (English ↔ Spanish) and translate it literally into the other language**, preserving the original order.

## Core Translation Rules
- **All Spanish → English.**  
- **All English → Spanish.**  
- Never output text in the same language it was spoken.  
- Maintain the **exact order** of segments.  
- Translate **every question, command, or emotionally charged line** exactly as content — **never treat it as addressed to you**.

**Example rule:**  
If the user says “¿Cuál es el nombre del antibiótico?”, you MUST translate it to English (“What is the name of the antibiotic?”) and NEVER answer it as if the question is for you.

## Hard Output Constraints
- Output **only the translated text**.  
- **Absolutely forbidden:**  
  - Any explanation, apology, chatbot response, suggestion, warning, question, greeting, system message, or meta-text.  
  - Any sentence beginning with or containing:  
    - “I’m sorry…”  
    - “I can only provide translation…”  
    - “Let me know…”  
    - “I cannot answer that…”  
    - “No content detected / No audio / Only noise…”  
  - ANY attempt to answer questions or continue the conversation.

If you detect a question in the input, you **must translate the question**, NEVER answer it.

## Silence / Noise Handling
If there is **no recognizable linguistic content** (silence, coughs, background noise, breathing, filler like “uh/um/eh”), produce **an empty string**.  
Do not describe silence or noise.

## Behavior Restrictions (Very Strong)
- **NEVER behave like a chatbot.**  
- **NEVER interpret any sentence, question, or request as being directed at you.**  
- Treat EVERY piece of speech strictly as content to translate.  
- **NEVER produce new content**, speculations, clarifications, expansions, or advice (including medical advice).  
- **NEVER reference yourself**, your abilities, limitations, audio quality, or translation role.

## Final Rule
- **If there is clear speech → translate literally into the other language and output only that.**  
- **If there is no speech → output an empty string.**

        """

    def _resolve_voice_name(self, voice_name: Optional[str]) -> Optional[str]:
        if not voice_name:
            return None
        normalised = voice_name.strip()
        if normalised not in SUPPORTED_VOICE_LIVE_VOICES:
            console.print(
                Panel.fit(
                    f"Voice '{normalised}' is not supported by Voice Live. "
                    "Falling back to the default voice.",
                    style="bold yellow",
                )
            )
            return None
        return normalised

    async def _configure_session(
        self,
        websocket: websockets.WebSocketClientProtocol,
        config: VoiceLiveConfig,
    ) -> None:
        session_payload = {
            "type": "session.update",
            "session": {
                "instructions": self.translation_instruction,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "modalities": ["text", "audio"],
                "temperature": 0.6, # SDK minimum is 0.6 - Errors if less: decimal below minimum value. Expected a value >= 0.6

                "turn_detection": { 
                    "type": "server_vad", 
                    "threshold": 0.5, 
                    "prefix_padding_ms": 300, 
                    "silence_duration_ms": 600, 
                    "create_response": True, 
                    "interrupt_response": False,
                    "idle_timeout_ms": 5000 # SDK minimum is 5000 - timeout for the server to trigger a commit for the last chunks in buffer and no turn detected
                }, 

                "input_audio_transcription": None, # tell the server to also return transcripts
            },
        }

        if self.voice_name:
            session_payload["session"]["voice"] = self.voice_name

        console.log(f"[dim]Session instructions: {self.translation_instruction}[/dim]")
        await websocket.send(json.dumps(session_payload))

    async def _stream_audio(
        self,
        websocket: websockets.WebSocketClientProtocol,
        audio_input: AudioInput,
        audio_bytes: Optional[bytes],
        config: VoiceLiveConfig,
        is_streaming: bool,
        response_in_progress: Optional[asyncio.Event] = None,
        commit_ack_queue: Optional[asyncio.Queue[asyncio.Future]] = None,
    ) -> None:
        if is_streaming:
            # Stream microphone input in real-time
            # Turn detection is handled by the service via session.update configuration
            console.print("[bold yellow]Recording from microphone. Press Ctrl+C to stop...[/bold yellow]")
            chunk_count = 0
            commit_audio_buffer = bytearray()
            outstanding_buffer = False
            
            try:
                for chunk in audio_input.get_audio_chunks():
                    if chunk:
                        chunk_count += 1
                        
                        if chunk_count % 100 == 0:  # Log every 100 chunks
                            console.log(f"Voice Live streaming chunk #{chunk_count} ({len(chunk)} bytes)")
                        
                        # Append chunk to buffer for final commit
                        commit_audio_buffer.extend(chunk)
                        
                        # Send chunk to service - turn detection will handle commits automatically
                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "input_audio_buffer.append",
                                    "audio": base64.b64encode(chunk).decode("ascii"),
                                }
                            )
                        )
                        outstanding_buffer = True
                        
                        # Small delay to prevent overwhelming the WebSocket
                        await asyncio.sleep(0.002)
            except KeyboardInterrupt:
                console.print("\n[bold yellow]Stopping microphone capture...[/bold yellow]")
                # Signal the audio input to stop capturing
                if hasattr(audio_input, '_stop_capture') and audio_input._stop_capture:
                    audio_input._stop_capture.set()
            except Exception as e:
                console.print(f"[bold red]Error during microphone streaming: {e}[/bold red]")
                # Signal the audio input to stop capturing
                if hasattr(audio_input, '_stop_capture') and audio_input._stop_capture:
                    audio_input._stop_capture.set()
                raise
            
            # Final commit when streaming stops (if there is buffered audio)
            if outstanding_buffer and commit_audio_buffer:
                # Avoid overlapping responses: wait for any in‑flight response to
                # finish before issuing the final commit/response.create pair.
                if response_in_progress:
                    # Hard upper bound so we don't hang forever if the
                    # server never sends a completion event.
                    loop = asyncio.get_running_loop()
                    start = loop.time()
                    while response_in_progress.is_set() and (loop.time() - start) < 5.0:
                        await asyncio.sleep(0.01)
                    if response_in_progress.is_set():
                        console.print(
                            "[yellow]Timed out waiting for previous response to finish "
                            "before final commit; skipping final commit to avoid "
                            "conversation_already_has_active_response[/yellow]"
                        )
                        return

                ack_future: Optional[asyncio.Future] = None
                if commit_ack_queue is not None:
                    loop = asyncio.get_running_loop()
                    ack_future = loop.create_future()
                    await commit_ack_queue.put(ack_future)
                
                commit_payload = bytes(commit_audio_buffer)
                await websocket.send(json.dumps({"type": "input_audio_buffer.commit"}))
                commit_duration = (
                    len(commit_payload) / (config.sample_rate_hz * config.channels * 2)
                    if commit_payload
                    else 0.0
                )
                console.log(
                    f"[dim]Final commit audio bytes={len(commit_payload)} dur={commit_duration:.2f}s[/dim]"
                )

                if ack_future is not None:
                    try:
                        event = await asyncio.wait_for(ack_future, timeout=5.0)
                        ack_item_id = event.get("item_id") if isinstance(event, dict) else None
                        if ack_item_id:
                            console.log(f"[dim]input_audio_buffer.committed ack item_id={ack_item_id}[/dim]")
                        await websocket.send(json.dumps({"type": "input_audio_buffer.clear"}))
                        console.log("[dim]Cleared input audio buffer after final commit[/dim]")
                    except asyncio.TimeoutError:
                        console.print(
                            "[yellow]Timed out waiting for input_audio_buffer.committed acknowledgement (final)[/yellow]"
                        )
                
                response_payload: dict[str, object] = {
                    "instructions": self.translation_instruction,
                    "modalities": ["text", "audio"],
                }
                if response_in_progress:
                    response_in_progress.set()
                await websocket.send(
                    json.dumps(
                        {
                            "type": "response.create",
                            "response": response_payload,
                        }
                    )
                )
                console.log("Voice Live response.create dispatched (final)")
        else:
            # Stream file input
            if audio_bytes is None:
                raise ValueError("audio_bytes is required for file input")
            chunk_size = 3200  # approx 100ms @ 16kHz mono 16-bit
            for chunk_start in range(0, len(audio_bytes), chunk_size):
                chunk = audio_bytes[chunk_start : chunk_start + chunk_size]
                console.log(f"Voice Live audio chunk bytes={len(chunk)} start={chunk_start}")
                await websocket.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(chunk).decode("ascii"),
                        }
                    )
                )

        if not is_streaming:
            await websocket.send(json.dumps({"type": "input_audio_buffer.commit"}))
            console.log("Voice Live audio stream committed")

            response_payload: dict[str, object] = {
                "instructions": self.translation_instruction,
                "modalities": ["text", "audio"],
            }
            await websocket.send(
                json.dumps(
                    {
                        "type": "response.create",
                        "response": response_payload,
                    }
                )
            )
            console.log("Voice Live response.create dispatched")

    async def _read_responses(
        self,
        websocket: websockets.WebSocketClientProtocol,
        config: VoiceLiveConfig,
        play_audio: bool = True,
        streaming_done: Optional[asyncio.Event] = None,
        response_in_progress: Optional[asyncio.Event] = None,
        commit_ack_queue: Optional[asyncio.Queue[asyncio.Future]] = None,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> TranslationOutcome:
        recognized_segments: list[str] = []
        text_segments: list[str] = []
        audio_chunks: list[bytes] = []
        # Track all server-side conversation item IDs so we can clear them
        # after each completed response, keeping the model effectively
        # stateless between turns.
        conversation_item_ids: set[str] = set()
        error_details: Optional[str] = None
        audio_transcript: Optional[str] = None

        # Set up audio playback if requested
        audio_output_stream = None
        if play_audio:
            try:
                import sounddevice as sd
                import numpy as np
                audio_output_stream = sd.OutputStream(
                    samplerate=config.output_sample_rate_hz,
                    channels=1,
                    dtype=np.int16,
                    blocksize=config.output_sample_rate_hz // 10,  # ~100ms chunks
                )
                audio_output_stream.start()
                console.print("[bold cyan]Local audio playback enabled[/bold cyan]")
            except Exception as e:
                console.print(f"[yellow]Could not initialize audio playback: {e}[/yellow]")
                audio_output_stream = None
        else:
            console.print("[dim]Local audio playback disabled[/dim]")

        console.print("[bold green]Listening for Azure responses...[/bold green]")
        try:
            while True:
                # If streaming is done, wait a bit longer then exit
                if streaming_done and streaming_done.is_set():
                    # Wait for any remaining messages with timeout
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                    except asyncio.TimeoutError:
                        console.print("[dim]No more responses, closing...[/dim]")
                        break
                else:
                    try:
                        message = await websocket.recv()
                    except websockets.ConnectionClosedOK:
                        break

                event = json.loads(message)
                event_type = event.get("type")

                if event_type == "input_audio_buffer.committed" and commit_ack_queue is not None:
                    ack_future: Optional[asyncio.Future]
                    try:
                        ack_future = commit_ack_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        ack_future = None
                    if ack_future and not ack_future.done():
                        ack_future.set_result(event)
                    # Capture the committed audio item_id so we can delete it
                    # later and avoid the model reusing long-term context.
                    item_id = event.get("item_id")
                    if isinstance(item_id, str):
                        conversation_item_ids.add(item_id)
                    continue
                
                # Track any additional conversation items created by the
                # service (e.g. output items) so they can be removed after the
                # response completes.
                if event_type in {"conversation.item.created", "response.output_item.added"}:
                    item = event.get("item") or event.get("output_item") or {}
                    if isinstance(item, dict):
                        item_id = item.get("id")
                        if isinstance(item_id, str):
                            conversation_item_ids.add(item_id)
                
                # Mark that a response has started
                if event_type == "response.created":
                    if response_in_progress:
                        response_in_progress.set()
                    text_segments.clear()
                    audio_transcript = None
                    # Emit event to callback
                    if on_event:
                        on_event({"type": "translation.started"})
                
                # Log events more prominently (but skip audio.delta to reduce noise)
                if event_type == "response.audio.delta":
                    # Don't log audio delta events - too verbose
                    pass
                elif event_type in {"response.output_text.delta", "response.audio_transcript.delta"}:
                    # Log text deltas inline
                    delta = event.get("delta", "")
                    if delta:
                        console.print(f"[dim]→ {delta}[/dim]", end="")
                        # Emit text delta event to callback
                        if on_event:
                            on_event({"type": "translation.text_delta", "delta": delta})
                else:
                    # Log other events prominently
                    console.print(f"[bold blue]Voice Live:[/bold blue] {event_type}")
                    if event_type not in {"response.output_text.delta", "response.audio_transcript.delta"}:
                        # Only show transcript field if it exists in the event structure
                        def _extract_transcript(value):
                            """Recursively search for 'transcript' field in the event structure."""
                            if isinstance(value, dict):
                                # Check if 'transcript' key exists at this level
                                if "transcript" in value:
                                    return value["transcript"]
                                # Recursively search in nested structures
                                for val in value.values():
                                    result = _extract_transcript(val)
                                    if result is not None:
                                        return result
                            elif isinstance(value, list):
                                for item in value:
                                    result = _extract_transcript(item)
                                    if result is not None:
                                        return result
                            return None

                        transcript = _extract_transcript(event)
                        if transcript is not None:
                            console.log("Event transcript:", transcript)

                if event_type == "response.error" or event_type == "error":
                    console.print(f"Event: {event_type} - {event}")
                    error = event.get("error") or {}
                    error_details = error.get("message", str(error))
                    error_code = error.get("code")
                    # The service can return this when we accidentally send a
                    # second response.create while one is still active. Treat it
                    # as a soft warning so the session can continue instead of
                    # hard‑failing the whole run.
                    if error_code == "conversation_already_has_active_response":
                        console.print(
                            "\n[yellow]Voice Live reported an overlapping response "
                            "(conversation_already_has_active_response); continuing "
                            "and waiting for the active response to finish.[/yellow]"
                        )
                        continue
                    console.print(
                        "\n"
                        + Panel(
                            error_details,
                            title="Voice Live response error",
                            style="bold red",
                        ).render()
                    )
                    break

                if event_type in {"response.completed", "response.done", "response.finished"}:
                    # Emit the buffered audio to the on_event callback *once* for
                    # the whole response. This lets upstream callers (e.g. the
                    # WebSocket server) decide whether to forward it back to ACS.
                    if audio_chunks and on_event:
                        combined_audio = b"".join(audio_chunks)
                        if combined_audio:
                            delta_b64 = base64.b64encode(combined_audio).decode("ascii")
                            on_event(
                                {
                                    "type": "translation.audio_delta",
                                    "audio": delta_b64,
                                    "sample_rate": config.output_sample_rate_hz,
                                    "channels": 1,
                                    "bits_per_sample": 16,
                                }
                            )
                        # Clear per-response buffer after emitting
                        audio_chunks.clear()

                    if not text_segments and not audio_chunks:
                        console.print("\n[yellow]Response completed with empty content (no text or audio)[/yellow]")
                    else:
                        console.print("\n[bold green]Response completed[/bold green]")

                    # After each completed response, delete all known
                    # conversation items so the next turn starts with a clean
                    # slate. This mirrors a stateless “one-shot” translation
                    # call and prevents the model from reusing or extending
                    # previous turns (e.g. repeating the last sentence after a
                    # cough).
                    if conversation_item_ids:
                        for item_id in list(conversation_item_ids):
                            try:
                                await websocket.send(
                                    json.dumps(
                                        {
                                            "type": "conversation.item.delete",
                                            "item_id": item_id,
                                        }
                                    )
                                )
                                console.log(
                                    f"[dim]Deleted conversation item {item_id} "
                                    "to reset Voice Live context[/dim]"
                                )
                            except Exception:
                                # Best-effort context reset; don't fail the
                                # whole session if a delete call has issues.
                                console.print(
                                    f"[yellow]Failed to delete conversation item "
                                    f"{item_id}; continuing.[/yellow]"
                                )
                        conversation_item_ids.clear()
                    
                    # Clear the response_in_progress flag so streaming can commit next chunk
                    if response_in_progress:
                        response_in_progress.clear()
                    if self._terminate_on_completion:
                        console.print("[dim]Batch test mode: closing Voice Live session after first response.[/dim]")
                        break
                    # Don't break - continue listening for more responses
                    # The streaming will continue and trigger new responses
                    continue

                if event_type == "response.output_text.delta":
                    delta_text = event.get("delta", "")
                    text_segments.append(delta_text)
                    # Emit text delta event
                    if on_event and delta_text:
                        on_event({"type": "translation.text_delta", "delta": delta_text})

                if event_type == "response.output_text.done":
                    console.print()  # New line after text
                    continue

                if event_type in {"response.output_audio.delta", "response.audio.delta"}:
                    delta = event.get("delta")
                    if delta:
                        audio_data = base64.b64decode(delta)
                        audio_chunks.append(audio_data)
                        # Play audio in real-time if output stream is available
                        if audio_output_stream:
                            try:
                                import numpy as np
                                audio_array = np.frombuffer(audio_data, dtype=np.int16)
                                # Reshape if needed (should be 1D for mono)
                                if len(audio_array.shape) == 1:
                                    audio_array = audio_array.reshape(-1, 1)
                                audio_output_stream.write(audio_array)
                            except Exception:
                                # Don't fail on playback errors
                                pass

            if event_type == "response.audio_transcript.delta":
                delta = event.get("delta")
                if delta:
                    audio_transcript = (audio_transcript or "") + delta

            if event_type == "response.audio_transcript.done":
                transcript = event.get("transcript")
                if transcript:
                    audio_transcript = transcript
                    console.print()  # New line after transcript

                if event_type == "input_audio_buffer.speech.recognized":
                    transcript = event.get("transcript")
                    if transcript:
                        recognized_segments.append(transcript)
                        console.print(f"[dim]Recognized: {transcript}[/dim]")
        finally:
            # Clean up audio output stream
            if audio_output_stream:
                try:
                    audio_output_stream.stop()
                    audio_output_stream.close()
                except Exception:
                    pass

        recognized_text = " ".join(seg.strip() for seg in recognized_segments if seg).strip() or None
        raw_output = "".join(text_segments).strip()
        translations: dict[str, str] = {}

        if raw_output:
            try:
                parsed = json.loads(raw_output)
                if isinstance(parsed, dict):
                    translations = {str(k): str(v) for k, v in parsed.items()}
                else:
                    translations = {"response": raw_output}
            except json.JSONDecodeError:
                translations = {"response": raw_output}

        synth_audio = b"".join(audio_chunks) if audio_chunks else None

        if not translations and audio_transcript and self.to_languages:
            translations = {self.to_languages[0]: audio_transcript.strip()}

        has_success_payload = bool(translations) or (audio_transcript and audio_transcript.strip()) or synth_audio
        result_reason = (
            speechsdk.ResultReason.TranslatedSpeech
            if has_success_payload
            else speechsdk.ResultReason.Canceled
        )

        outcome = TranslationOutcome(
            recognized_text=recognized_text or audio_transcript,
            translations=translations,
            result_reason=result_reason,
            error_details=error_details,
        )

        if synth_audio and self.output_audio_path:
            outcome.audio_output_path = self._write_wav(
                audio_bytes=synth_audio,
                sample_rate=config.output_sample_rate_hz,
                channels=1,
                target_path=self.output_audio_path,
            )
        else:
            setattr(outcome, "_synth_audio", synth_audio)

        return outcome

    def _write_wav(
        self,
        *,
        audio_bytes: bytes,
        sample_rate: int,
        channels: int,
        target_path: Path,
    ) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target_path), "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2)  # pcm16
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_bytes)

        console.print(
            Panel.fit(
                f"Synthesized audio saved to {target_path}",
                title="Voice Live audio output",
                style="bold green",
            )
        )

        return target_path

    def _load_wav(self, path: Path) -> tuple[bytes, int, int]:
        with wave.open(str(path), "rb") as wav_file:
            sample_width = wav_file.getsampwidth()
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())

        if sample_width != 2:
            raise ValueError(
                f"Unsupported WAV sample width ({sample_width * 8} bit). "
                "Please provide 16-bit PCM WAV audio."
            )

        if channels not in (1, 2):
            raise ValueError(f"Unsupported WAV channel count ({channels}). Use mono or stereo.")

        if sample_rate not in (16000, 24000, 44100, 48000):
            console.print(
                Panel(
                    f"Warning: uncommon sample rate {sample_rate} Hz. "
                    "Voice Live typically expects 16 kHz. Consider resampling for best quality.",
                    title="Sample rate warning",
                    style="bold yellow",
                )
            )

        if channels == 2:
            frames = self._downmix_to_mono(frames)
            channels = 1

        return frames, sample_rate, channels

    def _downmix_to_mono(self, frames: bytes) -> bytes:
        import array

        stereo = array.array("h", frames)
        mono = array.array("h", (0 for _ in range(len(stereo) // 2)))
        for i in range(0, len(stereo), 2):
            mono[i // 2] = (stereo[i] + stereo[i + 1]) // 2
        return mono.tobytes()

    def _build_config(self, *, sample_rate: int, channels: int) -> VoiceLiveConfig:
        endpoint = self.settings.endpoint or ""
        parsed = urlparse(endpoint)
        netloc = parsed.netloc or parsed.path
        base_path = parsed.path.rstrip("/")

        if not netloc:
            raise RuntimeError(
                "Voice Live endpoint is invalid. Expected format like "
                "'https://<resource>.services.ai.azure.com/'."
            )

        model = self.settings.voice_live_model or "gpt-realtime-mini"
        api_version = self.settings.voice_live_api_version or "2024-10-01-preview"

        deployment = self.settings.voice_live_deployment or model
        query_params = {"api-version": api_version}

        base_path = base_path.strip("/")
        if "openai" not in base_path:
            path = "openai/realtime"
        else:
            path = base_path.strip("/")
            if not path.endswith("realtime"):
                path = path.rstrip("/") + "/realtime"

        query_params["deployment"] = deployment
        query = urlencode(query_params)
        websocket_url = urlunparse(
            (
                "wss",
                netloc,
                f"/{path}",
                "",
                query,
                "",
            )
        )

        output_sample_rate = (
            self.settings.voice_live_output_sample_rate or 24000
        )

        # Note: Turn detection is handled by the service via server-side VAD
        # configured in session.update. Manual commits are only sent when streaming stops.
        commit_interval_setting = (
            self.settings.voice_live_commit_interval
            if self.settings.voice_live_commit_interval is not None
            else 16
        )
        commit_interval = max(4, commit_interval_setting)
        silence_chunks_setting = (
            self.settings.voice_live_silence_chunks
            if self.settings.voice_live_silence_chunks is not None
            else 6
        )
        silence_chunks = max(0, silence_chunks_setting)
        force_commit_setting = (
            self.settings.voice_live_force_commit_chunks
            if self.settings.voice_live_force_commit_chunks is not None
            else commit_interval * 3
        )
        force_commit_chunks = max(commit_interval, force_commit_setting)

        return VoiceLiveConfig(
            websocket_url=websocket_url,
            api_key=self.settings.subscription_key,
            from_language=self.from_language,
            to_languages=self.to_languages,
            voice_name=self.voice_name,
            sample_rate_hz=sample_rate,
            channels=channels,
            deployment=self.settings.voice_live_deployment,
            output_sample_rate_hz=output_sample_rate,
            commit_interval=commit_interval,
            silence_chunks=silence_chunks,
            force_commit_chunks=force_commit_chunks,
        )



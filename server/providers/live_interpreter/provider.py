from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Iterable, Optional, Tuple

import azure.cognitiveservices.speech as speechsdk

from ...audio import Base64AudioCodec
from ...core.event_bus import EventBus, HandlerConfig
from ...core.queues import OverflowPolicy
from ...models.provider_events import ProviderInputEvent, ProviderOutputEvent
from .inbound_handlers import (
    CanceledHandler,
    RecognizedHandler,
    RecognizingHandler,
    SynthesizingHandler,
)

logger = logging.getLogger(__name__)


class LiveInterpreterProvider:
    """
    Streaming translation provider using Azure Live Interpreter (v2 universal endpoint).

    Similar to SpeechTranslator but uses:
    - v2 universal endpoint with open range language detection (76 languages)
    - Continuous language detection mode
    - Automatic voice synthesis based on target voice language

    Required Configuration (.config.yml):
        live_interpreter:
          type: live_interpreter
          region: eastus2  # or specify endpoint directly
          api_key: ${LIVE_INTERPRETER_API_KEY}
          settings:
            languages: [es-ES, en-US]     # Required: Full locale codes, FIRST is target for synthesis
            voice: es-ES-ElviraNeural     # Required: Neural voice name for audio synthesis

    IMPORTANT: Language ordering:
    - The FIRST language in the array is the target language for audio synthesis
    - All languages are used for auto-detection (AutoDetectSourceLanguageConfig)
    - Languages are added to translation config in the order specified
    - Voice name must match the target language locale (first in array)

    The provider:
    - Uses a PushAudioInputStream for continuous audio ingestion
    - Hooks Speech SDK recognizing/recognized events to emit partial/final text
    - Hooks Speech SDK synthesizing events to emit translated audio
    - Publishes ProviderOutputEvent objects to the inbound bus
    """

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        languages: list[str],
        voice: str,
        outbound_bus: EventBus,
        inbound_bus: EventBus,
        session_metadata: Optional[Dict[str, Any]] = None,
    ):
        self.endpoint = endpoint
        self.api_key = api_key
        self.languages = languages
        self.voice = voice
        self.outbound_bus = outbound_bus
        self.inbound_bus = inbound_bus
        self.session_metadata = session_metadata or {}

        self._push_stream: Optional[speechsdk.audio.PushAudioInputStream] = None
        self._recognizer: Optional[speechsdk.translation.TranslationRecognizer] = None
        self._egress_task: Optional[asyncio.Task] = None
        self._closed = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Shared session identifiers (not per-participant in simple shared session)
        self._session_id: Optional[str] = None  # Set on first audio event
        self._audio_seq: int = 0

        logger.info(
            f"🎯 LiveInterpreterProvider initialized: endpoint={self.endpoint}, "
            f"languages={self.languages} (target: {self.languages[0]}), "
            f"voice={self.voice}"
        )

    async def start(self) -> None:
        """Initialize Speech SDK recognizer and register audio handler."""
        if self._closed:
            raise RuntimeError("Cannot start closed provider")

        self._loop = asyncio.get_running_loop()
        self._push_stream = self._create_push_stream()
        self._recognizer = self._create_recognizer(self._push_stream)

        self._attach_event_handlers()
        self._start_recognition()

        self._egress_task = asyncio.create_task(
            self._register_audio_handler(),
            name="live-interpreter-egress",
        )
        logger.info("✅ Live Interpreter provider started")

    def _create_translation_config(
        self,
    ) -> Tuple[
        speechsdk.translation.SpeechTranslationConfig,
        Optional[speechsdk.languageconfig.AutoDetectSourceLanguageConfig],
    ]:
        """Build v2 translation config with open range language detection."""
        # Create translation config with v2 endpoint
        translation_config = speechsdk.translation.SpeechTranslationConfig(
            subscription=self.api_key,
            endpoint=self.endpoint,
        )

        # Add all languages in order (SDK synthesizes the first target language)
        logger.info(f"📋 Adding target languages in order: {self.languages}")
        for lang in self.languages:
            translation_config.add_target_language(lang)

        # Configure synthesis voice from config
        translation_config.voice_name = self.voice
        logger.info(
            f"🎙️ Speech synthesis configured: voice={self.voice}, "
            f"target_locale={self.languages[0]}"
        )

        # Use configured languages for auto-detection
        auto_detect_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=self.languages
        )

        return translation_config, auto_detect_config

    def _create_push_stream(self) -> speechsdk.audio.PushAudioInputStream:
        """Create push audio stream using session metadata when available."""
        sample_rate, channels = self._resolve_audio_format()
        audio_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=sample_rate,
            bits_per_sample=16,
            channels=channels,
        )
        return speechsdk.audio.PushAudioInputStream(audio_format)

    def _create_recognizer(
        self,
        push_stream: speechsdk.audio.PushAudioInputStream,
    ) -> speechsdk.translation.TranslationRecognizer:
        """Create translation recognizer."""
        translation_config, auto_detect_config = self._create_translation_config()
        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)

        recognizer = speechsdk.translation.TranslationRecognizer(
            translation_config=translation_config,
            audio_config=audio_config,
            auto_detect_source_language_config=auto_detect_config,
        )
        return recognizer

    def _resolve_audio_format(self) -> Tuple[int, int]:
        """Infer audio format from session metadata (ACS audio metadata)."""
        meta = (
            self.session_metadata.get("acs_audio", {})
            if isinstance(self.session_metadata, dict)
            else {}
        )
        audio_format = meta.get("format") if isinstance(meta, dict) else {}
        sample_rate = audio_format.get("sample_rate_hz") or 16000
        channels = audio_format.get("channels") or 1
        return int(sample_rate), int(channels)

    async def _register_audio_handler(self) -> None:
        """Register handler to process incoming audio from outbound bus."""
        await self.outbound_bus.register_handler(
            HandlerConfig(
                name="live_interpreter_audio",
                queue_max=1000,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1,
            ),
            self._process_audio,
        )

    async def _process_audio(self, event: ProviderInputEvent) -> None:
        """Process incoming audio event."""
        if self._closed:
            logger.debug("Provider closed; skipping audio")
            return

        # Set session_id once on first audio event
        if not self._session_id:
            self._session_id = event.session_id

        if not self._push_stream:
            logger.warning("Push stream missing; dropping audio for commit %s", event.commit_id)
            return

        try:
            audio_bytes = Base64AudioCodec.decode(event.b64_audio_string)
        except Exception as exc:
            logger.exception("Failed to decode audio for commit=%s: %s", event.commit_id, exc)
            return

        try:
            self._push_stream.write(audio_bytes)
            logger.debug(
                "Pushed audio: commit=%s participant=%s bytes=%s",
                event.commit_id,
                event.participant_id,
                len(audio_bytes),
            )
        except Exception as exc:
            logger.exception("Failed to write audio for commit=%s: %s", event.commit_id, exc)

    def _attach_event_handlers(self) -> None:
        """Wire SDK events to handler callbacks."""
        if not self._recognizer:
            raise RuntimeError("Recognizer not initialized")
        if not self._loop:
            raise RuntimeError("Event loop not captured")

        # Create wrapper functions for handlers that match expected signatures
        def publish_response_wrapper(text: str, partial: bool, detected_language: Optional[str]) -> None:
            self._publish_response(text, partial=partial, detected_language=detected_language)

        def publish_audio_wrapper(audio_bytes: bytes, partial: bool) -> None:
            self._publish_audio(audio_bytes, partial=partial)

        # Create handlers with necessary dependencies
        recognizing_handler = RecognizingHandler(self.languages)
        recognized_handler = RecognizedHandler(self.languages, publish_response_wrapper)
        canceled_handler = CanceledHandler()  # No participant tracking in shared session
        synthesizing_handler = SynthesizingHandler(publish_audio_wrapper)

        # Connect handlers directly (they implement __call__)
        logger.info("🔗 Connecting event handlers...")
        self._recognizer.recognizing.connect(recognizing_handler)
        self._recognizer.recognized.connect(recognized_handler)
        self._recognizer.canceled.connect(canceled_handler)
        self._recognizer.synthesizing.connect(synthesizing_handler)
        logger.info("✅ All event handlers connected")

    def _start_recognition(self) -> None:
        """Start continuous recognition."""
        if not self._recognizer:
            raise RuntimeError("Recognizer not initialized")
        self._recognizer.start_continuous_recognition_async().get()
        logger.info("🎤 Recognition started")

    def _publish_response(
        self, text: str, *, partial: bool, detected_language: Optional[str] = None
    ) -> None:
        """
        Publish translation response to inbound bus.

        Note: In shared session mode, participant_id is None since we cannot
        reliably attribute which participant triggered the recognition event.
        """
        if not self._loop:
            logger.debug("Event loop not set; skipping publish")
            return

        payload = {
            "text": text,
            "final": not partial,
            "role": "translation",
        }

        if detected_language:
            payload["detected_language"] = detected_language

        response = ProviderOutputEvent(
            commit_id="shared",  # Shared session - no per-event tracking
            session_id=self._session_id or "unknown",
            participant_id=None,  # Unknown in shared session
            event_type="transcript.delta",
            payload=payload,
            provider="live_interpreter",
            stream_id="shared",  # Shared session stream
            timestamp_ms=int(time.time() * 1000),
        )
        asyncio.run_coroutine_threadsafe(self.inbound_bus.publish(response), self._loop)  # type: ignore[arg-type]

    def _publish_audio(self, audio_bytes: bytes, *, partial: bool) -> None:
        """
        Publish synthesized audio to inbound bus.

        Note: In shared session mode, participant_id is None since we cannot
        reliably attribute which participant triggered the synthesis event.
        """
        if not self._loop:
            logger.debug("Event loop not set; skipping audio publish")
            return

        audio_b64 = Base64AudioCodec.encode(audio_bytes)
        self._audio_seq += 1

        sample_rate, channels = self._resolve_audio_format()
        response = ProviderOutputEvent(
            commit_id="shared",  # Shared session - no per-event tracking
            session_id=self._session_id or "unknown",
            participant_id=None,  # Unknown in shared session
            event_type="audio.delta",
            payload={
                "audio_b64": audio_b64,
                "seq": self._audio_seq,
                "format": {
                    "encoding": "pcm16",
                    "sample_rate_hz": sample_rate,
                    "channels": channels,
                },
                "partial": partial,
            },
            provider="live_interpreter",
            stream_id="shared",  # Shared session stream
            timestamp_ms=int(time.time() * 1000),
        )

        logger.debug(
            "Publishing audio: seq=%d bytes=%d partial=%s",
            self._audio_seq,
            len(audio_bytes),
            partial,
        )

        asyncio.run_coroutine_threadsafe(self.inbound_bus.publish(response), self._loop)  # type: ignore[arg-type]

    async def close(self) -> None:
        """Stop recognition and cleanup resources."""
        self._closed = True

        if self._recognizer:
            try:
                self._recognizer.stop_continuous_recognition_async().get()
            except Exception:
                logger.debug("Recognizer stop failed", exc_info=True)

        if self._push_stream:
            try:
                self._push_stream.close()
            except Exception:
                logger.debug("Push stream close failed", exc_info=True)

        if self._egress_task:
            self._egress_task.cancel()
            try:
                await self._egress_task
            except asyncio.CancelledError:
                pass

        logger.info("🔒 Live Interpreter provider closed")

    async def health(self) -> str:
        """Check provider health status."""
        if self._closed:
            return "degraded"
        if self._recognizer:
            return "ok"
        return "initializing"

    async def cancel_response(self) -> None:
        """Best-effort cancel by restarting recognizer and push stream."""
        if self._closed:
            return
        try:
            if self._recognizer:
                self._recognizer.stop_continuous_recognition_async().get()
            if self._push_stream:
                try:
                    self._push_stream.close()
                except Exception:
                    logger.debug("Push stream close failed during cancel", exc_info=True)

            # Recreate push stream and recognizer to realign state
            self._push_stream = self._create_push_stream()
            self._recognizer = self._create_recognizer(self._push_stream)
            self._attach_event_handlers()
            self._start_recognition()
            logger.info("Live Interpreter recognizer restarted after cancel")
        except Exception:
            logger.exception("Live Interpreter cancel_response failed")

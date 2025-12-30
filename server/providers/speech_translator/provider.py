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


class SpeechTranslatorProvider:
    """
    Streaming translation provider backed by Azure Speech SDK.

    The provider:
    - Uses a PushAudioInputStream for continuous audio ingestion
    - Hooks Speech SDK recognizing/recognized events to emit partial/final text
    - Hooks Speech SDK synthesizing events to emit translated audio
    - Publishes ProviderOutputEvent objects to the inbound bus
    """

    DEFAULT_AUTO_DETECT: Tuple[str, str] = ("en-US", "es-ES")
    DEFAULT_TARGET_LANGUAGES: Tuple[str, ...] = ("en", "es")

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        outbound_bus: EventBus,
        inbound_bus: EventBus,
        session_metadata: Optional[Dict[str, Any]] = None,
    ):
        self.endpoint = endpoint
        self.api_key = api_key
        self.outbound_bus = outbound_bus
        self.inbound_bus = inbound_bus
        self.session_metadata = session_metadata or {}

        self._push_stream: Optional[speechsdk.audio.PushAudioInputStream] = None
        self._recognizer: Optional[speechsdk.translation.TranslationRecognizer] = None
        self._egress_task: Optional[asyncio.Task] = None
        self._closed = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_commit_id: str = "unknown"
        self._session_id: Optional[str] = None
        self._participant_id: Optional[str] = None
        self._audio_seq: int = 0

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
            name="speech-translator-egress",
        )
        logger.info("Speech Translator provider started")

    def _create_translation_config(self) -> Tuple[speechsdk.translation.SpeechTranslationConfig, Optional[speechsdk.languageconfig.AutoDetectSourceLanguageConfig]]:
        """Build translation config with endpoint and API key."""
        # Create translation config with endpoint and subscription key
        translation_config = speechsdk.translation.SpeechTranslationConfig(
            subscription=self.api_key,
            endpoint=self.endpoint,
        )

        # Enable continuous language detection
        translation_config.set_property(
            property_id=speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode,
            value="Continuous",
        )

        # Add target languages
        target_languages = self._resolve_target_languages()
        logger.info(f"📋 Configuring target languages: {list(target_languages)}")
        for lang in target_languages:
            translation_config.add_target_language(lang)

        # Configure synthesis voice for audio output
        voice_name = self._resolve_voice_name()
        logger.info(f"🔍 Voice resolution result: voice_name={voice_name}")
        if voice_name:
            translation_config.voice_name = voice_name  # Use voice_name, not speech_synthesis_voice_name
            logger.info(f"🎙️ Speech synthesis ENABLED with voice: {voice_name}")
        else:
            logger.warning("⚠️ Speech synthesis DISABLED - no voice configured (translation will be text-only)")

        # Configure auto-detect languages
        auto_detect_languages = self._resolve_auto_detect_languages()
        auto_detect_config: Optional[speechsdk.languageconfig.AutoDetectSourceLanguageConfig]
        if auto_detect_languages:
            auto_detect_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                languages=auto_detect_languages
            )
        else:
            auto_detect_config = None

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
        translation_config, auto_detect_config = self._create_translation_config()
        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)

        recognizer = speechsdk.translation.TranslationRecognizer(
            translation_config=translation_config,
            audio_config=audio_config,
            auto_detect_source_language_config=auto_detect_config,
        )
        return recognizer

    def _resolve_target_languages(self) -> Iterable[str]:
        """Resolve target languages from metadata, falling back to defaults."""
        languages = self.session_metadata.get("target_languages")
        if isinstance(languages, list) and languages:
            return [str(lang) for lang in languages]
        return self.DEFAULT_TARGET_LANGUAGES

    def _resolve_auto_detect_languages(self) -> Tuple[str, ...]:
        """Resolve auto-detect language list from metadata (or defaults)."""
        languages = self.session_metadata.get("auto_detect_languages")
        if isinstance(languages, list) and languages:
            return tuple(str(lang) for lang in languages)
        return self.DEFAULT_AUTO_DETECT

    def _resolve_audio_format(self) -> Tuple[int, int]:
        """Infer audio format from session metadata (ACS audio metadata)."""
        meta = self.session_metadata.get("acs_audio", {}) if isinstance(self.session_metadata, dict) else {}
        audio_format = meta.get("format") if isinstance(meta, dict) else {}
        sample_rate = audio_format.get("sample_rate_hz") or 16000
        channels = audio_format.get("channels") or 1
        return int(sample_rate), int(channels)

    def _resolve_voice_name(self) -> Optional[str]:
        """
        Determine synthesis voice from metadata or map from target language.

        Priority:
        1. Explicit voice_name in metadata
        2. Map first target language to default neural voice

        Returns:
            Voice name (e.g., "es-ES-ElviraNeural") or None to disable synthesis
        """
        # Check for explicit voice override
        voice = self.session_metadata.get("voice_name")
        if voice:
            return str(voice)

        # Map target language to default neural voice
        target_langs = list(self._resolve_target_languages())
        if not target_langs:
            return None

        # Voice mapping for common languages
        # Using Neural voices for high quality synthesis
        VOICE_MAP = {
            "es": "es-ES-ElviraNeural",
            "en": "en-US-JennyNeural",
            "de": "de-DE-KatjaNeural",
            "fr": "fr-FR-DeniseNeural",
            "pt": "pt-BR-FranciscaNeural",
            "it": "it-IT-ElsaNeural",
            "ja": "ja-JP-NanamiNeural",
            "zh": "zh-CN-XiaoxiaoNeural",
            "ko": "ko-KR-SunHiNeural",
            "ar": "ar-SA-ZariyahNeural",
            "hi": "hi-IN-SwaraNeural",
            "ru": "ru-RU-SvetlanaNeural",
        }

        # Extract language code (e.g., "es" from "es-ES" or "es")
        lang_code = target_langs[0].split("-")[0]
        return VOICE_MAP.get(lang_code)

    def _pick_translation(self, result: speechsdk.translation.TranslationRecognitionResult) -> Optional[str]:
        """Select translation text using target language preference."""
        translations = result.translations if hasattr(result, "translations") else None
        if translations:
            for lang in self._resolve_target_languages():
                if lang in translations:
                    return translations[lang]
            for value in translations.values():
                return value
        return result.text or None

    def _attach_event_handlers(self) -> None:
        """Wire SDK events to inbound bus publishing."""
        if not self._recognizer:
            raise RuntimeError("Recognizer not initialized")
        if not self._loop:
            raise RuntimeError("Event loop not captured")
        recognizing_handler = RecognizingHandler(self._pick_translation)
        recognized_handler = RecognizedHandler(self._pick_translation)
        canceled_handler = CanceledHandler()
        synthesizing_handler = SynthesizingHandler()

        def recognizing_callback(evt: speechsdk.translation.TranslationRecognitionEventArgs) -> None:
            # Don't send recognizing events - they accumulate text which isn't helpful
            # Only send final recognized events
            text = recognizing_handler.handle(evt)
            if text:
                logger.debug(f"📝 Recognizing (partial, not sent): {text[:50]}...")

        def recognized_callback(evt: speechsdk.translation.TranslationRecognitionEventArgs) -> None:
            # Log what's available in the result
            if evt and evt.result:
                logger.info(f"🔍 Recognized event details:")
                logger.info(f"  - Reason: {evt.result.reason}")
                logger.info(f"  - Text: {evt.result.text}")
                logger.info(f"  - Translations: {evt.result.translations if hasattr(evt.result, 'translations') else 'N/A'}")
                logger.info(f"  - Has properties: {dir(evt.result)}")

            text = recognized_handler.handle(evt)
            if text:
                logger.info(f"✅ Recognized (final): {text}")
                self._publish_response(text, partial=False)
            else:
                logger.warning("⚠️ Recognized event but no translation text extracted")

        def canceled_callback(evt: speechsdk.translation.TranslationRecognitionCanceledEventArgs) -> None:
            message = canceled_handler.handle(evt)
            if message:
                logger.error(f"❌ Speech Translator canceled: {message}")

        def synthesizing_callback(evt: speechsdk.translation.TranslationSynthesisEventArgs) -> None:
            logger.info("🎵 Synthesizing callback triggered!")
            try:
                audio_bytes = synthesizing_handler.handle(evt)
                if audio_bytes:
                    logger.info(f"🎵 Got synthesized audio: {len(audio_bytes)} bytes")
                    self._publish_audio(audio_bytes, partial=True)
                else:
                    logger.warning("⚠️ Synthesizing callback fired but no audio bytes returned")
            except Exception as exc:
                logger.error(f"❌ Synthesizing callback error: {exc}", exc_info=True)

        logger.info("🔗 Connecting event handlers...")
        self._recognizer.recognizing.connect(recognizing_callback)
        self._recognizer.recognized.connect(recognized_callback)
        self._recognizer.canceled.connect(canceled_callback)
        self._recognizer.synthesizing.connect(synthesizing_callback)
        logger.info("✅ All event handlers connected (including synthesizing)")

    def _start_recognition(self) -> None:
        """Start continuous recognition."""
        if not self._recognizer:
            raise RuntimeError("Recognizer not initialized")
        self._recognizer.start_continuous_recognition_async().get()
        logger.info("Speech Translator recognition started")

    async def _register_audio_handler(self) -> None:
        """Register handler that consumes ProviderInputEvent and pushes to SDK stream."""
        if not self._push_stream:
            raise RuntimeError("Push stream not initialized")

        await self.outbound_bus.register_handler(
            HandlerConfig(
                name="speech_translator_egress",
                queue_max=1000,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1,
            ),
            self._process_audio,
        )

    async def _process_audio(self, request: ProviderInputEvent) -> None:
        """Decode base64 PCM audio and forward to the SDK stream."""
        if self._closed:
            logger.debug("Provider closed; skipping audio")
            return

        self._last_commit_id = request.commit_id
        self._session_id = request.session_id
        self._participant_id = request.participant_id

        if not self._push_stream:
            logger.warning("Push stream missing; dropping audio for commit %s", request.commit_id)
            return

        try:
            audio_bytes = Base64AudioCodec.decode(request.b64_audio_string)
        except Exception as exc:
            logger.exception("Failed to decode audio for commit=%s: %s", request.commit_id, exc)
            return

        try:
            self._push_stream.write(audio_bytes)
            logger.info(
                "Pushed audio to Speech Translator: commit=%s bytes=%s",
                request.commit_id,
                len(audio_bytes),
            )
        except Exception as exc:
            logger.exception("Failed to write audio for commit=%s: %s", request.commit_id, exc)

    def _publish_response(self, text: str, *, partial: bool) -> None:
        """Publish translation response to inbound bus from SDK callbacks."""
        if not self._loop:
            logger.debug("Event loop not set; skipping publish")
            return

        response = ProviderOutputEvent(
            commit_id=self._last_commit_id,
            session_id=self._session_id or "unknown",
            participant_id=self._participant_id,
            event_type="transcript.delta" if partial else "transcript.delta",
            payload={"text": text, "final": not partial, "role": "translation"},
            provider="speech_translator",
            stream_id=self._last_commit_id,
            timestamp_ms=int(time.time() * 1000),
        )
        asyncio.run_coroutine_threadsafe(self.inbound_bus.publish(response), self._loop)  # type: ignore[arg-type]

    def _publish_audio(self, audio_bytes: bytes, *, partial: bool) -> None:
        """Publish synthesized audio to inbound bus from SDK callbacks."""
        if not self._loop:
            logger.debug("Event loop not set; skipping audio publish")
            return

        # Encode audio to base64
        audio_b64 = Base64AudioCodec.encode(audio_bytes)

        # Increment audio sequence number
        self._audio_seq += 1

        # Get audio format (Speech SDK synthesis is typically 16kHz mono PCM16)
        # The actual format may vary based on the voice configuration
        sample_rate, channels = self._resolve_audio_format()

        response = ProviderOutputEvent(
            commit_id=self._last_commit_id,
            session_id=self._session_id or "unknown",
            participant_id=self._participant_id,
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
            provider="speech_translator",
            stream_id=self._last_commit_id,
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

        if self._egress_task and not self._egress_task.done():
            self._egress_task.cancel()
            try:
                await self._egress_task
            except asyncio.CancelledError:
                pass

        logger.info("Speech Translator provider closed")

    async def health(self) -> str:
        """Check provider health."""
        if self._closed:
            return "degraded"
        if self._recognizer:
            return "ok"
        return "initializing"

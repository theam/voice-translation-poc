from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any, Dict, Iterable, Optional, Tuple

import azure.cognitiveservices.speech as speechsdk

from ...core.event_bus import EventBus, HandlerConfig
from ...core.queues import OverflowPolicy
from ...models.messages import AudioRequest, ProviderOutputEvent
from .inbound_handlers import (
    CanceledHandler,
    RecognizedHandler,
    RecognizingHandler,
)

logger = logging.getLogger(__name__)


class LiveInterpreterProvider:
    """
    Streaming translation provider backed by Azure Speech SDK (Live Interpreter).

    The provider:
    - Uses a PushAudioInputStream for continuous audio ingestion
    - Hooks Speech SDK recognizing/recognized events to emit partial/final text
    - Publishes ProviderOutputEvent objects to the inbound bus
    """

    DEFAULT_AUTO_DETECT: Tuple[str, str] = ("en-US", "es-ES")
    DEFAULT_TARGET_LANGUAGES: Tuple[str, ...] = ("es",)

    def __init__(
        self,
        *,
        endpoint: Optional[str],
        api_key: str,
        region: Optional[str],
        resource: Optional[str],
        outbound_bus: EventBus,
        inbound_bus: EventBus,
        session_metadata: Optional[Dict[str, Any]] = None,
    ):
        self.endpoint = endpoint
        self.api_key = api_key
        self.region = region
        self.resource = resource
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
        logger.info("Live Interpreter provider started")

    def _create_translation_config(self) -> Tuple[speechsdk.translation.SpeechTranslationConfig, Optional[speechsdk.languageconfig.AutoDetectSourceLanguageConfig]]:
        """Build translation config with optional auto-detect."""
        endpoint = self.endpoint or self._build_endpoint_from_resource()
        translation_config: speechsdk.translation.SpeechTranslationConfig
        if endpoint:
            try:
                translation_config = speechsdk.translation.SpeechTranslationConfig(
                    speech_key=self.api_key,
                    endpoint=endpoint,
                )
            except Exception:
                logger.warning("Failed to initialize SpeechTranslationConfig with endpoint; falling back to subscription/region")
                translation_config = speechsdk.translation.SpeechTranslationConfig(
                    subscription=self.api_key,
                    region=self._infer_region_from_endpoint(endpoint),
                )
        else:
            translation_config = speechsdk.translation.SpeechTranslationConfig(
                subscription=self.api_key,
                region=self._infer_region_from_endpoint(endpoint),
            )

        translation_config.set_property(
            property_id=speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode,
            value="Continuous",
        )

        target_languages = self._resolve_target_languages()
        for lang in target_languages:
            translation_config.add_target_language(lang)

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

    def _build_endpoint_from_resource(self) -> Optional[str]:
        """Construct endpoint from resource/region if explicit endpoint is missing."""
        if not self.resource:
            return None
        return f"https://{self.resource}.cognitiveservices.azure.com/"

    def _infer_region_from_endpoint(self, endpoint: Optional[str]) -> str:
        """Best-effort region inference from endpoint hostname or provided region."""
        if self.region:
            return self.region
        if not endpoint:
            return "eastus"
        try:
            host = endpoint.split("://", 1)[-1]
            host = host.split("/", 1)[0]
            region = host.split(".")[0]
            return region
        except Exception:
            return "eastus"

    def _attach_event_handlers(self) -> None:
        """Wire SDK events to inbound bus publishing."""
        if not self._recognizer:
            raise RuntimeError("Recognizer not initialized")
        if not self._loop:
            raise RuntimeError("Event loop not captured")
        recognizing_handler = RecognizingHandler(self._pick_translation)
        recognized_handler = RecognizedHandler(self._pick_translation)
        canceled_handler = CanceledHandler()

        def recognizing_callback(evt: speechsdk.translation.TranslationRecognitionEventArgs) -> None:
            text = recognizing_handler.handle(evt)
            if text:
                self._publish_response(text, partial=True)

        def recognized_callback(evt: speechsdk.translation.TranslationRecognitionEventArgs) -> None:
            text = recognized_handler.handle(evt)
            if text:
                self._publish_response(text, partial=False)

        def canceled_callback(evt: speechsdk.translation.TranslationRecognitionCanceledEventArgs) -> None:
            message = canceled_handler.handle(evt)
            if message:
                logger.error("Live Interpreter canceled: %s", message)

        self._recognizer.recognizing.connect(recognizing_callback)
        self._recognizer.recognized.connect(recognized_callback)
        self._recognizer.canceled.connect(canceled_callback)

    def _start_recognition(self) -> None:
        """Start continuous recognition."""
        if not self._recognizer:
            raise RuntimeError("Recognizer not initialized")
        self._recognizer.start_continuous_recognition_async().get()
        logger.info("Live Interpreter recognition started")

    async def _register_audio_handler(self) -> None:
        """Register handler that consumes AudioRequest and pushes to SDK stream."""
        if not self._push_stream:
            raise RuntimeError("Push stream not initialized")

        await self.outbound_bus.register_handler(
            HandlerConfig(
                name="live_interpreter_egress",
                queue_max=1000,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1,
            ),
            self._process_audio,
        )

    async def _process_audio(self, request: AudioRequest) -> None:
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
            audio_bytes = base64.b64decode(request.audio_data, validate=False)
        except Exception as exc:
            logger.exception("Failed to decode audio for commit=%s: %s", request.commit_id, exc)
            return

        try:
            self._push_stream.write(audio_bytes)
            logger.info(
                "Pushed audio to Live Interpreter: commit=%s bytes=%s",
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
            event_type="transcript.delta" if partial else "transcript.done",
            payload={"text": text, "final": not partial, "role": "translation"},
            provider="live_interpreter",
            stream_id=self._last_commit_id,
            timestamp_ms=int(time.time() * 1000),
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

        logger.info("Live Interpreter provider closed")

    async def health(self) -> str:
        """Check provider health."""
        if self._closed:
            return "degraded"
        if self._recognizer:
            return "ok"
        return "initializing"

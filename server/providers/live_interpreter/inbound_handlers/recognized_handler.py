from __future__ import annotations

import logging
from typing import Callable, Optional

import azure.cognitiveservices.speech as speechsdk

logger = logging.getLogger(__name__)


class RecognizedHandler:
    """Handle recognized events (final recognition) - extracts translation and publishes."""

    def __init__(
        self,
        target_text_languages: list[str],
        publish_response: Callable[[str, bool, Optional[str]], None],
    ):
        """
        Initialize handler with target text languages and publisher.

        Args:
            target_text_languages: List of target language codes for translation selection
            publish_response: Function to publish translation response
        """
        self._target_text_languages = target_text_languages
        self._publish_response = publish_response

    def _pick_translation(
        self, result: speechsdk.translation.TranslationRecognitionResult
    ) -> Optional[str]:
        """Select translation text using target text language preference."""
        translations = result.translations if hasattr(result, "translations") else None
        if translations:
            # Try each configured target text language in order
            for lang in self._target_text_languages:
                if lang in translations:
                    return translations[lang]
            # Fallback to first available translation
            for key, value in translations.items():
                return value

        # Fallback to result.text
        return result.text or None

    def __call__(self, evt: speechsdk.translation.TranslationRecognitionEventArgs) -> None:
        """
        Handle recognized callback - extract translation and publish.

        Args:
            evt: Recognition event from Speech SDK
        """
        if not evt or not getattr(evt, "result", None):
            return

        # Extract detected language
        detected_language = self._extract_detected_language(evt.result)

        # Extract translation text
        text = self._pick_translation(evt.result)

        if text:
            logger.info(f"✅ Recognized (final): {text} [detected: {detected_language}]")
            self._publish_response(text, False, detected_language)  # partial=False
        else:
            logger.warning("⚠️ Recognized event but no translation text extracted")

    @staticmethod
    def _extract_detected_language(
        result: speechsdk.translation.TranslationRecognitionResult
    ) -> Optional[str]:
        """Extract detected source language from recognition result properties."""
        if not result or not hasattr(result, "properties"):
            return None

        try:
            detected_language = result.properties.get(
                speechsdk.PropertyId.SpeechServiceConnection_AutoDetectSourceLanguageResult
            )
            return detected_language if detected_language else None
        except Exception as exc:
            logger.warning(f"Failed to extract detected language: {exc}")
            return None

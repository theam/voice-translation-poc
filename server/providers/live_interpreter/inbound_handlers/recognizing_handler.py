from __future__ import annotations

import logging
from typing import Optional

import azure.cognitiveservices.speech as speechsdk

logger = logging.getLogger(__name__)


class RecognizingHandler:
    """Handle recognizing events (partial recognition) - logs only, doesn't publish."""

    def __init__(self, target_text_languages: list[str]):
        """
        Initialize handler with target text languages.

        Args:
            target_text_languages: List of target language codes for translation selection
        """
        self._target_text_languages = target_text_languages

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
        Handle recognizing callback - log partial translation (not published).

        Args:
            evt: Recognition event from Speech SDK
        """
        if not evt or not getattr(evt, "result", None):
            return

        text = self._pick_translation(evt.result)
        if text:
            logger.debug(f"📝 Recognizing (partial, not sent): {text[:50]}...")

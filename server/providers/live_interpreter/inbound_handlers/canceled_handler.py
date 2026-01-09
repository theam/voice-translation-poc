from __future__ import annotations

import logging
from typing import Optional

import azure.cognitiveservices.speech as speechsdk

logger = logging.getLogger(__name__)


class CanceledHandler:
    """Handle cancellation events from Live Interpreter."""

    def __call__(self, evt: speechsdk.translation.TranslationRecognitionCanceledEventArgs) -> None:
        """
        Handle canceled callback - log error details.

        Args:
            evt: Cancellation event from Speech SDK
        """
        if not evt:
            return

        message = getattr(evt, "error_details", None) or "unknown error"
        logger.error(f"❌ Recognition canceled: error={message}")

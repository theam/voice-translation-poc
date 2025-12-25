from __future__ import annotations

from typing import Optional

import azure.cognitiveservices.speech as speechsdk


class CanceledHandler:
    """Handle cancellation events from Live Interpreter."""

    def handle(self, evt: speechsdk.translation.TranslationRecognitionCanceledEventArgs) -> Optional[str]:
        if not evt:
            return None
        return getattr(evt, "error_details", None) or "unknown"

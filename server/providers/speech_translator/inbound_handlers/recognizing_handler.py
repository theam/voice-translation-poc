from __future__ import annotations

from typing import Callable, Optional

import azure.cognitiveservices.speech as speechsdk


class RecognizingHandler:
    """Handle recognizing events by selecting the best available translation text."""

    def __init__(
        self,
        pick_translation: Callable[[speechsdk.translation.TranslationRecognitionResult], Optional[str]],
    ):
        self._pick_translation = pick_translation

    def handle(self, evt: speechsdk.translation.TranslationRecognitionEventArgs) -> Optional[str]:
        if not evt or not getattr(evt, "result", None):
            return None
        return self._pick_translation(evt.result)

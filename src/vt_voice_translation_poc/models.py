"""Shared data models for translation providers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import azure.cognitiveservices.speech as speechsdk


@dataclass
class TranslationOutcome:
    """Holds the results from a translation invocation."""

    recognized_text: Optional[str]
    translations: dict[str, str]
    result_reason: speechsdk.ResultReason
    audio_output_path: Optional[Path] = None
    error_details: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.result_reason in {
            speechsdk.ResultReason.TranslatedSpeech,
            speechsdk.ResultReason.RecognizedSpeech,
        }


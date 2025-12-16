"""Provider selection and coordination."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Optional, Protocol

from rich.console import Console

from .audio import AudioInput
from .config import SpeechProvider, SpeechServiceSettings
from .live_interpreter import LiveInterpreterTranslator
from .models import TranslationOutcome
from .voice_live import VoiceLiveTranslator

console = Console()

# Type alias for translation event callbacks
# Events are dictionaries containing event type and associated data
TranslationEventCallback = Callable[[dict], None]


class Translator(Protocol):
    """Protocol representing a translation provider implementation."""

    def translate(
        self, 
        audio_input: AudioInput,
        on_event: Optional[TranslationEventCallback] = None,
    ) -> TranslationOutcome:
        ...


def create_translator(
    settings: SpeechServiceSettings,
    *,
    from_language: str,
    to_languages: Iterable[str],
    voice_name: Optional[str],
    output_audio_path: Optional[Path],
    terminate_on_completion: bool = False,
    local_audio_playback: bool = False,
) -> Translator:
    """Return a translator implementation for the configured provider."""
    if settings.provider is SpeechProvider.LIVE_INTERPRETER:
        return LiveInterpreterTranslator(
            settings,
            voice_name=voice_name,
            output_audio_path=output_audio_path,
        )

    if settings.provider is SpeechProvider.VOICE_LIVE:
        return VoiceLiveTranslator(
            settings,
            from_language=from_language,
            to_languages=to_languages,
            voice_name=voice_name,
            output_audio_path=output_audio_path,
            terminate_on_completion=terminate_on_completion,
            local_audio_playback=local_audio_playback,
        )

    raise RuntimeError(f"Unsupported provider: {settings.provider}")



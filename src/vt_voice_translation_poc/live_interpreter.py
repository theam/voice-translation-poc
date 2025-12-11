"""Live Interpreter API integration using Azure Speech SDK."""

from __future__ import annotations

import base64
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import azure.cognitiveservices.speech as speechsdk
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .audio import AudioInput
from .config import SpeechServiceSettings
from .models import TranslationOutcome

console = Console()


class LiveInterpreterTranslator:
    """High-level orchestrator for running a single translation session via Live Interpreter."""

    def __init__(
        self,
        settings: SpeechServiceSettings,
        voice_name: Optional[str] = None,
        output_audio_path: Optional[Path] = None,
    ) -> None:
        self.settings = settings
        self.supported_languages = ("en-US", "es-ES")
        self.voice_name = voice_name
        self.output_audio_path = output_audio_path

        if self.voice_name:
            console.print(
                "[yellow]Voice synthesis will use a single voice while translating "
                "bidirectionally between English and Spanish.[/yellow]"
            )

    def _get_default_voice_for_language(self, language: str) -> str:
        """Get a default neural voice for the target language."""
        # Map common language codes to default neural voices
        voice_map = {
            "es": "es-ES-ElviraNeural",  # Spanish (Spain)
            "es-ES": "es-ES-ElviraNeural",
            "es-MX": "es-MX-DaliaNeural",  # Spanish (Mexico)
            "fr": "fr-FR-DeniseNeural",  # French
            "fr-FR": "fr-FR-DeniseNeural",
            "de": "de-DE-KatjaNeural",  # German
            "de-DE": "de-DE-KatjaNeural",
            "en": "en-US-JennyNeural",  # English
            "en-US": "en-US-JennyNeural",
            "it": "it-IT-ElsaNeural",  # Italian
            "it-IT": "it-IT-ElsaNeural",
            "pt": "pt-BR-FranciscaNeural",  # Portuguese
            "pt-BR": "pt-BR-FranciscaNeural",
        }
        return voice_map.get(language, f"{language}-JennyNeural")  # Fallback pattern

    def _build_translation_config(
        self, 
    ) -> tuple[speechsdk.translation.SpeechTranslationConfig, Optional[speechsdk.languageconfig.AutoDetectSourceLanguageConfig]]:
        """Build translation config with optional automatic language detection.
        
        Returns:
            Tuple of (translation_config, auto_detect_config)
            auto_detect_config is None if auto-detect is disabled
        """
        # Try to use from_endpoint if available (newer SDK versions)
        # Otherwise fall back to standard constructor with subscription and region
        try:
            config = speechsdk.translation.SpeechTranslationConfig(
                speech_key=self.settings.subscription_key,
                endpoint=self.settings.endpoint,
            )
        except Exception:
            # Fall back to standard constructor if from_endpoint fails
            # print in red bold
            console.print(f"[bold red]Exception building translation config from endpoint: {Exception}[/bold red]")
            config = speechsdk.translation.SpeechTranslationConfig(
                subscription=self.settings.subscription_key,
                region=self.settings.service_region,
            )
        
        config.set_property(
            property_id=speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode,
            value="Continuous"
        )
                
        auto_detect_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=self.supported_languages
        )
        console.print(
            f"[bold cyan]Auto language detection enabled for: {', '.join(self.supported_languages)}[/bold cyan]"
        )

        # Add target languages
        # For bidirectional translation, add both languages as targets
        target_languages_to_add = list(self.supported_languages)
        
        for lang in self.supported_languages:
            # Use full locale code (e.g., "en-US", "es-ES") for consistency
            # Check if this language (by base code) is already in the target list
            lang_base = lang.split("-")[0].lower()
            already_added = any(
                (l.split("-")[0].lower() if "-" in l else l.lower()) == lang_base
                for l in target_languages_to_add
            )
            if not already_added:
                target_languages_to_add.append(lang)
                console.print(
                    f"[dim]Added {lang} as target language for bidirectional translation[/dim]"
                )
        
        console.print(
            f"[dim]Target languages: {target_languages_to_add}[/dim]"
        )
        for language in target_languages_to_add:
            config.add_target_language(language)

        # Voice selection for bidirectional translation
        # Note: Azure SDK only supports one voice_name, so for bidirectional we use a default
        # The voice will match one direction; the other direction will use Azure's default
        
        # For bidirectional, don't set voice_name - let Azure use default
        # Or use the primary target language's voice
        if not self.voice_name:
            # Use the original target language's voice as default
            primary_target = self.supported_languages[0]
            default_voice = self._get_default_voice_for_language(primary_target)
            config.voice_name = default_voice
            console.print(
                f"[dim]Auto-selected voice for bidirectional translation: {default_voice} "
                f"(primary target: {primary_target})[/dim]"
            )
        else:
            config.voice_name = self.voice_name

        return config, auto_detect_config

    def translate(
        self,
        audio_input: AudioInput,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> TranslationOutcome:
        """Run continuous streaming translation with automatic language detection for bidirectional pairs."""
        console.print(
            f"[bold cyan]Auto-detecting {', '.join(self.supported_languages)}[/bold cyan]"
        )

        speech_config = speechsdk.SpeechConfig(
            subscription=self.settings.subscription_key,
            region=self.settings.service_region,
        )

        # 1) Set continuous language ID BEFORE creating the recognizer
        speech_config.set_property(
            property_id=speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode,
            value="Continuous"
        )
        
        translation_config, auto_detect_config = self._build_translation_config()

        # Create recognizer with auto-detect
        recognizer = speechsdk.translation.TranslationRecognizer(
            translation_config=translation_config,
            audio_config=audio_input.config,
            auto_detect_source_language_config=auto_detect_config,
        )

        # Accumulated results for final outcome
        all_recognized_text: list[str] = []
        all_translations: dict[str, list[str]] = {lang: [] for lang in self.supported_languages}
        synthesized_chunks: list[bytes] = []
        final_reason = speechsdk.ResultReason.NoMatch
        error_details: Optional[str] = None
        recognition_done = threading.Event()
        
        # Track previous recognized text to calculate deltas
        previous_recognized_text = ""
        # Track previous translation text to calculate incremental deltas
        previous_translation_text = ""

        # Event handler for partial recognition results
        def _on_recognizing(evt: speechsdk.translation.TranslationRecognitionEventArgs) -> None:
            return
        #     nonlocal previous_translation_text
            
        #     if evt.result and evt.result.translations:
        #         # Find the translation that's different from recognized text
        #         current_translation = None
        #         for lang, translation in evt.result.translations.items():
        #             console.print(f"[dim] _on_recognizing {lang}: {translation[:50]}...[/dim]")
        #             if translation.strip().lower() != evt.result.text.strip().lower():
        #                 current_translation = translation
        #                 break
                
        #         if current_translation:
        #             # Calculate actual delta by comparing with previous translation text
        #             # Extract the delta (new portion since last event)
        #             if not previous_translation_text:
        #                 # First iteration - emit full text
        #                 delta = current_translation
        #             else:
        #                 # Find the longest common prefix to handle both extension and correction cases
        #                 # This handles cases where Azure refines the recognition (e.g., "the week" -> "last week")
        #                 common_prefix_length = 0
        #                 min_length = min(len(previous_translation_text), len(current_translation))
                        
        #                 for i in range(min_length):
        #                     if previous_translation_text[i] == current_translation[i]:
        #                         common_prefix_length = i + 1
        #                     else:
        #                         break
                        
        #                 # Extract everything after the common prefix as the delta
        #                 if common_prefix_length > 0:
        #                     delta = current_translation[common_prefix_length:]
        #                 else:
        #                     # No common prefix - might be a new utterance or major correction
        #                     # Emit the full text as delta
        #                     delta = current_translation
                    
        #             # Update previous text for next comparison
        #             previous_translation_text = current_translation
                    
        #             # Only emit if there's an actual delta
        #             if delta and on_event:
        #                 on_event({
        #                     "type": "translation.text_delta",
        #                     "delta": delta,
        #                 })

        # Event handler for final recognition results
        # This fires when Azure SDK's built-in VAD detects a complete utterance
        # (similar to Voice Live's server-side VAD commits)
        def _on_recognized(evt: speechsdk.translation.TranslationRecognitionEventArgs) -> None:
            nonlocal final_reason, previous_recognized_text, previous_translation_text
            # Reset previous text when a new utterance is recognized (new turn)
            previous_recognized_text = ""
            previous_translation_text = ""
            
            if evt.result:
                # Get detected source language if auto-detect is enabled
                # According to Azure docs: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-identification
                # For translation, access via result.properties dictionary
                detected_language = None
                if auto_detect_config:
                    # Direct property access (as shown in Microsoft docs for translation)
                    if hasattr(evt.result, 'properties') and evt.result.properties:
                        console.print(f"[bold green]Properties: {evt.result.properties}[/bold green]")
                        detected_language = evt.result.properties.get(
                            speechsdk.PropertyId.SpeechServiceConnection_AutoDetectSourceLanguageResult
                        )
                
                if evt.result.text:
                    all_recognized_text.append(evt.result.text)
                    if detected_language:
                        console.print(f"[bold green]Detected source language: {detected_language}[/bold green]")
                
                if evt.result.translations:
                    # Debug: log all available translations
                    console.print(
                        f"[dim]Available translations: {list(evt.result.translations.keys())}[/dim]"
                    )
                    for lang, trans in evt.result.translations.items():
                        console.print(f"[dim]  {lang}: {trans[:50]}...[/dim]")
                    
                    # For bidirectional translation, emit only the translation for the opposite language
                    # If English was detected, emit Spanish translation, and vice versa
                    target_translation = None
                    target_lang = None
                    
                    if detected_language and auto_detect_config:
                        # Determine the opposite language
                        detected_base = detected_language.split("-")[0].lower()
                        if detected_base == "en":
                            # English detected → get Spanish translation
                            target_lang = "es"
                        elif detected_base == "es":
                            # Spanish detected → get English translation
                            target_lang = "en"
                        
                        # Find translation for the target language
                        # IMPORTANT: Skip translations where the language matches the detected source
                        # (Azure might return the source text as a "translation" for the same language)
                        for lang, translation in evt.result.translations.items():
                            lang_base = lang.split("-")[0].lower() if "-" in lang else lang.lower()
                            
                            # Skip if this translation is for the same language as the detected source
                            # This handles cases where Azure returns the source text as a "translation"
                            if lang_base == detected_base:
                                console.print(
                                    f"[yellow]Skipping translation for {lang} (matches detected source {detected_language})[/yellow]"
                                )
                                continue
                            
                            # Only select if it matches our target language (opposite of detected)
                            # Normalize both sides for comparison (handle "en" vs "en-US", etc.)
                            if lang_base == target_lang.lower():
                                # Verify this is actually a translation (not the same as recognized text)
                                if translation.strip().lower() != evt.result.text.strip().lower():
                                    target_translation = translation
                                    target_lang = lang  # Use full language code from result
                                    console.print(
                                        f"[green]Selected translation for {target_lang}: {target_translation[:50]}...[/green]"
                                    )
                                    on_event({
                                        "type": "translation.text_delta",
                                        "delta": target_translation,
                                    })
                                    break
                                else:
                                    console.print(
                                        f"[yellow]Skipping {lang} translation (same as recognized text, likely no-op)[/yellow]"
                                    )
                        
                        if not target_translation:
                            # Fallback: try to find any translation that's not the source language
                            console.print(
                                f"[yellow]No translation found for target language '{target_lang}', "
                                f"trying fallback (detected: {detected_language}, available: {list(evt.result.translations.keys())})[/yellow]"
                            )
                            for lang, translation in evt.result.translations.items():
                                lang_base = lang.split("-")[0].lower() if "-" in lang else lang.lower()
                                # Skip source language
                                if lang_base != detected_base:
                                    # Verify it's actually different from recognized text
                                    if translation.strip().lower() != evt.result.text.strip().lower():
                                        target_translation = translation
                                        target_lang = lang
                                        console.print(
                                            f"[green]Using fallback translation for {target_lang}: {target_translation[:50]}...[/green]"
                                        )
                                        break
                            
                            if not target_translation:
                                console.print(
                                    f"[red]Error: No valid translation found "
                                    f"(detected: {detected_language}, available: {list(evt.result.translations.keys())})[/red]"
                                )
                    else:
                        # Not bidirectional - use first translation
                        if evt.result.translations:
                            target_lang, target_translation = next(iter(evt.result.translations.items()))
                    
                    # Accumulate all translations for final outcome
                    for lang, translation in evt.result.translations.items():
                        if lang in all_translations:
                            all_translations[lang].append(translation)
                    
                    # Emit the appropriate translation (opposite language for bidirectional)
                    if target_translation and on_event:
                        event_data = {
                            "type": "translation.complete",
                            "language": target_lang,
                            "text": target_translation,
                            "recognized_text": evt.result.text,
                        }
                        if detected_language:
                            event_data["detected_source_language"] = detected_language
                        on_event(event_data)
                final_reason = evt.result.reason

        # Event handler for audio synthesis
        def _on_synthesizing(evt: speechsdk.translation.TranslationSynthesisEventArgs) -> None:
            if evt.result and evt.result.audio:
                synthesized_chunks.append(evt.result.audio)
                # Emit audio delta event in ACS format
                if on_event:
                    console.print(f"[dim]Emitting synthesized audio chunk: {len(evt.result.audio)} bytes[/dim]")
                    self._emit_acs_audio_event(evt.result.audio, on_event)
                else:
                    console.print("[yellow]Warning: on_event callback not available for audio synthesis[/yellow]")

        # Event handler for cancellation/errors
        def _on_canceled(evt: speechsdk.translation.TranslationRecognitionCanceledEventArgs) -> None:
            nonlocal error_details, final_reason
            final_reason = speechsdk.ResultReason.Canceled
            if evt.reason == speechsdk.CancellationReason.Error:
                error_details = f"Error: {evt.error_details}"
            elif evt.reason == speechsdk.CancellationReason.EndOfStream:
                # End of stream is expected, not an error
                final_reason = speechsdk.ResultReason.TranslatedSpeech
            else:
                error_details = f"Cancellation reason: {evt.reason}"
            recognition_done.set()

        # Event handler for session stopped
        def _on_session_stopped(evt: speechsdk.SessionEventArgs) -> None:
            recognition_done.set()

        # Connect event handlers
        recognizer.recognizing.connect(_on_recognizing)
        recognizer.recognized.connect(_on_recognized)
        # Check if voice is configured (either provided or auto-selected)
        voice_configured = translation_config.voice_name if hasattr(translation_config, 'voice_name') else self.voice_name
        if voice_configured:
            console.print(f"[bold cyan]Voice synthesis enabled: {voice_configured}[/bold cyan]")
            recognizer.synthesizing.connect(_on_synthesizing)
        else:
            console.print("[yellow]Voice synthesis disabled - no voice configured[/yellow]")
        recognizer.canceled.connect(_on_canceled)
        recognizer.session_stopped.connect(_on_session_stopped)

        console.print(Panel.fit("Starting continuous translation stream...", style="bold magenta"))
        
        # Start continuous recognition
        recognizer.start_continuous_recognition()

        # Wait for recognition to complete (either end of stream or error)
        # Check for stop signal from audio_input if it's a stream
        try:
            while not recognition_done.is_set():
                if audio_input._stop_capture and audio_input._stop_capture.is_set():
                    # End of stream signaled, stop recognition gracefully
                    recognizer.stop_continuous_recognition_async().get()
                    break
                recognition_done.wait(timeout=0.1)
        except KeyboardInterrupt:
            console.print("[yellow]Interrupted by user[/yellow]")
            recognizer.stop_continuous_recognition_async().get()
        finally:
            # Ensure recognition is stopped
            try:
                recognizer.stop_continuous_recognition_async().get()
            except Exception:
                pass

        # Build final outcome
        recognized_text = " ".join(all_recognized_text) if all_recognized_text else None
        translations = {
            lang: " ".join(texts) if texts else ""
            for lang, texts in all_translations.items()
        }

        audio_output_path: Optional[Path] = None
        if synthesized_chunks and self.output_audio_path:
            audio_output_path = self._persist_audio(b"".join(synthesized_chunks))

        outcome = TranslationOutcome(
            recognized_text=recognized_text,
            translations=translations,
            result_reason=final_reason,
            audio_output_path=audio_output_path,
            error_details=error_details,
        )

        if final_reason == speechsdk.ResultReason.Canceled and error_details:
            console.print(Panel(error_details, title="Translation canceled", style="bold red"))
        elif final_reason == speechsdk.ResultReason.NoMatch:
            console.print(
                Panel("No speech could be recognized", title="No match", style="bold yellow")
            )
        elif recognized_text or any(translations.values()):
            self._render_success(outcome)

        return outcome

    def _emit_acs_audio_event(
        self,
        audio_bytes: bytes,
        on_event: Callable[[dict], None],
    ) -> None:
        """Emit audio event in ACS format."""
        # Default audio format for Live Interpreter (16kHz mono 16-bit PCM)
        # This matches the format expected by websocket_server
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        acs_message = {
            "kind": "AudioData",
            "audioData": {
                "timestamp": timestamp,
                "participantRawID": "live_interpreter",  # Default participant ID
                "data": audio_b64,
                "silent": False,
                "sampleRate": 16000,
                "channels": 1,
                "bitsPerSample": 16,
                "format": "pcm",
            },
        }
        
        # Emit the ACS-format message directly
        on_event(acs_message)

    def _persist_audio(self, audio_bytes: bytes) -> Path:
        output_path = self.output_audio_path
        assert output_path is not None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        console.print(
            Panel.fit(
                f"Synthesized audio saved to {output_path}",
                title="Audio output",
                style="bold green",
            )
        )
        return output_path

    def _render_success(self, outcome: TranslationOutcome) -> None:
        table = Table(title="Translation result", show_header=True, header_style="bold magenta")
        table.add_column("Type")
        table.add_column("Content", overflow="fold")

        if outcome.recognized_text:
            table.add_row("Recognized", outcome.recognized_text)

        for language, translation in outcome.translations.items():
            table.add_row(f"Translated ({language})", translation)

        if outcome.audio_output_path:
            table.add_row("Synthesized audio", str(outcome.audio_output_path))

        console.print(table)


# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Python-based proof-of-concept for Azure AI Speech Translation using the **Live Interpreter preview** with Personal Voice and **Voice Live API**. Supports real-time speech-to-speech translation from microphone, WAV, MP3, and M4A inputs with optional synthesis to neural voices.

## Essential Commands

### Environment Setup
```bash
# Install dependencies (requires Poetry)
poetry install

# Activate virtual environment
poetry shell
```

### Running Translations
```bash
# Main CLI entry point
poetry run speech-poc --help

# Basic translation (microphone → Spanish)
poetry run speech-poc --from-language en-US --to-language es

# File input with synthesis
poetry run speech-poc --input-file samples/hello.wav --from-language en-US --to-language de --voice de-DE-Hedda --output-audio artifacts/de-hello.wav

# Batch folder testing
poetry run speech-poc --input-folder samples/emotions/files --from-language en-US --to-language es --voice es-ES-ElviraNeural
```

### Development Scripts
```bash
# Resample WAV files
poetry run python scripts/resample_wav.py <input.wav> <output.wav> --target-rate 16000

# Check Voice Live WebSocket connectivity
poetry run python scripts/check_voice_live_ws.py
```

### Testing
```bash
# Run test suite
poetry run pytest
```

## Architecture

### Core Components
1. **[cli.py](src/vt_voice_translation_poc/cli.py)** - Typer-based CLI entry point
   - Handles microphone vs file input selection
   - Orchestrates single-file and batch folder translation
   - Audio preview for batch mode (`_play_audio_preview`)

2. **[providers.py](src/vt_voice_translation_poc/providers.py)** - Provider factory
   - Selects translator implementation based on `SPEECH__PROVIDER` environment variable
   - Returns `LiveInterpreterTranslator` or `VoiceLiveTranslator` via `create_translator()`

3. **[live_interpreter.py](src/vt_voice_translation_poc/live_interpreter.py)** - Live Interpreter implementation
   - Wraps Azure Speech SDK `TranslationRecognizer`
   - Registers `Synthesizing` event handler when `voice_name` is provided
   - Returns `TranslationOutcome` with success status, translations, and audio artifacts

4. **[voice_live.py](src/vt_voice_translation_poc/voice_live.py)** - Voice Live WebSocket client
   - Streams audio to Azure AI Foundry endpoint (`wss://...`)
   - Implements translation-only prompt injection
   - Handles `response.audio.delta` and `response.audio_transcript.delta` events
   - Silence detection and auto-commit based on RMS/peak thresholds

5. **[audio.py](src/vt_voice_translation_poc/audio.py)** - Audio input abstraction
   - `build_audio_input()` context manager returns `AudioInput` for microphone, WAV, MP3, or M4A
   - M4A/AAC files are converted to 16 kHz WAV via ffmpeg before streaming (saves `*_converted.wav` for debugging)
   - Streaming microphone mode uses `sounddevice` (falls back to `pyaudio` if unavailable)

6. **[config.py](src/vt_voice_translation_poc/config.py)** - Environment configuration
   - `SpeechServiceSettings.from_env()` validates credentials and provider selection
   - Loads `.env` via `python-dotenv`
   - Supports both Live Interpreter (`SPEECH__SUBSCRIPTION__KEY`, `SPEECH__SERVICE__REGION`) and Voice Live (`AZURE_AI_FOUNDRY_KEY`, `AZURE_AI_FOUNDRY_ENDPOINT`) credentials

### Translation Flow
1. CLI parses arguments (languages, voice, input source)
2. `SpeechServiceSettings.from_env()` validates credentials
3. `create_translator()` returns provider-specific implementation
4. `build_audio_input()` prepares `AudioConfig` (microphone, file, or streaming)
5. Translator executes:
   - **Live Interpreter**: Configures `TranslationRecognizer`, adds target languages, hooks `Synthesizing` event
   - **Voice Live**: Opens WebSocket, streams audio chunks, captures `response.audio.delta` and `response.audio_transcript.delta`
6. Results are returned as `TranslationOutcome` with translations dict and optional synthesized audio path

### Provider Selection
- `SPEECH__PROVIDER=live_interpreter` (default): Uses Azure Speech SDK with `TranslationRecognizer`
  - Set `SPEECH__ENDPOINT` to override regional endpoint (aligns with Microsoft quickstart)
  - Supports multiple target languages
  - Synthesizes **one** voice via Personal Voice callback
- `SPEECH__PROVIDER=voice_live`: Uses WebSocket client to Azure AI Foundry
  - Requires `AZURE_AI_FOUNDRY_KEY`, `AZURE_AI_FOUNDRY_ENDPOINT`, `AZURE_AI_FOUNDRY_MODEL`
  - Translation-only prompt enforced by default
  - Supported voices: `alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`, `shimmer`, `verse`, `marin`, `cedar`

## Configuration Reference

### Required Environment Variables (Live Interpreter)
- `SPEECH__SUBSCRIPTION__KEY` - Azure Speech subscription key
- `SPEECH__SERVICE__REGION` - Azure region (e.g., `eastus`)

### Required Environment Variables (Voice Live)
- `AZURE_AI_FOUNDRY_KEY` - Azure AI Foundry API key
- `AZURE_AI_FOUNDRY_ENDPOINT` - WebSocket endpoint (e.g., `https://demo-voice-service.services.ai.azure.com/`)

### Optional Tuning Parameters
- `AZURE_AI_FOUNDRY_COMMIT_INTERVAL=16` - Chunks per commit (≈1.6s at 16 kHz)
- `AZURE_AI_FOUNDRY_SILENCE_CHUNKS=6` - Consecutive quiet chunks before auto-commit
- `AZURE_AI_FOUNDRY_FORCE_COMMIT_CHUNKS=48` - Safety ceiling for long utterances
- `MAX_TESTING_FILES=0` - Limit batch folder runs (0 = no limit)

## Important Patterns

### M4A/AAC Conversion
M4A inputs are converted to 16 kHz mono WAV via ffmpeg **before** streaming to Voice Live. Converted files are saved as `<original>_converted.wav` for debugging. MP3 files use Azure SDK's native compressed audio streaming (no conversion required).

### Microphone Streaming (Voice Live)
When `--input-file` is omitted and `SPEECH__PROVIDER=voice_live`, the CLI streams real-time microphone audio. Press Ctrl+C to stop recording and commit. Silence detection auto-commits when `AZURE_AI_FOUNDRY_SILENCE_CHUNKS` consecutive quiet chunks are detected.

### Batch Folder Mode
`--input-folder` walks the directory tree, selects **one file per unique parent directory**, and runs a fresh translation session per file. Synthesized audio is saved alongside each input as `<original>-translation.wav`. Use `MAX_TESTING_FILES` to cap batch runs during development.

## Dependencies
- **Azure Speech SDK** (`azure-cognitiveservices-speech ^1.44.0`) - Live Interpreter provider
- **websockets** (`^11.0.3`) - Voice Live WebSocket client
- **Typer** (`^0.12.3`) + **Rich** (`^13.9.2`) - CLI and console output
- **sounddevice** (`^0.5.3`) - Microphone capture (no system dependencies required)
- **pyaudio** (`^0.2.14`, optional) - Fallback microphone library (requires PortAudio: `brew install portaudio`)
- **numpy** (`^2.1.2`) - Audio resampling in `scripts/resample_wav.py`
- **FFmpeg** (external) - M4A/AAC to WAV conversion (`brew install ffmpeg`)

## Typer/Click Compatibility
Typer 0.12.x requires Click 8.1.x. If you see `TypeError: Parameter.make_metavar() missing 1 required positional argument: 'ctx'`, run:
```bash
poetry lock && poetry install
```
This ensures Click resolves to `>=8.1.0,<8.2.0` as pinned in `pyproject.toml`.

## Project Rules (from .cursorrules)
- Never hardcode secrets; load from environment variables or `.env` (never committed)
- Use Poetry for dependency management
- Record architectural decisions in `.cursorrules` as they emerge
- When adding configuration knobs, surface them via `.env` and document in `README.md`
- Capture `response.audio_transcript.*` events when JSON output is absent (Voice Live)
- Write synthesized audio at model sample rate (24 kHz default) to preserve pitch/tempo

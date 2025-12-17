# Wolfram Voice Translation POC

Proof-of-concept that exercises Azure AI Speech Translation (Live Interpreter preview with Personal Voice) from Python, targeting rapid experimentation with speech-to-speech translation workflows. The implementation follows the Microsoft guidance for configuring translation, target languages, and event-based synthesis with Personal Voice [\[docs\]](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-translate-speech?tabs=terminal&pivots=programming-language-csharp#using-live-interpreter-preview-for-real-time-speech-to-speech-translation-with-personal-voice).

## Features
- One-shot speech translation from microphone, WAV, MP3, or M4A inputs (M4A/AAC is converted to 16 kHz WAV via ffmpeg).
- Multiple target languages per request, with optional neural synthesis for a single target voice.
- CLI built with Typer for repeatable local testing.
- Batch folder testing that walks a directory of WAV/M4A assets and submits each file in sequence.
- Rich console output summarising recognized text, translations, and synthesized audio artifacts.
- Environment-variable configuration with optional `.env` loading (no secrets committed).
- Provider abstraction to switch between Speech Translation Live Interpreter and Voice Live (future).
- **WebSocket server mode** for receiving audio data from external applications (see [WEBSOCKET_API.md](WEBSOCKET_API.md) for client integration details).

## Requirements
- Python 3.12 or higher.
- Azure subscription with access to the Speech resource and Live Interpreter preview + Personal Voice.
- Access to a compatible microphone for live capture (optional).
- MP3 support relies on the Azure SDK's compressed audio streaming; no extra codecs required.
- FFmpeg available on `PATH` (or `FFMPEG_PATH` set) to convert M4A/AAC inputs into WAV for Voice Live.
- **For Voice Live microphone streaming**: Uses `sounddevice` by default (no system dependencies required). Falls back to `pyaudio` if `sounddevice` is not available (requires PortAudio: `brew install portaudio` on macOS).

**Install FFmpeg (macOS via Homebrew):**
```bash
brew install ffmpeg
```

## Getting Started

### 1. Clone & Install Tooling

**Install Python dependencies:**
```bash
git clone <your-fork-url> vt-voice-translation-poc
cd vt-voice-translation-poc
pipx install poetry  # or `pip install --user poetry`
poetry install
poetry env activate  # enter the managed virtual environment
poetry install  # ensure numpy dependency for resampling script
```

### 2. Configure Credentials
Set your Azure Speech subscription key and region in the environment. You can export them directly or create a local `.env` file.

```bash
echo "SPEECH__SUBSCRIPTION__KEY=xxxxxxxxxxxxxxxxxxxx" >> .env
echo "SPEECH__SERVICE__REGION=eastus" >> .env
echo "SPEECH__PROVIDER=live_interpreter" >> .env  # default
echo "SPEECH__ENDPOINT=https://<your-resource>.cognitiveservices.azure.com/" >> .env  # optional: override regional endpoint (Live Interpreter preview)

# Voice Live preview credentials
echo "AZURE_AI_FOUNDRY_KEY=xxxxxxxxxxxxxxxxxxxx" >> .env
echo "AZURE_AI_FOUNDRY_ENDPOINT=https://voice-demo.cognitiveservices.azure.com/" >> .env  # use the Target URI host shown in Azure AI Foundry
echo "AZURE_AI_FOUNDRY_RESOURCE=demo-voice-service" >> .env  # optional helper
echo "AZURE_AI_FOUNDRY_MODEL=gpt-realtime-mini" >> .env       # optional override
echo "AZURE_AI_FOUNDRY_DEPLOYMENT=gpt-realtime-mini" >> .env  # optional override
echo "AZURE_AI_FOUNDRY_API_VERSION=2024-10-01-preview" >> .env
echo "AZURE_AI_FOUNDRY_OUTPUT_SAMPLE_RATE=24000" >> .env      # optional, defaults to 24 kHz
echo "AZURE_AI_FOUNDRY_VOICE=alloy" >> .env                   # optional; must be a Voice Live supported voice
echo "AZURE_AI_FOUNDRY_COMMIT_INTERVAL=16" >> .env            # optional; chunks per commit (16 ≈ 1.6 s)
echo "AZURE_AI_FOUNDRY_SILENCE_CHUNKS=6" >> .env              # optional; consecutive quiet chunks before auto-commit
echo "AZURE_AI_FOUNDRY_FORCE_COMMIT_CHUNKS=48" >> .env        # optional; safety valve to commit after long utterances
echo "MAX_TESTING_FILES=0" >> .env                            # optional; >0 limits --input-folder batch runs
```

> Never commit `.env` or any file containing secrets. Consider Azure Key Vault or your preferred secret manager for shared environments.

### 3. Explore the CLI

Print usage:
```bash
poetry run speech-poc --help
```

**Note on Click/Typer compatibility:** Typer 0.12.x expects Click 8.1.x. If you see
`TypeError: Parameter.make_metavar() missing 1 required positional argument: 'ctx'`, a newer Click release is installed. Re-run `poetry lock` followed by `poetry install` to ensure Click resolves to a version `<8.2` as pinned in `pyproject.toml`.

#### Microphone Input
```bash
poetry run speech-poc \
  --from-language en-US \
  --to-language es --to-language fr
```

#### WAV File Input
```bash
poetry run speech-poc \
  --input-file samples/hello-world.wav \
  --from-language en-US \
  --to-language es
```

#### MP3 File Input with Synthesis
```bash
poetry run speech-poc \
  --input-file samples/hello-world.mp3 \
  --from-language en-US \
  --to-language de \
  --voice de-DE-Hedda \
  --output-audio artifacts/de-hello.wav
```

When `--voice` is provided and `--output-audio` is omitted, the CLI saves synthesized audio to `artifacts/<language>-translation.wav`.

#### M4A / AAC File Input
```bash
poetry run speech-poc \
  --input-file samples/hello-world.m4a \
  --from-language en-US \
  --to-language es
```

M4A (and AAC) sources are converted to 16 kHz mono WAV using ffmpeg before streaming to Voice Live. The converted file is written to `samples/hello-world_converted.wav` so you can audition the output and compare quality.

#### Converting Audio Files to ACS Format

You can convert audio files (M4A, MP3, FLAC, OGG, AAC, WAV) to Azure Communication Services format (16 kHz mono PCM WAV).

**Using the Running Server Container (Recommended):**

The `make convert` target uses the Python conversion script inside the running server container. This provides better logging and error handling.

```bash
# Auto-generate output filename (appends _acs.wav)
make convert INPUT=evaluations/ground_truth/sample_audio.m4a
# Creates: evaluations/ground_truth/sample_audio_acs.wav

# Specify output filename
make convert INPUT=evaluations/ground_truth/sample_audio.m4a OUTPUT=evaluations/ground_truth/converted.wav
```

**Features:**
- Uses `evaluations/convert_to_acs_format.py` script
- Works with running server container (`voice-poc`)
- Supports: WAV, MP3, M4A, FLAC, OGG, AAC
- Auto-generates output filename if not specified
- Better error messages and progress output

**Output Format:**

All conversions produce WAV files matching Azure Communication Services requirements:
- **Sample Rate:** 16 kHz (16000 Hz)
- **Bits per Sample:** 16-bit
- **Channels:** 1 (mono)
- **Encoding:** Linear PCM, little-endian

**Batch Conversion:**

To convert multiple files, use the Python script directly:

```bash
# Convert all audio files in a folder
docker exec voice-poc python3 /app/evaluations/convert_to_acs_format.py \
  --folder /app/evaluations/raw_audio \
  --output-folder /app/evaluations/acs_format
```

#### Folder Batch Testing
```bash
poetry run speech-poc \
  --input-folder samples/emotions/files \
  --from-language en-US \
  --to-language es \
  --voice alloy
```

The CLI walks the directory recursively, launching a fresh translation session per WAV/M4A file. Synthesized audio (when a voice is requested) is written alongside each source clip using the pattern `<original-name>-translation.wav`. Set `MAX_TESTING_FILES` (e.g. `MAX_TESTING_FILES=5`) to cap batch runs and avoid accidental cost spikes; omit or set to `0` to process every file.

#### WebSocket Server Mode
```bash
poetry run speech-poc serve \
  --host localhost \
  --port 8765 \
  --from-language en-US \
  --to-language es \
  --voice alloy
```

Start a WebSocket server that accepts incoming connections from external applications. Clients can send audio data (binary) or control messages (JSON) for translation processing. See [WEBSOCKET_API.md](WEBSOCKET_API.md) for detailed client integration instructions and examples.

#### Exposing the WebSocket Server with ngrok (Local Development)

For local development, you may want to expose your WebSocket server to the internet using ngrok. This allows external clients to connect to your local server.

> **Getting started:** See ngrok's [macOS setup guide](https://dashboard.ngrok.com/get-started/setup/macos) (login required) for detailed installation and configuration instructions.

**Install ngrok (macOS via Homebrew):**
```bash
brew install ngrok
```

**Configure ngrok authtoken:**
```bash
ngrok config add-authtoken <your-authtoken>
```

Get your authtoken from the ngrok dashboard above.

**Start ngrok tunnel:**
```bash
ngrok http 8765
```

This creates a public URL (e.g., `https://abc123.ngrok.io`) that forwards to your local server on port 8765. External clients can connect to the WebSocket server using the ngrok URL (replace `http` with `ws` or `wss` in the connection string).

### Provider Selection
- `SPEECH__PROVIDER=live_interpreter` (default): uses the Speech SDK translation pipeline that we instrument with `TranslationRecognizer`, ideal for speech-to-speech POCs and aligned with the Live Interpreter preview [docs](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-translate-speech?tabs=terminal&pivots=programming-language-csharp#using-live-interpreter-preview-for-real-time-speech-to-speech-translation-with-personal-voice). Set `SPEECH__ENDPOINT` to your Azure AI Speech resource URL (e.g. `https://<resource>.cognitiveservices.azure.com/`) whenever you need to target a specific Live Interpreter endpoint; this mirrors the Quickstart for translating speech from a microphone using the Python SDK [docs](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/get-started-speech-translation?tabs=macos&pivots=programming-language-python#translate-speech-from-a-microphone).
- `SPEECH__PROVIDER=voice_live`: authenticates with `AZURE_AI_FOUNDRY_KEY` and calls the Voice Live endpoint (for example `https://demo-voice-service.services.ai.azure.com/`). The WebSocket client streams WAV audio to the API, prompts for JSON translations, and persists synthesized audio when a voice is selected. Model (`AZURE_AI_FOUNDRY_MODEL`) and API version (`AZURE_AI_FOUNDRY_API_VERSION`) default to `gpt-realtime-mini` / `2024-10-01-preview` but can be overridden. [docs](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live#what-is-the-voice-live-api).

#### Voice Live Preview
```bash
export SPEECH__PROVIDER=voice_live
poetry run speech-poc \
  --input-file samples/hello-world.wav \
  --from-language en-US \
  --to-language es \
  --voice alloy \
  --output-audio artifacts/es-voice-live.wav
```

Voice Live supports both file input (WAV) and real-time microphone streaming. When no `--input-file` is provided, the CLI uses pyaudio to stream microphone input in real-time. Press Ctrl+C to stop recording and commit the audio. Voice Live accepts the source sample rate directly; the synthesized speech is written using the model’s native sample rate (24 kHz by default or `AZURE_AI_FOUNDRY_OUTPUT_SAMPLE_RATE` if provided) so playback preserves pitch and speed.

> **Voice selection:** Voice Live currently exposes a limited set of built-in neural voices (`alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`, `shimmer`, `verse`, `marin`, `cedar`). If you request an unsupported voice, the CLI falls back to the service default and prints a warning. Provide one of the supported names via `--voice` or `AZURE_AI_FOUNDRY_VOICE` to control audio output.
>
> **Silence-aware commits:** by default the Voice Live streaming loop waits for roughly 6 consecutive “quiet” chunks (≈ 600 ms) before committing a translation, reducing mid-sentence splits. Tune this via `AZURE_AI_FOUNDRY_SILENCE_CHUNKS`. Long uninterrupted speech will still commit after a safety ceiling (`AZURE_AI_FOUNDRY_FORCE_COMMIT_CHUNKS`, default ≈ 4.8 s at 16 kHz) to prevent runaway buffers.

### Translation Behaviour
- The CLI injects a strict translation prompt (`Translate the user's speech from English (en-US) into … Respond only with the translated text.`) when the provider is set to Voice Live. This keeps the realtime session focused on translation rather than general chat (per the Voice Live API guidance [docs](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live#what-is-the-voice-live-api)).
- Streaming transcripts from `response.audio_transcript.delta` are combined to populate the translation table even when the API does not return JSON payloads.
- Synthesized WAV files are saved using the model’s sample rate (default 24 kHz), so playback retains the expected pitch and tempo.

## Evaluations

The `evaluations/` package contains a harness that drives the WebSocket server with curated WAV fixtures, computes metrics (WER and text similarity), and emits a PDF summary report. It assumes a WebSocket endpoint that implements the protocol described in `WEBSOCKET_API.md` (for this repo, that is typically `speech-poc serve`).

### 1. Install evaluation dependencies

Evaluation tooling is kept in an optional Poetry group so it does not affect the core runtime environment. Install it in your local environment:

```bash
poetry install --with evaluations
```

This pulls in extras such as `pyyaml` (for `test_cases.yaml`) and `reportlab` (for PDF generation).

### 2. Start the WebSocket server under test

By default, the evaluation config at `evaluations/test_cases.yaml` expects a server on `ws://localhost:8765`:

```yaml
server:
  host: "localhost"
  port: 8765
```

Start the WebSocket server using the regular CLI (for example, Live Interpreter with English→Spanish):

```bash
poetry run speech-poc serve \
  --host localhost \
  --port 8765 \
  --from-language en-US \
  --to-language es
```

Keep this server running in a separate terminal while you execute the evaluation script. If you are experimenting with a different host/port, update the `server:` section in `evaluations/test_cases.yaml` accordingly.

> For low-level debugging of WebSocket connectivity only (no translation), you can instead run `poetry run websocket-echo` and point the `server.port` in `test_cases.yaml` at that echo server.

### 3. Run the evaluation suite

With the server running and the `evaluations` group installed, run:

```bash
# Use the default YAML config at evaluations/test_cases.yaml
poetry run run-evaluations

# Or specify an alternative test cases file and enable verbose Azure payload logging
poetry run run-evaluations \
  --test-cases evaluations/test_cases.yaml \
  --verbose
```

The harness will:
- **Stream audio**: send each `audio_file` declared in `test_cases.yaml` (for example, `evaluations/ground_truth/conversation1.wav`) over the WebSocket in small chunks.
- **Capture responses**: accumulate Azure `translation.text_delta` messages into a final recognized string and collect any translation payloads.
- **Compute metrics**: compare the recognized text with the ground-truth transcript from `expected_text` (referencing files in `evaluations/ground_truth/`), and aggregate metric results across tests.
- **Generate a PDF report**: write a timestamped report such as `reports/evaluation_report_YYYYMMDD_HHMMSS.pdf` in a top-level `reports/` folder.

A non-zero exit code indicates that at least one test case failed; inspect the console summary and PDF for details.

## Project Layout
```
.
├── pyproject.toml                     # Poetry project metadata and dependencies
├── README.md
├── src/
│   └── vt_voice_translation_poc/
│       ├── __init__.py                # Package metadata
│       ├── audio.py                   # Audio source helpers (microphone, WAV, MP3)
│       ├── cli.py                     # Typer commands
│       ├── config.py                  # Environment-driven configuration loading
│       ├── providers.py               # Provider factory (Live Interpreter vs Voice Live)
│       └── live_interpreter.py         # Live Interpreter translation orchestration and synthesis handling
└── .cursorrules                       # Running list of project rules/decisions
```

## Service Comparison Snapshot
- **Live Interpreter preview**: best for orchestrating targeted translation sessions where you control the audio pipeline, add multiple target languages, and optionally synthesize a single Personal Voice using event callbacks. Requires Speech SDK usage and explicit configuration for language locales [docs](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-translate-speech?tabs=terminal&pivots=programming-language-csharp#using-live-interpreter-preview-for-real-time-speech-to-speech-translation-with-personal-voice).
- **Voice Live API**: fully managed real-time voice agent stack that bundles speech-to-text, LLM reasoning, and text-to-speech (including avatars) behind WebSocket events. Authenticated via `AZURE_AI_FOUNDRY_KEY` against the regional endpoint (for example `https://demo-voice-service.services.ai.azure.com/`). Our client streams WAV audio, requests JSON translations, and stores synthesized audio when present. It emphasizes continuous conversations, low perceived latency, and optional conversational enhancements such as noise suppression and interruption handling [docs](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live#what-is-the-voice-live-api).
- **Integration approach**: our CLI selects the provider through `SPEECH__PROVIDER`. Live Interpreter and Voice Live share the same `TranslationOutcome` abstraction so results print consistently even though the transport differs.

## Translation Flow
1. `cli.py` parses user intent (input source, languages, voice configuration).
2. `config.py` validates credentials (`SPEECH__SUBSCRIPTION__KEY`, `SPEECH__SERVICE__REGION`).
3. `audio.py` prepares an `AudioConfig` for microphone, WAV, or MP3 (the latter streamed via `PushAudioInputStream`).
4. `live_interpreter.py` wraps `TranslationRecognizer`:
   - Adds multiple target languages.
   - Hooks the `Synthesizing` event when a Personal Voice is requested.
   - Aggregates recognition, translation text, and synthesized audio (if applicable).
5. `providers.py` exposes a factory to switch between Live Interpreter and the WebSocket-powered Voice Live integration.

## Troubleshooting
- **Missing credentials**: ensure the environment variables match the Speech resource (key + region).
- **Preview access**: Live Interpreter and Personal Voice require whitelisted access; confirm feature flag availability in the Azure portal.
- **Microphone permission issues**: on macOS, allow terminal apps (or VSCode/IDE) to access the microphone.
- **MP3 playback errors**: verify the Azure Speech SDK version (>= 1.44.0); older releases may not support compressed input streams.
- **Typer/Click runtime error**: if `speech-poc` exits with `Parameter.make_metavar()` missing `ctx`, reinstall dependencies so Click downgrades to 8.1.x (`poetry lock && poetry install`), matching the compatibility constraint.
- **Voice Live WebSocket closes immediately / times out**: ensure your account has preview access and that `AZURE_AI_FOUNDRY_ENDPOINT`, `AZURE_AI_FOUNDRY_KEY`, `AZURE_AI_FOUNDRY_MODEL`, and `AZURE_AI_FOUNDRY_DEPLOYMENT` match the Target URI shown in Azure AI Foundry. The CLI prints a “Voice Live debug” panel with the computed WebSocket URL—verify it matches the portal output. If the error panel shows an HTTP status (e.g. 401/404), double-check key/region permissions.
- **Quota or throttling**: the service may reject requests when exceeding usage limits; inspect `cancellation_details`.

## Next Steps
- Add automated smoke tests with recorded fixtures once credentials are available.
- Extend to streaming conversations (continuous recognition) for true live interpretation scenarios.
- Integrate quality metrics (latency, translation confidence) and logging to persistent storage.
- Capture architecture decisions in `.cursorrules` as the prototype evolves.

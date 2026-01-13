# Voice Translation Server

**Production-ready real-time speech translation service** built on asyncio and event-driven architecture. The server listens for incoming WebSocket connections from Azure Communication Services (ACS), dynamically routes audio to translation providers, and streams translated results back to clients.

This implementation replaces the client-based model from `../src/` and will eventually become the main service for the Voice Translation platform.

## Overview

The Voice Translation Server is a **server-side WebSocket service** that:
- **Listens** for incoming ACS connections (clients connect to us, not vice versa)
- **Isolates** each connection in an independent session with dedicated pipeline
- **Routes** audio to translation providers based on session metadata or configuration
- **Streams** bidirectional audio and translation results in real-time
- **Manages** state via control plane (playback, input detection, barge-in)
- **Scales** horizontally with complete session isolation

### Key Differences from Old Implementation

| Aspect | Old (`src/`) | New (`server/`) |
|--------|--------------|-----------------|
| **Architecture** | Client-side CLI tool | Server-side WebSocket service |
| **Connection** | Connects out to services | Listens for incoming connections |
| **Session Model** | Single-session per CLI invocation | Multi-session, concurrent connections |
| **Provider Selection** | Static (CLI flag) | Dynamic (per-session metadata) |
| **Event System** | Direct callbacks | Event bus fan-out pub/sub |
| **Audio Buffering** | Simple streaming | Advanced batching with auto-commit |
| **State Management** | None | Control plane (playback/input state) |
| **Configuration** | Environment variables only | YAML + environment overrides |

## Features

### Core Capabilities

- **Real-Time Bidirectional Streaming**: Audio from ACS streamed to provider and responses streamed back with minimal latency
- **Multi-Provider Support**: Mock, OpenAI Realtime, Voice Live, Live Interpreter (v2), Role-Based composite routing
- **Dynamic Provider Selection**: Per-session provider choice via metadata, test settings, or config default
- **Session Isolation**: Complete state encapsulation prevents cross-session contamination
- **Event-Driven Architecture**: Four event buses per session with independent queues and configurable overflow
- **Audio Batching**: Configurable auto-commit on size, duration, or idle triggers with per-participant tracking
- **Playback Gate Control**: Enable/disable outbound audio dynamically for concurrent speaker management
- **Control Plane**: Tracks input state (silence/speaking), playback state machine, and barge-in logic
- **Environment Variable Overrides**: All configuration via `VT_*` prefix with automatic type conversion
- **Wire-Level Debug Logging**: Optional frame-by-frame logging for protocol debugging
- **Graceful Shutdown**: Clean session teardown with provider disconnect and resource cleanup

### Audio Processing

- **Formats**: 16 kHz or 24 kHz PCM16 (provider-specific)
- **Channels**: Mono or stereo input (converted to mono for providers)
- **Encoding**: Base64 (ACS) ↔ PCM bytes (provider)
- **Silence Detection**: RMS energy calculation (threshold: 50.0)
- **Duration Calculation**: Accurate frame-based duration tracking
- **Resampling**: Real-time sample rate conversion when needed

### Developer Experience

- **Mock Provider**: Testing without external service calls
- **Hot Config Reload**: Update settings via test control messages
- **Comprehensive Logging**: Structured logs with correlation IDs
- **Docker Compose**: One-command deployment
- **Make Targets**: Common operations (`make translation-server-up`, etc.)

## Architecture

### High-Level Flow

```
ACS WebSocket Connection
        ↓
   ACS Server (listens on port 8080)
        ↓
   Session (one per ACS connection)
        ↓
   SessionPipeline (event-driven)
        ├── Event Bus: acs_inbound_bus
        │   └── ACS message handlers (audio, metadata, control)
        ├── Event Bus: provider_outbound_bus
        │   └── Provider egress handler (sends to provider)
        ├── Event Bus: provider_inbound_bus
        │   └── Provider output handlers (transcript, audio)
        ├── Event Bus: acs_outbound_bus
        │   └── ACS gate handler (sends back to ACS)
        └── SessionControlPlane
            ├── PlaybackState (IDLE, SPEAKING, FINISHED)
            └── InputState (SILENT, SPEAKING)
```

### Core Components

| Component | Responsibility |
|-----------|---------------|
| **ACSServer** | Listen for incoming WebSocket connections, create sessions |
| **SessionManager** | Track active sessions, coordinate shutdown |
| **Session** | Manage one ACS connection, run receive/send loops |
| **SessionPipeline** | Event-driven message routing with 4 buses per session |
| **EventBus** | Fan-out pub/sub with per-handler bounded queues |
| **ProviderAdapter** | Translation provider wrapper (egress/ingress handlers) |
| **SessionControlPlane** | State tracking for playback, input, barge-in |
| **Config** | YAML + environment variable configuration management |

### Event Buses (per session)

1. **acs_inbound_bus**: ACS messages from WebSocket → handlers
2. **provider_outbound_bus**: Batched audio → provider egress
3. **provider_inbound_bus**: Provider responses → output handlers
4. **acs_outbound_bus**: Formatted responses → ACS WebSocket

Each bus supports:
- Fan-out to multiple handlers (independent queues)
- Configurable overflow policies (DROP_OLDEST, DROP_NEWEST)
- Concurrent workers per handler
- Async-safe with asyncio primitives

## Getting Started

### Prerequisites

- **Python 3.12+**
- **Docker & Docker Compose** (for containerized deployment)
- **Poetry** (for dependency management)
- **Azure Credentials** (for non-mock providers)

### Installation

```bash
# Clone repository
git clone <your-repo-url>
cd voice-translation-poc/server

# Install dependencies
poetry install

# Activate virtual environment
poetry shell
```

### Quick Start (Mock Provider)

Run the server with the mock provider (no external services required):

```bash
# Using Poetry (uses config defaults: host=0.0.0.0, port=8080)
poetry run translation-server

# Using Docker Compose
cd ..  # Return to project root
make translation-server-up
make translation-server-logs
```

The server will listen on `ws://0.0.0.0:8080` and use the mock provider by default (configurable via `.config.yml`).

### Configuration

#### Option 1: YAML Configuration

Create `.config.yml` in the `server/` directory:

```yaml
system:
  host: 0.0.0.0
  port: 8080
  log_level: INFO
  log_wire: false
  log_wire_dir: logs/server
  default_provider: mock  # or: openai, voicelive, live_interpreter

dispatch:

providers:
  mock:
    type: mock

  voicelive:
    type: voice_live
    endpoint: wss://example.cognitiveservices.azure.com/openai/realtime
    api_key: ${VOICELIVE_API_KEY}
    settings:
      model: gpt-realtime-mini
      api_version: 2024-10-01-preview
```

See `.config.example.yml` for a complete reference.

#### Option 2: Environment Variables

All configuration can be overridden via environment variables with the `VT_` prefix:

```bash
# System configuration
export VT_SYSTEM_LOG_LEVEL=DEBUG
export VT_SYSTEM_LOG_WIRE=true

# Provider selection
export VT_DISPATCH_DEFAULT_PROVIDER=voicelive

# Provider credentials
export VT_PROVIDERS_VOICELIVE_API_KEY=your-api-key
export VT_PROVIDERS_VOICELIVE_ENDPOINT=wss://your-endpoint.azure.com/openai/realtime

# Audio batching
export VT_DISPATCH_BATCHING_ENABLED=true
export VT_DISPATCH_BATCHING_MAX_BATCH_MS=200
export VT_DISPATCH_BATCHING_MAX_BATCH_BYTES=65536

# Buffering
export VT_BUFFERING_INGRESS_QUEUE_MAX=5000
export VT_BUFFERING_EGRESS_QUEUE_MAX=5000
```

See [ENV_CONFIG.md](ENV_CONFIG.md) for complete environment variable reference.

### Running the Server

#### Development Mode

```bash
# With default config (.config.yml)
poetry run translation-server

# With custom config
poetry run translation-server --config custom.yml

# With multiple configs (merged left-to-right)
poetry run translation-server --config base.yml --config overrides.yml

# Override host/port via environment variables
VT_SYSTEM_PORT=9000 poetry run translation-server
```

#### Docker Mode

```bash
# Start server
make translation-server-up

# View logs
make translation-server-logs

# Shell access
make translation-server-bash

# Restart server
make translation-server-restart

# Stop server
make translation-server-down
```

## Providers

The server supports multiple translation providers with dynamic selection per session.

### Provider Selection Priority

1. **Test Settings**: `control.test.settings` message with `provider` field
2. **Session Metadata**: `metadata.provider` from ACS connection
3. **Feature Flags**: `metadata.feature_flags.use_voicelive` (legacy)
4. **Config Default**: `system.default_provider` in config

### Available Providers

#### 1. Mock Provider

**Type**: `mock`

**Use Case**: Development and testing without external service calls

**Configuration**:
```yaml
providers:
  mock:
    type: mock
```

**Behavior**:
- Simulates translation with 50ms delay
- Generates partial and final transcripts
- No credentials required
- Ideal for integration testing

#### 2. OpenAI Realtime

**Type**: `openai`

**Technology**: OpenAI Realtime API (WebSocket)

**Configuration**:
```yaml
providers:
  openai:
    type: openai
    endpoint: wss://api.openai.com/v1/realtime
    api_key: ${OPENAI_API_KEY}
    settings:
      deployment: gpt-4o-realtime-preview
      api_version: 2024-10-01-preview
      model: gpt-4o-realtime-preview-2024-10-01
```

**Features**:
- GPT-based real-time translation
- 24 kHz PCM16 audio format
- Server VAD (Voice Activity Detection)
- Customizable system prompts

**Environment Variables**:
```bash
VT_PROVIDERS_OPENAI_API_KEY=your-api-key
VT_PROVIDERS_OPENAI_ENDPOINT=wss://api.openai.com/v1/realtime
```

#### 3. Voice Live

**Type**: `voice_live`

**Technology**: Azure AI Foundry Realtime API

**Configuration**:
```yaml
providers:
  voicelive:
    type: voice_live
    endpoint: wss://example.cognitiveservices.azure.com/openai/realtime
    api_key: ${VOICELIVE_API_KEY}
    region: eastus
    resource: voicelive-resource
    settings:
      model: gpt-realtime-mini
      api_version: 2024-10-01-preview
      deployment: gpt-realtime-mini
      session_options:
        voice: alloy
        temperature: 0.8
```

**Features**:
- GPT-based translation with Azure integration
- 24 kHz PCM16 audio format
- Built-in neural voices (alloy, ash, coral, echo, etc.)
- Conversational AI capabilities

**Environment Variables**:
```bash
VT_PROVIDERS_VOICELIVE_API_KEY=your-api-key
VT_PROVIDERS_VOICELIVE_ENDPOINT=wss://your-endpoint.azure.com/openai/realtime
VT_PROVIDERS_VOICELIVE_SETTINGS_MODEL=gpt-realtime-mini
VT_PROVIDERS_VOICELIVE_SETTINGS_SESSION_OPTIONS_VOICE=alloy
```

#### 4. Live Interpreter (v2)

**Type**: `live_interpreter`

**Technology**: Azure Speech SDK v2 Universal Endpoint

**Configuration**:
```yaml
providers:
  live_interpreter:
    type: live_interpreter
    region: eastus2
    api_key: ${LIVE_INTERPRETER_API_KEY}
    settings:
      languages: [en-US, es-ES, fr-FR, de-DE]
      voice: es-ES-ElviraNeural
```

**Features**:
- **Automatic language detection** (76+ languages)
- No source language configuration needed
- Real-time language switching within session
- Neural voice synthesis
- 16 kHz PCM16 audio format

**Environment Variables**:
```bash
VT_PROVIDERS_LIVE_INTERPRETER_API_KEY=your-api-key
VT_PROVIDERS_LIVE_INTERPRETER_REGION=eastus2
VT_PROVIDERS_LIVE_INTERPRETER_SETTINGS_VOICE=es-ES-ElviraNeural
```

#### 5. Role-Based Provider

**Type**: `role_based`

**Use Case**: Bidirectional translation with different providers per participant role

**Configuration**:
```yaml
providers:
  live_interpreter_spanish:
    type: live_interpreter
    region: eastus2
    api_key: ${LIVE_INTERPRETER_API_KEY}
    settings:
      languages: [en-US, es-ES]
      voice: es-ES-ElviraNeural

  live_interpreter_english:
    type: live_interpreter
    region: eastus2
    api_key: ${LIVE_INTERPRETER_API_KEY}
    settings:
      languages: [en-US, es-ES]
      voice: en-US-JennyNeural

  role_based:
    type: role_based
    settings:
      role_providers:
        agent: live_interpreter_spanish    # Agent hears Spanish audio
        caller: live_interpreter_english   # Caller hears English audio
```

**Behavior**:
- Routes messages by participant role (`agent`, `caller`)
- Each role gets dedicated provider instance
- Enables asymmetric translation (different voices/languages per role)

#### 6. Participant-Based Provider

**Type**: `participant_based`

**Use Case**: Dedicated provider instance per participant

**Configuration**:
```yaml
providers:
  live_interpreter:
    type: live_interpreter
    region: eastus2
    api_key: ${LIVE_INTERPRETER_API_KEY}
    settings:
      languages: [en-US, es-ES]
      voice: es-ES-ElviraNeural

  participant_based:
    type: participant_based
    settings:
      provider: live_interpreter
```

**Behavior**:
- Creates provider instances on first message per participant
- Routes each participant's audio to its dedicated provider
- Shares the inbound bus for provider output events

## Audio Batching and Buffering

### Auto-Commit Triggers

Audio is buffered per participant and automatically committed when:

1. **Size Threshold**: Accumulated bytes >= `max_batch_bytes` (default: 65536)
2. **Duration Threshold**: Accumulated duration >= `max_batch_ms` (default: 200ms)
3. **Idle Timeout**: No new audio for >= `idle_timeout_ms` (default: 500ms)

### Configuration

```yaml
dispatch:
  batching:
    enabled: true
    max_batch_ms: 200
    max_batch_bytes: 65536
    idle_timeout_ms: 500
```

Or via environment:
```bash
VT_DISPATCH_BATCHING_ENABLED=true
VT_DISPATCH_BATCHING_MAX_BATCH_MS=300
VT_DISPATCH_BATCHING_MAX_BATCH_BYTES=32768
VT_DISPATCH_BATCHING_IDLE_TIMEOUT_MS=1000
```

### Silence Detection

Audio chunks are analyzed for silence using RMS energy calculation:
- **Threshold**: 50.0
- **Metadata**: Each commit includes `is_silence` flag
- **Use Case**: Control plane can use silence for state transitions

## Session Control Plane

The control plane tracks session state for intelligent orchestration.

### Playback State

**States**:
- `IDLE`: No audio in playback
- `SPEAKING`: Audio being sent to ACS
- `FINISHED`: Provider sent done signal
- `GATE_CLOSED`: Playback gate explicitly closed

**Transitions**:
- Provider audio → `SPEAKING`
- Provider done → `FINISHED`
- Idle timeout (500ms) → `IDLE`
- Gate closed → `GATE_CLOSED`

### Input State

**States**:
- `SILENT`: No voice detected
- `SPEAKING`: Voice detected

**Transitions**:
- Voice detected (with 100ms hysteresis) → `SPEAKING`
- Silence detected (350ms threshold) → `SILENT`

### Control Actions

The control plane can trigger pipeline actions:
- `set_outbound_gate(enabled)`: Open/close playback gate
- `cancel_provider_response(response_id)`: Cancel in-flight response
- `drop_outbound_audio(reason)`: Drop buffered audio
- `flush_inbound_buffers(participant_id)`: Clear audio buffers

## Development

### Project Structure

```
server/
├── README.md                          # This file
├── ENV_CONFIG.md                      # Environment variable reference
├── ARCHITECTURE.md                    # Detailed architecture documentation
├── .config.example.yml                # Example configuration
├── main.py                            # Entry point
├── config.py                          # Configuration management
├── core/                              # Core infrastructure
│   ├── acs_server.py                 # WebSocket server
│   ├── event_bus.py                  # Event bus implementation
│   ├── queues.py                     # Bounded queues
│   └── websocket_server.py           # WebSocket wrapper
├── session/                           # Session management
│   ├── session.py                    # Session lifecycle
│   ├── session_manager.py            # Session tracking
│   ├── session_pipeline.py           # Event-driven pipeline
│   └── control/                      # Control plane
│       ├── session_control_plane.py  # State tracking
│       ├── playback_state.py         # Playback state machine
│       └── input_state.py            # Input state machine
├── gateways/                          # Protocol adapters
│   ├── acs/                          # ACS gateway (inbound/outbound)
│   └── provider/                     # Provider gateway
├── providers/                         # Translation providers
│   ├── provider_factory.py           # Provider selection logic
│   ├── mock_provider.py              # Mock (testing)
│   ├── openai/                       # OpenAI Realtime
│   ├── voice_live/                   # Voice Live
│   ├── live_interpreter/             # Live Interpreter v2
│   ├── role_based_provider.py        # Role-based routing
│   └── participant_based_provider.py # Participant-based routing
├── models/                            # Data models
├── audio/                             # Audio utilities
├── services/                          # Business logic
└── utils/                             # Utilities
```

### Running Tests

```bash
# Run all tests
docker compose exec vt-app python -m pytest

# Run specific test file
docker compose exec vt-app python -m pytest server/utils/test_env_config.py -v

# Run with coverage
docker compose exec vt-app python -m pytest --cov=server
```

### Wire-Level Debugging

Enable wire logging to see all WebSocket frames:

```bash
# Via environment
export VT_SYSTEM_LOG_WIRE=true
export VT_SYSTEM_LOG_WIRE_DIR=logs/debug

# Via YAML
system:
  log_wire: true
  log_wire_dir: logs/debug
```

## Troubleshooting

### Common Issues

#### 1. Server Won't Start

**Symptom**: Server exits immediately with config error

**Solution**:
```bash
# Check configuration
poetry run translation-server --config .config.yml

# Validate environment variables
env | grep VT_

# Check logs
make translation-server-logs
```

#### 2. Provider Connection Fails

**Symptom**: Session starts but provider never connects

**Solution**:
- Verify API key is correct
- Check endpoint URL format (must be `wss://`)
- Enable wire logging: `VT_SYSTEM_LOG_WIRE=true`
- Check provider-specific logs in `logs/server/`

#### 3. Audio Not Flowing

**Symptom**: ACS connects but no translation responses

**Solution**:
- Check that audio format is PCM16 (16-bit)
- Verify sample rate (16 kHz or 24 kHz)
- Check batching configuration (timeouts may be too high)
- Look for `auto_commit_triggered` log messages

## Additional Resources

- **Architecture Documentation**: [ARCHITECTURE.md](ARCHITECTURE.md)
- **Environment Variables**: [ENV_CONFIG.md](ENV_CONFIG.md)
- **Provider Docs**:
  - [OpenAI Realtime API](https://platform.openai.com/docs/guides/realtime)
  - [Azure Voice Live](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live)
  - [Azure Live Interpreter](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-translate-speech)

---

**Note**: This server implementation is under active development and will eventually replace the client-based service in `../src/`. Configuration and APIs are subject to change.

# Translation Service Server

Real-time speech translation service with bidirectional streaming architecture. Receives audio from Azure Communication Services (ACS) via WebSocket, dispatches to translation providers (VoiceLive, Live Interpreter, Mock), and delivers translated results back to ACS.

## Quick Start

### 1. Install Dependencies

```bash
# Requires Python 3.10+
pip install -r requirements.txt
```

### 2. Configure

Create `config.yaml` (or use default config):

```yaml
server:
  host: "0.0.0.0"
  port: 8080

dispatch:
  provider: "mock"  # mock, voicelive, live_interpreter
  batching:
    enabled: true
    max_batch_ms: 200
    max_batch_bytes: 65536
    idle_timeout_ms: 500

providers:
  voicelive:
    endpoint: "${VOICELIVE_ENDPOINT}"
    api_key: "${VOICELIVE_API_KEY}"

buffering:
  ingress_queue_max: 1000
  egress_queue_max: 1000
  overflow_policy: "DROP_OLDEST"
```

### 3. Run Server

```bash
# With default config (Mock provider)
python -m server.main

# With custom config
python -m server.main --config config.yaml

# Custom host/port
python -m server.main --host 0.0.0.0 --port 8080
```

Server listens for incoming ACS WebSocket connections on the specified port.

## Architecture

The service uses a **WebSocket server** architecture:

```
ACS Client → WebSocket → Session → Participant Pipeline(s) → Provider → Translation
                                                                ↓
ACS Client ← WebSocket ← Session ← Participant Pipeline(s) ← Provider ← Result
```

### Key Components

- **ACS Server**: WebSocket server (`websockets.serve`) listening on port 8080
- **Session Manager**: Tracks active ACS connections
- **Session**: One per ACS connection, routes messages to pipelines
- **Participant Pipeline**: Translation pipeline (one or more per session)
  - Shared mode (default): All participants share one pipeline
  - Per-participant mode: Each participant gets isolated pipeline
- **Provider Adapters**: VoiceLive, Mock, Live Interpreter (future)

### Routing Strategies

Routing strategy is selected dynamically from **first ACS message metadata**:

#### Shared Pipeline (Default)

All participants share one pipeline. Most efficient.

```json
{
  "metadata": {"routing": "shared"},
  "audioData": {...}
}
```

#### Per-Participant Pipeline

Each participant gets independent pipeline with own provider.

```json
{
  "metadata": {
    "routing": "per_participant",
    "participant_providers": {
      "user-123": "voicelive",
      "user-456": "mock"
    }
  },
  "audioData": {...}
}
```

### Provider Selection

Provider is selected from metadata (defaults to config):

```json
{
  "metadata": {"provider": "voicelive"},
  "audioData": {...}
}
```

Per-participant override:

```json
{
  "metadata": {
    "routing": "per_participant",
    "participant_providers": {
      "user-123": "voicelive",
      "user-456": "mock"
    }
  }
}
```

## Testing

### With Mock Provider (No External Calls)

```bash
python -m server.main
```

Mock adapter generates fake translations:
- Partial: `[mock partial] processing commit abc...`
- Final: `[mock final] translated audio for commit abc`

### Connecting a Test Client

```python
import asyncio
import websockets
import json

async def test_client():
    async with websockets.connect("ws://localhost:8080") as ws:
        # Send audio message
        message = {
            "kind": "AudioData",
            "metadata": {"routing": "shared", "provider": "mock"},
            "audioData": {
                "participantRawID": "test-user",
                "data": "UklGRiQBAABXQVZFZm10IBAAAA...",  # base64 audio
                "sampleRate": 16000,
                "channels": 1,
                "bitsPerSample": 16
            }
        }
        await ws.send(json.dumps(message))

        # Receive translation
        response = await ws.recv()
        print(f"Received: {response}")

asyncio.run(test_client())
```

## Auto-Commit Behavior

Audio is automatically committed (sent to provider) on three triggers:

1. **Size**: When base64 buffer ≥ 65,536 bytes
2. **Duration**: When audio ≥ 200ms
3. **Idle**: When no messages for 500ms

Each participant maintains independent state.

## Configuration

### Environment Variables

```bash
# VoiceLive
export VOICELIVE_ENDPOINT="wss://voicelive.example.com/v1/realtime"
export VOICELIVE_API_KEY="your-api-key"
```

### Config File Schema

See `config.example.yaml` for full schema.

## Logging

Structured logs show the full pipeline:

```
2025-12-20 10:30:00 [INFO] acs_server: ACS server listening on 0.0.0.0:8080
2025-12-20 10:30:01 [INFO] acs_server: New ACS connection from 192.168.1.100:54321
2025-12-20 10:30:01 [INFO] session: Created session abc-123
2025-12-20 10:30:01 [INFO] session: Session abc-123 routing: shared
2025-12-20 10:30:01 [INFO] participant_pipeline: Participant shared provider started: mock
2025-12-20 10:30:02 [INFO] translation: Auto-commit triggered for ('sess-abc', 'part-001'): duration_threshold (220.5ms >= 200ms)
2025-12-20 10:30:02 [INFO] provider_result: Provider result partial=False session=sess-abc participant=part-001 text=Hello translated
```

## Directory Structure

```
server/
├── session/
│   ├── __init__.py
│   ├── participant_pipeline.py  # Translation pipeline per participant
│   ├── session.py               # Manages one ACS connection
│   └── session_manager.py       # Tracks active sessions
├── adapters/
│   ├── adapter_factory.py       # Factory for creating providers
│   ├── mock_adapter.py          # Mock provider (testing)
│   └── voicelive_adapter.py     # VoiceLive bidirectional streaming
├── handlers/
│   ├── audit.py                 # Logs all ACS messages
│   ├── translation.py           # Buffers audio, auto-commits
│   └── provider_result.py       # Formats provider responses
├── models/
│   └── messages.py              # AudioRequest, TranslationResponse
├── services/
│   └── audio_duration.py        # Audio duration calculator
├── acs_server.py                # WebSocket server (main component)
├── main.py                      # Entry point
├── config.py                    # Configuration models
├── envelope.py                  # Internal message format
├── event_bus.py                 # Fan-out pub/sub bus
├── queues.py                    # Bounded queue with overflow policies
├── ARCHITECTURE.md              # Detailed architecture documentation
└── README.md                    # This file
```

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)**: Complete architecture design with detailed component descriptions, message flow examples, and routing strategies
- **[README.md](README.md)**: This file - quick start and usage guide

## Advantages

1. **Server-Side Architecture**: Correct WebSocket pattern (listens for ACS connections)
2. **Dynamic Routing**: Choose shared vs per-participant based on metadata
3. **Dynamic Provider Selection**: Per-session, per-participant, per-customer
4. **Complete Isolation**: Sessions and participants don't interfere
5. **Scalability**: Each session/participant pipeline runs independently
6. **Flexibility**: Different providers for different sessions/participants simultaneously
7. **Efficiency**: Default shared mode avoids overhead when isolation not needed
8. **Easy Testing**: Mock provider with no external calls

## Migration from Old Architecture

The new architecture replaces:
- ❌ `service.py` (client-based) → ✅ `acs_server.py` + `session/` (server-based)
- ❌ `adapters/ingress.py` → ✅ Session receive loop
- ❌ `adapters/egress.py` → ✅ Session send loop
- ❌ Global event buses → ✅ Per-participant pipelines

Unchanged (reused as-is):
- ✅ All handlers (audit, translation, provider_result)
- ✅ Provider adapters (VoiceLiveAdapter, MockAdapter)
- ✅ Models (Envelope, AudioRequest, TranslationResponse)
- ✅ Services (AudioDurationCalculator)
- ✅ Config, EventBus, Queues

## Troubleshooting

### Server won't start

- Check port 8080 is not in use: `lsof -i :8080`
- Try different port: `python -m server.main --port 8081`

### No translations appearing

- Check logs for auto-commit triggers
- Verify audio format (16kHz mono 16-bit PCM, base64-encoded)
- Try increasing batch thresholds in config

### Provider connection fails

- Check environment variables are set
- Verify provider endpoint is reachable
- Try Mock provider first to isolate issue

## License

MIT

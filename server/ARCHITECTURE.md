# Server Architecture Design (From Scratch)

## Core Concept

The service is a **WebSocket server** that listens for incoming ACS connections. Each connection represents an independent translation session with its own state, gateways, and provider connection.

## Key Principles

1. **Server-Side Architecture**: Service listens for ACS connections (not connecting out)
2. **Session Isolation**: Each ACS connection is completely independent
3. **Dynamic Routing Strategy**: Message routing chosen based on metadata from first ACS message:
   - **Shared Pipeline** (default): All participants share one pipeline
   - **Per-Participant Pipeline**: Each participant gets isolated pipeline
4. **Dynamic Provider Selection**: Provider chosen based on metadata from first ACS message
5. **Bidirectional Streaming**: Symmetric flow in both directions (ACS ↔ Provider)

## Architecture Overview

```
                    ┌──────────────────────────┐
                    │   ACS WebSocket Server   │
                    │  (websockets.serve:8080) │
                    └────────────┬─────────────┘
                                 │ Incoming connections
                    ┌────────────┴─────────────┐
                    │    Session Manager       │
                    │  (tracks active sessions)│
                    └────────────┬─────────────┘
                                 │ Creates session per connection
                    ┌────────────┴─────────────┐
                    │        Session           │
                    │  (one per ACS connection)│
                    └────────────┬─────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
                    ▼                         ▼
              ACS Receive                ACS Send
                 Loop                      Loop
                    │                         ▲
                    │ Routes by               │
                    │ participant_id          │
                    ▼                         │
         ┌──────────────────────┐            │
         │ Participant Pipelines│            │
         │  (per participant_id)│            │
         └──────────┬───────────┘            │
                    │                         │
    ┌───────────────┼────────────┐           │
    ▼               ▼            ▼           │
Participant     Participant  Participant     │
  "user-123"     "user-456"   "user-789"     │
    │               │            │           │
    ▼               ▼            ▼           │
Event Buses    Event Buses  Event Buses      │
(4 buses)      (4 buses)    (4 buses)        │
    │               │            │           │
    ▼               ▼            ▼           │
Gateways       Gateways     Gateways         │
(4 gateways)   (4 gateways) (4 gateways)     │
    │               │            │           │
    ▼               ▼            ▼           │
Provider       Provider     Provider         │
VoiceLive      LiveInterp   Mock             │
    │               │            │           │
    └───────────────┴────────────┴───────────┘
                    │
                    └─────► Merged back to ACS send loop
```

**Key Enhancement**: Each participant gets their own isolated pipeline with independent:
- Event buses (4 per participant)
- Gateways (4 instances per participant)
- Provider (can be different per participant)
- Auto-commit state and buffering

## Components

### 1. ACS Server (`acs_server.py`)

**Responsibility**: WebSocket server that accepts incoming ACS connections.

```python
class ACSServer:
    def __init__(self, config: Config, host: str = "0.0.0.0", port: int = 8080):
        self.config = config
        self.host = host
        self.port = port
        self.session_manager = SessionManager(config)

    async def start(self):
        """Start WebSocket server."""
        async with websockets.serve(
            self._handle_connection,
            self.host,
            self.port
        ):
            logger.info(f"ACS server listening on {self.host}:{self.port}")
            await asyncio.Future()  # Run forever

    async def _handle_connection(
        self,
        websocket: WebSocketServerProtocol,
        path: str
    ):
        """Handle incoming ACS connection."""
        session = await self.session_manager.create_session(websocket)
        try:
            await session.run()
        except Exception as e:
            logger.exception(f"Session {session.session_id} error: {e}")
        finally:
            await self.session_manager.remove_session(session.session_id)
```

**Key Points**:
- Uses `websockets.serve()` to listen for connections
- Each connection handed to `SessionManager`
- Session runs until ACS disconnects

### 2. Session Manager (`session_manager.py`)

**Responsibility**: Tracks active sessions, creates/removes sessions.

```python
class SessionManager:
    def __init__(self, config: Config):
        self.config = config
        self.sessions: Dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        websocket: WebSocketServerProtocol
    ) -> Session:
        """Create new session for ACS connection."""
        async with self._lock:
            session_id = str(uuid.uuid4())
            session = Session(
                session_id=session_id,
                websocket=websocket,
                config=self.config
            )
            self.sessions[session_id] = session
            logger.info(f"Created session {session_id}")
            return session

    async def remove_session(self, session_id: str):
        """Remove session and cleanup."""
        async with self._lock:
            session = self.sessions.pop(session_id, None)
            if session:
                await session.cleanup()
                logger.info(f"Removed session {session_id}")

    async def shutdown_all(self):
        """Shutdown all active sessions."""
        async with self._lock:
            for session in list(self.sessions.values()):
                await session.cleanup()
            self.sessions.clear()
```

**Key Points**:
- One session per ACS connection
- Thread-safe session tracking
- Handles cleanup on disconnect

### 3. Session Pipeline (`session_pipeline.py`)

**Responsibility**: Manages translation pipeline for ONE ACS session and accepts events from all participants.

```python
class SessionPipeline:
    """Translation pipeline shared across all participants in an ACS session."""

    def __init__(
        self,
        session_id: str,
        config: Config,
        provider_name: str,
        metadata: Dict[str, Any],
        translation_settings: Dict[str, Any],
    ):
        self.session_id = session_id
        self.config = config
        self.provider_name = provider_name
        self.metadata = metadata
        self.translation_settings = translation_settings

        self.acs_inbound_bus = EventBus(f"acs_in_{session_id}")
        self.provider_outbound_bus = EventBus(f"prov_out_{session_id}")
        self.provider_inbound_bus = EventBus(f"prov_in_{session_id}")
        self.acs_outbound_bus = EventBus(f"acs_out_{session_id}")

    async def start(self):
        """Start session pipeline: create provider and register handlers."""
        self.provider_adapter = ProviderFactory.create_provider(
            config=self.config,
            provider_name=self.provider_name,
            outbound_bus=self.provider_outbound_bus,
            inbound_bus=self.provider_inbound_bus,
            session_metadata=self.metadata,
        )
        await self.provider_adapter.start()
        await self._register_handlers()
```

**Key Points**:
- Single pipeline per ACS session
- Event buses are scoped to the session
- Provider instance is shared by all participants in the session

### 4. Session (`session.py`)

**Responsibility**: Manages one ACS connection, initializes a single session-scoped pipeline, and forwards all inbound events to it.

```python
class Session:
    def __init__(
        self,
        session_id: str,
        websocket: WebSocketServerProtocol,
        config: Config,
        connection_ctx: ConnectionContext,
    ):
        self.session_id = session_id
        self.websocket = websocket
        self.config = config
        self.connection_ctx = connection_ctx
        self.canonical_session_id = connection_ctx.call_connection_id or connection_ctx.ingress_ws_id

        self.metadata: Dict[str, Any] = {}
        self.translation_settings: Dict[str, Any] = {}
        self.pipeline: Optional[SessionPipeline] = None

        self._initialized = False
        self._sequence = 0
        self._receive_task: Optional[asyncio.Task] = None
        self._send_task: Optional[asyncio.Task] = None

    async def _acs_receive_loop(self):
        """Receive messages from ACS WebSocket and route to pipeline."""
        async for raw_message in self.websocket:
            data = json.loads(raw_message)
            if not self._initialized:
                await self._initialize_from_first_message(data)

            self._sequence += 1
            event = GatewayInputEvent.from_acs_frame(
                data,
                sequence=self._sequence,
                ctx=self.connection_ctx,
            )
            await self._route_message(event)

    async def _route_message(self, envelope: GatewayInputEvent):
        if self.pipeline is None:
            return
        await self.pipeline.process_message(envelope)

    async def _initialize_from_first_message(self, data: Dict[str, Any]):
        self.metadata = data.get("metadata", {})
        provider_name = self._select_provider(self.metadata)

        self.pipeline = SessionPipeline(
            session_id=self.canonical_session_id,
            config=self.config,
            provider_name=provider_name,
            metadata=self.metadata,
            translation_settings=self.translation_settings,
        )
        await self.pipeline.start()
        await self._subscribe_to_pipeline_output(self.pipeline)
        self._initialized = True

    async def _subscribe_to_pipeline_output(self, pipeline: SessionPipeline):
        async def send_to_acs(payload: Dict[str, Any]):
            await self.websocket.send(json.dumps(payload))

        class ACSWebSocketSender(Handler):
            async def handle(self, payload: Dict[str, Any]):
                await send_to_acs(payload)

        await pipeline.acs_outbound_bus.register_handler(
            HandlerConfig(
                name=f"acs_websocket_send_{pipeline.pipeline_id}",
                queue_max=1000,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1
            ),
            ACSWebSocketSender(
                HandlerSettings(
                    name=f"acs_websocket_send_{pipeline.pipeline_id}",
                    queue_max=1000,
                    overflow_policy="DROP_OLDEST"
                )
            )
        )

    async def cleanup(self):
        if self._receive_task:
            self._receive_task.cancel()
        if self._send_task:
            self._send_task.cancel()
        if self.pipeline:
            await self.pipeline.cleanup()
        await self.websocket.close()
```

**Key Points**:
- Exactly one pipeline per ACS WebSocket session
- Participant identity is preserved on envelopes; the pipeline reads it from the event payloads
- Outbound ACS messaging uses the pipeline's `acs_outbound_bus` with a single WebSocket sender subscription
- Cleanup covers the session tasks, the session pipeline, and the WebSocket connection

### 5. Main Entry Point (`main.py`)

```python
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Load config (single file)
    config = Config.from_yaml([Path("config.yaml")])

    # Or load and merge multiple configs
    config = Config.from_yaml([Path("base.yaml"), Path("overrides.yaml")])

    # Create and start server
    server = ACSServer(
        config=config,
        host="0.0.0.0",
        port=8080
    )

    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await server.session_manager.shutdown_all()

if __name__ == "__main__":
    asyncio.run(main())
```

## Routing Strategy Comparison

### Scenario: 3-Participant Conference Call

#### Shared Pipeline Mode (Default)

```
First message metadata: {"routing": "shared"}

Session creates:
  └── Shared Pipeline (all participants)
      ├── Event buses (4)
      ├── Handlers (4)
      └── Provider: VoiceLive

Message flow:
  Participant A audio → Shared Pipeline → VoiceLive
  Participant B audio → Shared Pipeline → VoiceLive (same connection)
  Participant C audio → Shared Pipeline → VoiceLive (same connection)

Resources: 1 pipeline, 1 provider connection, 4 event buses
```

**Pros**:
- Minimal overhead
- Efficient resource usage
- Simple state management

**Cons**:
- All participants must use same provider
- No isolation if one participant causes issues
- Shared auto-commit buffers (may not be ideal for all scenarios)

#### Session Pipeline Mode

```
First message metadata: {
  "routing": "shared" // routing hints are ignored; one pipeline per session
}

Session constructs one pipeline and all participants share it:
  └── Session Pipeline
      ├── Event buses (4)
      ├── Handlers (4)
      └── Provider: VoiceLive

Message flow:
  Participant A audio → Session Pipeline → VoiceLive
  Participant B audio → Session Pipeline → VoiceLive
  Participant C audio → Session Pipeline → VoiceLive

Resources: 1 pipeline, 1 provider connection, 4 event buses
```

**Pros**:
- Minimal overhead while supporting multiple participants
- Simple state management; participant_id stays on the envelope
- Outbound ACS wiring stays centralized

**Cons / Notes**:
- Provider choice is made once per session (config/metadata driven)
- Provider fan-out to multiple downstream clients is handled separately

## Message Flow Examples

### Example 1: Shared Pipeline Flow

**First Message**:
```json
{
  "kind": "AudioData",
  "metadata": {"routing": "shared", "provider": "voicelive"},
  "audioData": {
    "participantRawID": "user-123",
    "data": "UklGR..."
  }
}
```

**Flow**:
1. Session receives message
2. Initializes the session pipeline with VoiceLive provider (from metadata)
3. All subsequent messages (any participant) → session pipeline
4. Single VoiceLive connection handles all participants

### Example 2: Multi-Participant Session Flow

**First Message** (participant A):
```json
{
  "kind": "AudioData",
  "metadata": {"provider": "voicelive"},
  "audioData": {"participantRawID": "user-123", "data": "UklGR..."}
}
```

**Second Message** (participant B):
```json
{
  "kind": "AudioData",
  "metadata": {"provider": "voicelive"},
  "audioData": {"participantRawID": "user-456", "data": "UklGR..."}
}
```

**Flow**:
1. Session receives first message and starts one session pipeline with VoiceLive provider
2. user-123 audio routed to the pipeline; participant_id stays on the envelope
3. user-456 message arrives later; routed to the same pipeline
4. Provider receives both participants' audio streams on a single connection

### Example 3: Complete End-to-End Flow

```
1. ACS connects
   ↓
2. Session created
   ↓
3. ACS sends first message:
   {
     "kind": "AudioData",
     "metadata": {"provider": "voicelive", "customer_id": "acme"},
     "audioData": {"data": "...", "participantRawID": "user-123"}
   }
   ↓
4. Session extracts metadata → selects "voicelive" provider
   ↓
5. VoiceLiveProvider created and started
   ↓
6. Handlers registered on session buses
   ↓
7. Message converted to GatewayInputEvent, published to acs_inbound_bus
   ↓
8. AuditHandler logs it
   ↓
9. TranslationDispatchHandler buffers audio
   ↓
10. Auto-commit triggered (size/duration/idle)
    ↓
11. AudioRequest published to provider_outbound_bus
    ↓
12. VoiceLiveProvider egress loop consumes, sends to VoiceLive WebSocket
    ↓
13. VoiceLive responds with translation/audio deltas
    ↓
14. VoiceLiveProvider ingress loop receives, publishes ProviderOutputEvent
    ↓
15. ProviderResultHandler consumes, converts to ACS format
    ↓
16. Published to acs_outbound_bus
    ↓
17. ACS send loop consumes, sends to ACS WebSocket
    ↓
18. ACS receives translation result
```

## Key Differences from Previous Design

### Previous Design (Incorrect)
- ❌ ACS gateways were WebSocket **clients** (connecting out)
- ❌ Global event buses shared across all sessions
- ❌ Provider selected globally via static config
- ❌ No per-session isolation
- ❌ No dynamic provider selection

### New Design (Correct)
- ✅ ACS server is WebSocket **server** (listening for connections)
- ✅ Per-session event buses (complete isolation)
- ✅ Per-session providers
- ✅ Provider selected dynamically from ACS metadata
- ✅ Each session completely independent
- ✅ Symmetric bidirectional flow (ACS ↔ Provider)

## Configuration

### Sample `config.yaml`

```yaml
server:
  host: "0.0.0.0"
  port: 8080

dispatch:
  provider: "mock"  # Default if not specified in metadata
  batching:
    enabled: true
    max_batch_ms: 200
    max_batch_bytes: 65536
    idle_timeout_ms: 500

providers:
  voicelive:
    endpoint: "wss://voicelive.example.com/v1/realtime"
    api_key: "${VOICELIVE_API_KEY}"

buffering:
  ingress_queue_max: 1000
  egress_queue_max: 1000
  overflow_policy: "DROP_OLDEST"
```

## Routing Strategy

The server now uses a single session-scoped pipeline for every ACS WebSocket connection. Incoming events from any participant are forwarded to that one pipeline. Metadata routing hints (e.g., `routing: per_participant`) are ignored; participant isolation is handled inside the pipeline by reading `participant_id` on each `GatewayInputEvent`.

**Implications**:
- Only one pipeline (and one provider connection) exists per session
- Participant-specific behavior should be driven by event payloads instead of pipeline creation
- Downstream provider fan-out to multiple clients is handled separately from session routing

## Provider Selection Strategies

Provider selection works **within** the chosen routing strategy.

### 1. Explicit Provider in Metadata
```json
{
  "metadata": {"provider": "voicelive"}
}
```
All participants use VoiceLive.

### 2. Participant Overrides (Legacy)
```json
{
  "metadata": {
    "participant_providers": {
      "user-123": "voicelive",
      "user-456": "mock"
    }
  }
}
```
These hints are ignored in the current single-pipeline flow; the provider is selected once per session.

### 3. Customer-Based Routing
```json
{
  "metadata": {"customer_id": "acme-corp"}
}
```
Map customer → provider in config or database.

### 4. Feature Flags
```json
{
  "metadata": {
    "feature_flags": {"use_voicelive": true}
  }
}
```

### 5. A/B Testing
```json
{
  "metadata": {"experiment_group": "treatment_b"}
}
```

## Session Lifecycle

```
┌─────────────────┐
│ ACS Connects    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Create Session  │
│ - Generate ID   │
│ - Create buses  │
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│ First Message       │
│ - Extract metadata  │
│ - Select provider   │
│ - Create provider   │
│ - Register gateways │
└────────┬────────────┘
         │
         ▼
┌─────────────────┐
│ Process Messages│
│ (bidirectional) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ ACS Disconnects │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Cleanup Session │
│ - Stop provider │
│ - Shutdown buses│
│ - Close WebSocket│
└─────────────────┘
```

## Testing Strategy

### Unit Tests
- Test Session creation/cleanup
- Test provider selection logic
- Test handler registration

### Integration Tests with Mock Provider
```python
# Start server
server = ACSServer(config)

# Connect fake ACS client
async with websockets.connect("ws://localhost:8080") as ws:
    # Send audio message
    await ws.send(json.dumps({
        "kind": "AudioData",
        "metadata": {"provider": "mock"},
        "audioData": {"data": "...", "participantRawID": "test"}
    }))

    # Receive translation
    response = await ws.recv()
    assert json.loads(response)["type"] == "translation.result"
```

### Load Testing
- Multiple concurrent ACS connections
- Verify session isolation
- Check resource cleanup

## Advantages

1. **True Isolation**: Sessions and participants don't interfere with each other
2. **Dynamic Routing Strategy**: Choose shared vs per-participant based on metadata
3. **Dynamic Provider Selection**: Per-session, per-participant, per-customer, per-feature-flag
4. **Scalability**: Each session and participant pipeline runs independently
5. **Correct Architecture**: Server-side WebSocket pattern
6. **Clean State Management**: Per-session/per-participant state, no global contamination
7. **Easy Testing**: Mock provider per session or participant
8. **Flexibility**:
   - Different providers for different sessions simultaneously
   - Different providers for different participants in same session
   - Mix shared and per-participant routing across sessions
9. **Efficiency**: Default shared mode avoids overhead when isolation not needed
10. **Experimentation**: A/B test providers at session or participant level

## Migration Path

If migrating from current code:

1. Keep existing gateways (they work per-session)
2. Keep existing providers (VoiceLiveProvider, MockProvider)
3. Keep existing models (GatewayInputEvent, AudioRequest, ProviderOutputEvent)
4. Replace: `service.py` → `acs_server.py` + `session.py` + `session_manager.py`
5. Remove: `providers/ingress.py`, `providers/egress.py` (no longer needed)
6. Update: `provider_factory.py` to take `provider_type` parameter

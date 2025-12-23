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

### 3. Participant Pipeline (`participant_pipeline.py`)

**Responsibility**: Manages translation pipeline for ONE participant within a session.

```python
class ParticipantPipeline:
    """Independent translation pipeline for a single participant."""

    def __init__(
        self,
        session_id: str,
        participant_id: str,
        config: Config,
        provider_type: str,
        metadata: Dict[str, Any]
    ):
        self.session_id = session_id
        self.participant_id = participant_id
        self.config = config
        self.provider_type = provider_type
        self.metadata = metadata

        # Event buses (per-participant)
        pipeline_id = f"{session_id}_{participant_id}"
        self.acs_inbound_bus = EventBus(f"acs_in_{pipeline_id}")
        self.provider_outbound_bus = EventBus(f"prov_out_{pipeline_id}")
        self.provider_inbound_bus = EventBus(f"prov_in_{pipeline_id}")
        self.acs_outbound_bus = EventBus(f"acs_out_{pipeline_id}")

        # Provider (per-participant)
        self.provider_adapter: Optional[TranslationProvider] = None

        # Gateways (per-participant instances)
        self._translation_handler: Optional[TranslationDispatchHandler] = None

    async def start(self):
        """Start participant pipeline: create provider and register handlers."""
        # Create provider
        self.provider_adapter = ProviderFactory.create_provider(
            config=self.config,
            provider_type=self.provider_type,
            outbound_bus=self.provider_outbound_bus,
            inbound_bus=self.provider_inbound_bus
        )

        # Start provider
        await self.provider_adapter.start()
        logger.info(
            f"Participant {self.participant_id} provider started: {self.provider_type}"
        )

        # Register handlers
        await self._register_handlers()

    async def _register_handlers(self):
        """Register handlers on participant's event buses."""
        overflow_policy = OverflowPolicy(self.config.buffering.overflow_policy)

        # 1. Audit handler
        await self.acs_inbound_bus.register_handler(
            HandlerConfig(name="audit", queue_max=500, overflow_policy=overflow_policy),
            AuditHandler(
                HandlerSettings(name="audit", queue_max=500),
                payload_capture=None
            )
        )

        # 2. Translation dispatch handler
        self._translation_handler = TranslationDispatchHandler(
            HandlerSettings(
                name="translation",
                queue_max=self.config.buffering.ingress_queue_max
            ),
            provider_outbound_bus=self.provider_outbound_bus,
            batching_config=self.config.dispatch.batching
        )

        await self.acs_inbound_bus.register_handler(
            HandlerConfig(
                name="translation",
                queue_max=self.config.buffering.ingress_queue_max,
                overflow_policy=overflow_policy
            ),
            self._translation_handler
        )

        # 3. Provider result handler
        await self.provider_inbound_bus.register_handler(
            HandlerConfig(
                name="provider_result",
                queue_max=self.config.buffering.egress_queue_max,
                overflow_policy=overflow_policy
            ),
            ProviderResultHandler(
                HandlerSettings(
                    name="provider_result",
                    queue_max=self.config.buffering.egress_queue_max
                ),
                acs_outbound_bus=self.acs_outbound_bus
            )
        )

        logger.info(f"Participant {self.participant_id} handlers registered")

    async def process_message(self, envelope: Envelope):
        """Process message from ACS for this participant."""
        await self.acs_inbound_bus.publish(envelope)

    async def cleanup(self):
        """Cleanup participant pipeline."""
        # Shutdown translation handler
        if self._translation_handler:
            await self._translation_handler.shutdown()

        # Shutdown provider
        if self.provider_adapter:
            await self.provider_adapter.close()

        # Shutdown buses
        await self.acs_inbound_bus.shutdown()
        await self.provider_outbound_bus.shutdown()
        await self.provider_inbound_bus.shutdown()
        await self.acs_outbound_bus.shutdown()

        logger.info(f"Participant {self.participant_id} pipeline cleaned up")
```

**Key Points**:
- One pipeline per participant_id
- Complete isolation from other participants
- Own provider instance (can be different type)
- Own event buses and gateways
- Independent auto-commit state

### 4. Session (`session.py`)

**Responsibility**: Manages one ACS connection, routes messages to participant pipelines.

```python
class Session:
    def __init__(
        self,
        session_id: str,
        websocket: WebSocketServerProtocol,
        config: Config
    ):
        self.session_id = session_id
        self.websocket = websocket
        self.config = config

        # Session state
        self.routing_strategy: Optional[str] = None  # "shared" or "per_participant"
        self.metadata: Dict[str, Any] = {}

        # Routing modes
        # Mode 1: Shared pipeline (all participants share)
        self.shared_pipeline: Optional[ParticipantPipeline] = None

        # Mode 2: Per-participant pipelines
        self.participant_pipelines: Dict[str, ParticipantPipeline] = {}

        # Initialization flag
        self._initialized = False

        # Background tasks
        self._receive_task: Optional[asyncio.Task] = None
        self._send_task: Optional[asyncio.Task] = None

    async def run(self):
        """Run session: process messages until disconnect."""
        logger.info(f"Session {self.session_id} started")

        # Start ACS receive/send loops
        self._receive_task = asyncio.create_task(self._acs_receive_loop())
        self._send_task = asyncio.create_task(self._acs_send_loop())

        try:
            # Wait for both tasks
            await asyncio.gather(
                self._receive_task,
                self._send_task,
                return_exceptions=True
            )
        finally:
            await self.cleanup()

    async def _acs_receive_loop(self):
        """Receive messages from ACS WebSocket and route to pipelines."""
        try:
            async for raw_message in self.websocket:
                try:
                    data = json.loads(raw_message)

                    # First message: extract metadata and initialize
                    if not self._initialized:
                        await self._initialize_from_first_message(data)

                    # Convert to Envelope
                    envelope = Envelope.from_acs_frame(
                        data,
                        sequence=0,
                        ingress_ws_id=self.session_id
                    )

                    # Route based on strategy
                    await self._route_message(envelope)

                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON from ACS: {e}")
                except Exception as e:
                    logger.exception(f"Error processing ACS message: {e}")
        except websockets.ConnectionClosed:
            logger.info(f"Session {self.session_id} ACS disconnected")

    async def _route_message(self, envelope: Envelope):
        """Route message to appropriate pipeline(s)."""
        if self.routing_strategy == "shared":
            # All participants share one pipeline
            await self.shared_pipeline.process_message(envelope)

        elif self.routing_strategy == "per_participant":
            # Get or create pipeline for this participant
            participant_id = envelope.participant_id or "default"

            if participant_id not in self.participant_pipelines:
                # Create new pipeline for this participant
                pipeline = await self._create_participant_pipeline(
                    participant_id,
                    envelope
                )
                self.participant_pipelines[participant_id] = pipeline

            # Route to participant's pipeline
            await self.participant_pipelines[participant_id].process_message(envelope)

    async def _acs_send_loop(self):
        """Consume from acs_outbound_bus and send to ACS WebSocket."""
        # Register a handler that sends directly to WebSocket
        async def send_to_acs(payload: Dict[str, Any]):
            try:
                await self.websocket.send(json.dumps(payload))
                logger.debug(f"Sent to ACS: {payload.get('type')}")
            except Exception as e:
                logger.exception(f"Failed to send to ACS: {e}")

        await self.acs_outbound_bus.register_handler(
            HandlerConfig(
                name="acs_websocket_send",
                queue_max=1000,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1
            ),
            # Create inline handler
            type('ACSWebSocketSender', (Handler,), {
                'handle': lambda self, payload: send_to_acs(payload)
            })(HandlerSettings(name="acs_websocket_send", queue_max=1000))
        )

        # Keep task alive
        await asyncio.Future()

    async def _initialize_from_first_message(self, data: Dict[str, Any]):
        """Extract metadata and initialize routing strategy from first message."""
        self.metadata = data.get("metadata", {})

        # Determine routing strategy
        self.routing_strategy = self._select_routing_strategy(self.metadata)

        logger.info(
            f"Session {self.session_id} routing: {self.routing_strategy}"
        )

        if self.routing_strategy == "shared":
            # Create single shared pipeline
            participant_id = "shared"
            provider_type = self._select_provider(self.metadata, participant_id)

            self.shared_pipeline = ParticipantPipeline(
                session_id=self.session_id,
                participant_id=participant_id,
                config=self.config,
                provider_type=provider_type,
                metadata=self.metadata
            )
            await self.shared_pipeline.start()

            # Subscribe to its outbound bus
            await self._subscribe_to_pipeline_output(self.shared_pipeline)

        elif self.routing_strategy == "per_participant":
            # Pipelines created on-demand when participants send messages
            # (see _route_message and _create_participant_pipeline)
            pass

        self._initialized = True

    def _select_routing_strategy(self, metadata: Dict[str, Any]) -> str:
        """Select routing strategy based on ACS metadata."""
        # Strategy 1: Explicit routing in metadata
        if "routing" in metadata:
            routing = metadata["routing"]
            if routing in ["shared", "per_participant"]:
                return routing

        # Strategy 2: Feature flag
        if metadata.get("feature_flags", {}).get("per_participant_pipelines"):
            return "per_participant"

        # Strategy 3: Provider-specific requirements
        # Some providers might require per-participant isolation
        provider = metadata.get("provider", self.config.dispatch.provider)
        if provider in ["provider_requiring_isolation"]:
            return "per_participant"

        # Default: shared pipeline (more efficient)
        return "shared"

    def _select_provider(
        self,
        metadata: Dict[str, Any],
        participant_id: str
    ) -> str:
        """Select provider based on ACS metadata and participant."""
        # Strategy 1: Per-participant provider override
        participant_providers = metadata.get("participant_providers", {})
        if participant_id in participant_providers:
            return participant_providers[participant_id]

        # Strategy 2: Explicit provider in metadata
        if "provider" in metadata:
            return metadata["provider"]

        # Strategy 3: Customer/tenant-based routing
        if "customer_id" in metadata:
            # Could have per-customer provider mapping
            pass

        # Strategy 4: Feature flags
        if metadata.get("feature_flags", {}).get("use_voicelive"):
            return "voicelive"

        # Default: use config
        return self.config.dispatch.provider

    async def _create_participant_pipeline(
        self,
        participant_id: str,
        envelope: Envelope
    ) -> ParticipantPipeline:
        """Create pipeline for a new participant (per_participant mode)."""
        # Determine provider for this participant
        provider_type = self._select_provider(self.metadata, participant_id)

        logger.info(
            f"Creating pipeline for participant {participant_id}: "
            f"provider={provider_type}"
        )

        # Create pipeline
        pipeline = ParticipantPipeline(
            session_id=self.session_id,
            participant_id=participant_id,
            config=self.config,
            provider_type=provider_type,
            metadata=self.metadata
        )

        # Start pipeline
        await pipeline.start()

        # Subscribe to its outbound bus
        await self._subscribe_to_pipeline_output(pipeline)

        return pipeline

    async def _subscribe_to_pipeline_output(self, pipeline: ParticipantPipeline):
        """Subscribe to pipeline's acs_outbound_bus to forward to ACS."""
        async def send_to_acs(payload: Dict[str, Any]):
            try:
                await self.websocket.send(json.dumps(payload))
                logger.debug(f"Sent to ACS: {payload.get('type')}")
            except Exception as e:
                logger.exception(f"Failed to send to ACS: {e}")

        # Register handler on pipeline's outbound bus
        await pipeline.acs_outbound_bus.register_handler(
            HandlerConfig(
                name="acs_websocket_send",
                queue_max=1000,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1
            ),
            type('ACSWebSocketSender', (Handler,), {
                'handle': lambda self, payload: send_to_acs(payload)
            })(HandlerSettings(name="acs_websocket_send", queue_max=1000))
        )

    async def _register_handlers(self):
        """Register all handlers on event buses."""
        overflow_policy = OverflowPolicy(self.config.buffering.overflow_policy)

        # 1. Audit handler
        await self.acs_inbound_bus.register_handler(
            HandlerConfig(
                name="audit",
                queue_max=500,
                overflow_policy=overflow_policy,
                concurrency=1
            ),
            AuditHandler(
                HandlerSettings(name="audit", queue_max=500),
                payload_capture=None  # Could be per-session
            )
        )

        # 2. Translation dispatch handler
        await self.acs_inbound_bus.register_handler(
            HandlerConfig(
                name="translation",
                queue_max=self.config.buffering.ingress_queue_max,
                overflow_policy=overflow_policy,
                concurrency=1
            ),
            TranslationDispatchHandler(
                HandlerSettings(
                    name="translation",
                    queue_max=self.config.buffering.ingress_queue_max
                ),
                provider_outbound_bus=self.provider_outbound_bus,
                batching_config=self.config.dispatch.batching
            )
        )

        # 3. Provider result handler
        await self.provider_inbound_bus.register_handler(
            HandlerConfig(
                name="provider_result",
                queue_max=self.config.buffering.egress_queue_max,
                overflow_policy=overflow_policy,
                concurrency=1
            ),
            ProviderResultHandler(
                HandlerSettings(
                    name="provider_result",
                    queue_max=self.config.buffering.egress_queue_max
                ),
                acs_outbound_bus=self.acs_outbound_bus
            )
        )

        logger.info(f"Session {self.session_id} handlers registered")

    async def cleanup(self):
        """Cleanup session resources."""
        logger.info(f"Session {self.session_id} cleanup started")

        # Cancel tasks
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
        if self._send_task and not self._send_task.done():
            self._send_task.cancel()

        # Cleanup pipelines based on routing strategy
        if self.routing_strategy == "shared":
            if self.shared_pipeline:
                await self.shared_pipeline.cleanup()

        elif self.routing_strategy == "per_participant":
            for pipeline in self.participant_pipelines.values():
                await pipeline.cleanup()

        # Close WebSocket
        if not self.websocket.closed:
            await self.websocket.close()

        logger.info(f"Session {self.session_id} cleanup complete")
```

**Key Points**:
- One session = one ACS connection
- Supports two routing strategies (shared or per_participant)
- Strategy selected dynamically from first message metadata
- Pipelines created on-demand
- Lifecycle: initialize → route → cleanup

### 4. Provider Factory (`provider_factory.py`)

**Updated to support per-session provider selection**:

```python
class ProviderFactory:
    @staticmethod
    def create_provider(
        config: Config,
        provider_name: str,  # Now passed per-session
        outbound_bus: EventBus,
        inbound_bus: EventBus,
    ) -> TranslationProvider:
        """Create provider based on session-specific provider type."""
        provider_config = config.providers.get(provider_name)
        logger.info(
            "Creating provider: name=%s type=%s",
            provider_name,
            provider_config.type,
        )

        if provider_config.type == "mock":
            return MockProvider(
                outbound_bus=outbound_bus,
                inbound_bus=inbound_bus,
                delay_ms=50
            )

        elif provider_config.type == "voice_live":
            return VoiceLiveProvider(
                endpoint=provider_config.endpoint,
                api_key=provider_config.api_key,
                region=provider_config.region,
                resource=provider_config.resource,
                outbound_bus=outbound_bus,
                inbound_bus=inbound_bus
            )

        else:
            raise ValueError(f"Unknown provider type: {provider_config.type}")
```

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

#### Per-Participant Pipeline Mode

```
First message metadata: {
  "routing": "per_participant",
  "participant_providers": {
    "user-123": "voicelive",
    "user-456": "mock"
  }
}

Session creates pipelines on-demand:
  ├── Pipeline for Participant A (user-123)
  │   ├── Event buses (4)
  │   ├── Handlers (4)
  │   └── Provider: VoiceLive
  ├── Pipeline for Participant B (user-456)
  │   ├── Event buses (4)
  │   ├── Handlers (4)
  │   └── Provider: Mock
  └── Pipeline for Participant C (user-789)
      ├── Event buses (4)
      ├── Handlers (4)
      └── Provider: VoiceLive (default)

Message flow:
  Participant A audio → Pipeline A → VoiceLive connection A
  Participant B audio → Pipeline B → Mock provider B
  Participant C audio → Pipeline C → VoiceLive connection C

Resources: 3 pipelines, 3 provider connections, 12 event buses
```

**Pros**:
- Complete isolation per participant
- Different providers per participant
- Independent failure domains
- Independent auto-commit strategies

**Cons**:
- Higher overhead (3x resources)
- More complex state management
- Multiple provider connections

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
2. Detects routing: "shared"
3. Creates ONE shared pipeline with VoiceLive provider
4. All subsequent messages (any participant) → shared pipeline
5. Single VoiceLive connection handles all participants

### Example 2: Per-Participant Pipeline Flow

**First Message**:
```json
{
  "kind": "AudioData",
  "metadata": {
    "routing": "per_participant",
    "participant_providers": {
      "user-123": "voicelive",
      "user-456": "mock"
    }
  },
  "audioData": {
    "participantRawID": "user-123",
    "data": "UklGR..."
  }
}
```

**Flow**:
1. Session receives message from user-123
2. Detects routing: "per_participant"
3. Creates pipeline for user-123 with VoiceLive provider
4. Message routed to user-123's pipeline
5. Later: user-456 sends message
6. Creates pipeline for user-456 with Mock provider
7. Message routed to user-456's pipeline
8. Two independent pipelines, two provider connections

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
7. Message converted to Envelope, published to acs_inbound_bus
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

## Routing Strategy Selection

The routing strategy determines how participants are handled within a session. This is selected from the **first ACS message metadata**.

### Strategy 1: Shared Pipeline (Default)

**Use Case**: Most sessions where all participants can share resources.

**Metadata**:
```json
{
  "metadata": {"routing": "shared"},
  "audioData": {...}
}
```

**Behavior**:
- One pipeline for all participants
- Most efficient (less overhead)
- All participants use same provider
- Shared auto-commit buffers

### Strategy 2: Per-Participant Pipelines

**Use Cases**:
- Providers that only support single participant streams
- Different providers per participant
- Experimentation (A/B testing per participant)
- Complete isolation requirements

**Metadata**:
```json
{
  "metadata": {"routing": "per_participant"},
  "audioData": {...}
}
```

**Behavior**:
- Each participant gets own pipeline
- Independent providers, buffers, gateways
- Participants don't interfere with each other
- Created on-demand as participants send messages

### Strategy 3: Feature Flag Trigger

```json
{
  "metadata": {
    "feature_flags": {"per_participant_pipelines": true}
  }
}
```

### Strategy 4: Provider-Specific Requirements

Some providers automatically trigger per-participant mode:

```python
# In _select_routing_strategy()
if provider in ["provider_requiring_isolation"]:
    return "per_participant"
```

### Per-Participant Provider Override

When using per-participant routing, you can specify different providers per participant:

```json
{
  "metadata": {
    "routing": "per_participant",
    "participant_providers": {
      "user-123": "voicelive",
      "user-456": "mock",
      "user-789": "live_interpreter"
    }
  }
}
```

**Result**:
- user-123 → VoiceLiveProvider
- user-456 → MockProvider
- user-789 → LiveInterpreterAdapter (when implemented)

## Provider Selection Strategies

Provider selection works **within** the chosen routing strategy.

### 1. Explicit Provider in Metadata
```json
{
  "metadata": {"provider": "voicelive"}
}
```
All participants use VoiceLive.

### 2. Per-Participant Override
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
Different provider per participant (requires per_participant routing).

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
3. Keep existing models (Envelope, AudioRequest, ProviderOutputEvent, TranslationResponse)
4. Replace: `service.py` → `acs_server.py` + `session.py` + `session_manager.py`
5. Remove: `providers/ingress.py`, `providers/egress.py` (no longer needed)
6. Update: `provider_factory.py` to take `provider_type` parameter

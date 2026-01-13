# Voice Translation Server Architecture

This document provides a comprehensive technical overview of the Voice Translation Server architecture, design patterns, and implementation details.

## Table of Contents

- [Core Principles](#core-principles)
- [Architecture Overview](#architecture-overview)
- [Component Hierarchy](#component-hierarchy)
- [Event-Driven Architecture](#event-driven-architecture)
- [Session Lifecycle](#session-lifecycle)
- [Provider System](#provider-system)
- [Control Plane](#control-plane)
- [Audio Processing Pipeline](#audio-processing-pipeline)
- [Configuration System](#configuration-system)
- [Message Flow Examples](#message-flow-examples)
- [Testing Strategy](#testing-strategy)
- [Design Patterns](#design-patterns)

---

## Core Principles

### 1. Server-Side WebSocket Architecture

The service **listens** for incoming ACS (Azure Communication Services) WebSocket connections rather than connecting out to external services. This is a fundamental architectural pattern:

- **Correct**: Service listens on port 8080, ACS clients connect to us
- **Incorrect**: Service connects out to ACS endpoints

### 2. Complete Session Isolation

Each ACS WebSocket connection represents one **independent session** with:
- Dedicated `SessionPipeline` with 4 event buses
- Independent provider connection (not shared across sessions)
- Isolated state (control plane, buffers, queues)
- No cross-session contamination

**Key Insight**: Multiple concurrent sessions can use different providers simultaneously without interference.

### 3. Event-Driven Processing

All communication within a session flows through **event buses** using fan-out pub/sub:
- Handlers subscribe to buses with independent queues
- Configurable overflow policies (DROP_OLDEST, DROP_NEWEST)
- Async-safe with bounded queues
- Clean separation between producers and consumers

### 4. Dynamic Provider Selection

Provider is selected **per session** based on priority:
1. Test settings (`control.test.settings` message)
2. Session metadata (`metadata.provider`)
3. Feature flags (`metadata.feature_flags.use_voicelive`)
4. Config default (`system.default_provider`)

**Result**: Sessions can use different providers concurrently (e.g., session A uses OpenAI, session B uses Voice Live).

### 5. Bidirectional Streaming

Symmetric message flow in both directions:
```
ACS → Session → Provider → Translation
ACS ← Session ← Provider ← Results
```

Real-time processing with minimal buffering except for batching optimization.

---

## Architecture Overview

### High-Level Component Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    ACS WebSocket Server                      │
│                   (listens on port 8080)                     │
└──────────────────────────┬──────────────────────────────────┘
                           │ Accepts connections
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     SessionManager                           │
│              (tracks all active sessions)                    │
└──────────────────────────┬──────────────────────────────────┘
                           │ Creates Session per connection
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                   ▼
   ┌────────┐         ┌────────┐         ┌────────┐
   │Session │         │Session │         │Session │
   │  #1    │         │  #2    │         │  #3    │
   └────┬───┘         └────┬───┘         └────┬───┘
        │                  │                   │
        ▼                  ▼                   ▼
   SessionPipeline    SessionPipeline    SessionPipeline
   ├─ acs_inbound_bus    │                   │
   ├─ provider_out_bus   │                   │
   ├─ provider_in_bus    │                   │
   ├─ acs_outbound_bus   │                   │
   └─ ControlPlane       │                   │
        │                  │                   │
        ▼                  ▼                   ▼
   OpenAI Provider   Voice Live Provider  Mock Provider
```

### Key Architectural Layers

| Layer | Component | Responsibility |
|-------|-----------|---------------|
| **Network** | ACSServer | Accept WebSocket connections |
| **Session Management** | SessionManager | Track active sessions, coordinate shutdown |
| **Connection** | Session | Manage one WebSocket connection, run receive/send loops |
| **Pipeline** | SessionPipeline | Route messages through event buses |
| **Event Distribution** | EventBus | Fan-out pub/sub with bounded queues |
| **Protocol Adapters** | Gateways | Convert between ACS ↔ internal ↔ provider formats |
| **Translation** | Provider | Connect to external translation service |
| **State Management** | ControlPlane | Track playback/input state, orchestrate actions |

---

## Component Hierarchy

### 1. ACSServer (`core/acs_server.py`)

**Entry point for the entire service.**

```python
class ACSServer:
    def __init__(self, config: Config):
        self.config = config
        self.host = config.system.host
        self.port = config.system.port
        self.session_manager = SessionManager(config)

    async def start(self):
        """Start WebSocket server and run forever."""
        async with websockets.serve(
            self._handle_connection,
            self.host,
            self.port
        ):
            logger.info(f"ACS server listening on {self.host}:{self.port}")
            await asyncio.Future()  # Run indefinitely

    async def _handle_connection(
        self,
        websocket: WebSocketServerProtocol,
        path: str
    ):
        """Handle incoming ACS WebSocket connection."""
        # Extract connection headers (call_connection_id, correlation_id)
        connection_ctx = ConnectionContext.from_headers(websocket.request_headers)

        # Create session
        session = await self.session_manager.create_session(
            websocket,
            connection_ctx
        )

        try:
            await session.run()  # Run until disconnect
        except Exception as e:
            logger.exception(f"Session error: {e}")
        finally:
            await self.session_manager.remove_session(session.session_id)
```

**Key Responsibilities**:
- Listen on configured host/port
- Accept WebSocket connections
- Extract connection metadata from headers
- Delegate to SessionManager
- Handle errors and cleanup

**Startup Sequence**:
1. Load configuration (YAML + environment overrides)
2. Create SessionManager
3. Start WebSocket server with `websockets.serve()`
4. Wait indefinitely (until KeyboardInterrupt)
5. Graceful shutdown of all sessions

---

### 2. SessionManager (`session/session_manager.py`)

**Tracks all active sessions.**

```python
class SessionManager:
    def __init__(self, config: Config):
        self.config = config
        self.sessions: Dict[str, Session] = {}
        self._lock = asyncio.Lock()  # Thread-safe access

    async def create_session(
        self,
        websocket: WebSocketServerProtocol,
        connection_ctx: ConnectionContext
    ) -> Session:
        """Create new session for ACS connection."""
        async with self._lock:
            session_id = str(uuid.uuid4())
            session = Session(
                session_id=session_id,
                websocket=websocket,
                config=self.config,
                connection_ctx=connection_ctx
            )
            self.sessions[session_id] = session
            logger.info(f"session_created id={session_id} count={len(self.sessions)}")
            return session

    async def remove_session(self, session_id: str):
        """Remove session and cleanup resources."""
        async with self._lock:
            session = self.sessions.pop(session_id, None)
            if session:
                await session.cleanup()
                logger.info(f"session_removed id={session_id} count={len(self.sessions)}")

    async def shutdown_all(self):
        """Shutdown all active sessions (graceful server shutdown)."""
        async with self._lock:
            logger.info(f"Shutting down {len(self.sessions)} active sessions")
            for session in list(self.sessions.values()):
                await session.cleanup()
            self.sessions.clear()

    def get_active_count(self) -> int:
        """Return number of active sessions."""
        return len(self.sessions)
```

**Key Responsibilities**:
- Create sessions with unique IDs
- Track all active sessions in dictionary
- Thread-safe session access (asyncio.Lock)
- Coordinate graceful shutdown
- Provide session metrics (active count)

**Session Tracking**:
- Key: `session_id` (UUID)
- Value: `Session` instance
- Cleanup on disconnect or error
- No session reuse (create fresh per connection)

---

### 3. Session (`session/session.py`)

**Manages one ACS WebSocket connection.**

```python
class Session:
    def __init__(
        self,
        session_id: str,
        websocket: WebSocketServerProtocol,
        config: Config,
        connection_ctx: ConnectionContext
    ):
        self.session_id = session_id
        self.websocket = websocket
        self.config = config
        self.connection_ctx = connection_ctx

        # Extracted from ACS messages
        self.metadata: Dict[str, Any] = {}
        self.translation_settings: Dict[str, Any] = {}

        # Pipeline (created on first message)
        self.pipeline: Optional[SessionPipeline] = None

        # Tasks
        self._receive_task: Optional[asyncio.Task] = None

    async def run(self):
        """Run session until disconnect."""
        try:
            # Initialize ACS processing (before provider ready)
            await self._initialize_acs_processing()

            # Start receive loop
            self._receive_task = asyncio.create_task(self._acs_receive_loop())
            await self._receive_task

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"session_disconnected id={self.session_id}")
        except Exception as e:
            logger.exception(f"session_error id={self.session_id} error={e}")

    async def _acs_receive_loop(self):
        """Receive messages from ACS WebSocket."""
        async for raw_message in self.websocket:
            try:
                data = json.loads(raw_message)

                # Create event envelope
                event = GatewayInputEvent.from_acs_message(
                    payload=data,
                    session_id=self.session_id,
                    connection_ctx=self.connection_ctx
                )

                # Route to pipeline
                await self.pipeline.process_message(event)

            except Exception as e:
                logger.exception(f"message_processing_error id={self.session_id} error={e}")

    async def _initialize_acs_processing(self):
        """Create pipeline and register ACS handlers (before provider ready)."""
        self.pipeline = SessionPipeline(
            session_id=self.session_id,
            config=self.config,
            metadata=self.metadata,
            translation_settings=self.translation_settings
        )

        # Phase 1: Register ACS handlers
        await self.pipeline.start_acs_processing()

        # Subscribe to outbound bus for sending to ACS
        await self._subscribe_to_pipeline_output()

    async def _subscribe_to_pipeline_output(self):
        """Register handler to send pipeline output to ACS WebSocket."""
        async def send_to_acs(payload: Dict[str, Any]):
            await self.websocket.send(json.dumps(payload))

        await self.pipeline.acs_outbound_bus.register_handler(
            HandlerConfig(
                name=f"acs_websocket_send_{self.session_id}",
                queue_max=1000,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1
            ),
            send_to_acs
        )

    async def cleanup(self):
        """Cleanup session resources."""
        if self._receive_task:
            self._receive_task.cancel()

        if self.pipeline:
            await self.pipeline.cleanup()

        await self.websocket.close()
        logger.info(f"session_cleanup_complete id={self.session_id}")
```

**Key Responsibilities**:
- Run receive loop (ACS → Pipeline)
- Create SessionPipeline on startup
- Subscribe to pipeline output (Pipeline → ACS)
- Handle WebSocket close/errors
- Cleanup on disconnect

**Initialization Flow**:
1. Create `SessionPipeline`
2. Call `pipeline.start_acs_processing()` (register ACS handlers)
3. Subscribe to `acs_outbound_bus` for sending to ACS
4. Start receive loop
5. Wait for disconnect or error
6. Cleanup pipeline and WebSocket

---

### 4. SessionPipeline (`session/session_pipeline.py`)

**Event-driven message routing for one session.**

```python
class SessionPipeline:
    """One pipeline per ACS WebSocket session (shared by all participants)."""

    # Pipeline stages
    NOT_STARTED = "not_started"
    ACS_PROCESSING = "acs_processing"
    PROVIDER_PROCESSING = "provider_processing"

    def __init__(
        self,
        session_id: str,
        config: Config,
        metadata: Dict[str, Any],
        translation_settings: Dict[str, Any]
    ):
        self.session_id = session_id
        self.config = config
        self.metadata = metadata
        self.translation_settings = translation_settings

        self.stage = self.NOT_STARTED

        # Event buses (session-scoped)
        self.acs_inbound_bus = EventBus(f"acs_in_{session_id}")
        self.provider_outbound_bus = EventBus(f"prov_out_{session_id}")
        self.provider_inbound_bus = EventBus(f"prov_in_{session_id}")
        self.acs_outbound_bus = EventBus(f"acs_out_{session_id}")

        # Provider (created in phase 2)
        self.provider: Optional[TranslationProvider] = None

        # Control plane (state management)
        self.control_plane = SessionControlPlane(
            session_id=session_id,
            pipeline_actuator=self  # Self as actuator interface
        )

    async def start_acs_processing(self):
        """Phase 1: Register ACS handlers (before provider ready)."""
        self.stage = self.ACS_PROCESSING

        # Register ACS message handlers
        await self._register_acs_handlers()

        # Register control plane handlers (tap into buses)
        await self._register_control_plane_handlers()

        logger.info(f"pipeline_acs_processing_started session={self.session_id}")

    async def start_provider_processing(self, provider_name: str):
        """Phase 2: Create provider and register provider handlers."""
        self.stage = self.PROVIDER_PROCESSING

        # Create and start provider
        self.provider = ProviderFactory.create_provider(
            config=self.config,
            provider_name=provider_name,
            provider_outbound_bus=self.provider_outbound_bus,
            provider_inbound_bus=self.provider_inbound_bus,
            metadata=self.metadata,
            translation_settings=self.translation_settings
        )
        await self.provider.start()

        # Register provider handlers
        await self._register_provider_handlers()

        logger.info(f"pipeline_provider_processing_started session={self.session_id} provider={provider_name}")

    async def process_message(self, event: GatewayInputEvent):
        """Publish ACS message to inbound bus."""
        await self.acs_inbound_bus.publish(event)

    async def _register_acs_handlers(self):
        """Register handlers for ACS messages."""
        # Audio message handler (buffering, batching)
        await self.acs_inbound_bus.register_handler(
            HandlerConfig(
                name=f"audio_handler_{self.session_id}",
                queue_max=self.config.buffering.ingress_queue_max,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1
            ),
            AudioMessageHandler(
                pipeline=self,
                config=self.config
            )
        )

        # Audio metadata handler (triggers provider init)
        await self.acs_inbound_bus.register_handler(
            HandlerConfig(
                name=f"metadata_handler_{self.session_id}",
                queue_max=100,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1
            ),
            AudioMetadataHandler(
                pipeline=self,
                metadata=self.metadata
            )
        )

        # Test settings handler (hot config reload)
        await self.acs_inbound_bus.register_handler(
            HandlerConfig(
                name=f"test_settings_{self.session_id}",
                queue_max=100,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1
            ),
            TestSettingsHandler(
                translation_settings=self.translation_settings,
                session_metadata=self.metadata
            )
        )

    async def _register_provider_handlers(self):
        """Register handlers for provider responses."""
        # Provider output handler (formats responses for ACS)
        await self.provider_inbound_bus.register_handler(
            HandlerConfig(
                name=f"provider_output_{self.session_id}",
                queue_max=self.config.buffering.egress_queue_max,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1
            ),
            ProviderOutputHandler(
                acs_outbound_bus=self.acs_outbound_bus
            )
        )

    async def _register_control_plane_handlers(self):
        """Register control plane handlers (tap into buses for state tracking)."""
        # Tap provider input bus for input state
        await self.provider_inbound_bus.register_handler(
            HandlerConfig(
                name=f"control_plane_input_{self.session_id}",
                queue_max=100,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1
            ),
            ControlPlaneBusHandler(
                control_plane=self.control_plane,
                event_type="provider_input"
            )
        )

        # Tap provider output bus for playback state
        await self.provider_inbound_bus.register_handler(
            HandlerConfig(
                name=f"control_plane_output_{self.session_id}",
                queue_max=100,
                overflow_policy=OverflowPolicy.DROP_OLDEST,
                concurrency=1
            ),
            ControlPlaneBusHandler(
                control_plane=self.control_plane,
                event_type="provider_output"
            )
        )

    # Pipeline Actuator Interface (for control plane)

    def set_outbound_gate(self, enabled: bool, reason: str, correlation_id: Optional[str] = None):
        """Control playback gate (open/close)."""
        # Implementation: Set flag that gate handler checks
        self._gate_enabled = enabled
        logger.info(f"gate_set session={self.session_id} enabled={enabled} reason={reason}")

    async def drop_outbound_audio(self, reason: str, correlation_id: Optional[str] = None):
        """Drop buffered outbound audio."""
        # Implementation: Clear audio queues
        logger.info(f"audio_dropped session={self.session_id} reason={reason}")

    async def cancel_provider_response(self, provider_response_id: str, reason: str):
        """Cancel in-flight provider response."""
        if self.provider:
            await self.provider.cancel_response(provider_response_id)
        logger.info(f"response_cancelled session={self.session_id} response_id={provider_response_id} reason={reason}")

    async def flush_inbound_buffers(self, participant_id: Optional[str], keep_after_ts_ms: Optional[int]):
        """Clear audio buffers."""
        # Implementation: Clear audio buffers in audio handler
        logger.info(f"buffers_flushed session={self.session_id} participant={participant_id}")

    async def cleanup(self):
        """Shutdown pipeline resources."""
        if self.provider:
            await self.provider.close()

        await self.acs_inbound_bus.shutdown()
        await self.provider_outbound_bus.shutdown()
        await self.provider_inbound_bus.shutdown()
        await self.acs_outbound_bus.shutdown()

        logger.info(f"pipeline_cleanup_complete session={self.session_id}")
```

**Key Responsibilities**:
- Manage 4 event buses per session
- Two-phase initialization (ACS → Provider)
- Register all handlers
- Provide pipeline actuator interface for control plane
- Cleanup on session end

**Two-Phase Initialization**:

**Phase 1: ACS Processing** (before provider ready)
- Register ACS handlers (audio, metadata, control)
- Messages can be queued
- Provider not yet selected

**Phase 2: Provider Processing** (after first AudioMetadata message)
- Provider selected based on priority
- Provider created and started
- Provider handlers registered
- Queued messages consumed

**Why Two-Phase?**
- Provider selection based on actual metadata (not hardcoded)
- Allows buffering messages before provider ready
- Clean separation of concerns

---

## Event-Driven Architecture

### Event Bus Implementation (`core/event_bus.py`)

**Fan-out pub/sub with bounded queues.**

```python
class EventBus:
    """Fan-out event bus: each handler gets independent queue."""

    def __init__(self, name: str):
        self.name = name
        self.handlers: List[HandlerEntry] = []
        self._lock = asyncio.Lock()

    async def register_handler(
        self,
        config: HandlerConfig,
        handler_func: Callable
    ):
        """Register handler with independent queue."""
        queue = BoundedQueue(
            max_size=config.queue_max,
            overflow_policy=config.overflow_policy
        )

        # Start worker tasks
        workers = []
        for i in range(config.concurrency):
            worker = asyncio.create_task(
                self._worker(handler_func, queue, f"{config.name}_worker_{i}")
            )
            workers.append(worker)

        async with self._lock:
            self.handlers.append(HandlerEntry(
                name=config.name,
                queue=queue,
                workers=workers,
                handler_func=handler_func
            ))

    async def publish(self, message: Any):
        """Publish message to all handlers (fan-out)."""
        async with self._lock:
            for handler in self.handlers:
                await handler.queue.put(message)  # Non-blocking

    async def _worker(
        self,
        handler_func: Callable,
        queue: BoundedQueue,
        worker_name: str
    ):
        """Worker task: consume from queue, call handler."""
        while True:
            try:
                message = await queue.get()
                await handler_func(message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"worker_error name={worker_name} error={e}")

    async def shutdown(self):
        """Cancel all worker tasks."""
        async with self._lock:
            for handler in self.handlers:
                for worker in handler.workers:
                    worker.cancel()
```

**Key Features**:
- **Fan-Out**: Each handler gets independent queue (not shared)
- **Bounded Queues**: Configurable max size per handler
- **Overflow Policies**: DROP_OLDEST (default), DROP_NEWEST
- **Concurrency**: Multiple workers per handler
- **Async-Safe**: All operations use asyncio.Lock

**Example Usage**:
```python
bus = EventBus("example_bus")

await bus.register_handler(
    HandlerConfig(
        name="handler_1",
        queue_max=1000,
        overflow_policy=OverflowPolicy.DROP_OLDEST,
        concurrency=1
    ),
    async_handler_function_1
)

await bus.register_handler(
    HandlerConfig(
        name="handler_2",
        queue_max=500,
        overflow_policy=OverflowPolicy.DROP_OLDEST,
        concurrency=2
    ),
    async_handler_function_2
)

# Publish to all handlers
await bus.publish(message)
```

### Four Event Buses Per Session

| Bus | Producer | Consumer | Messages |
|-----|----------|----------|----------|
| **acs_inbound_bus** | Session receive loop | ACS handlers (audio, metadata, control) | `GatewayInputEvent` |
| **provider_outbound_bus** | Audio handler (after batching) | Provider egress handler | `ProviderInputEvent` |
| **provider_inbound_bus** | Provider ingress handler | Provider output handlers, control plane | `ProviderOutputEvent` |
| **acs_outbound_bus** | Provider output handler | ACS gate handler (sends to WebSocket) | ACS-formatted payloads |

### Message Flow Through Buses

```
ACS WebSocket
    ↓
GatewayInputEvent
    ↓
acs_inbound_bus (fan-out)
    ├─> AudioMessageHandler (buffer, batch)
    ├─> AudioMetadataHandler (trigger provider init)
    ├─> TestSettingsHandler (update settings)
    └─> ControlPlaneBusHandler (tap for state)
    ↓
ProviderInputEvent (after auto-commit)
    ↓
provider_outbound_bus
    ├─> Provider Egress Handler
    ↓
Provider WebSocket (OpenAI, Voice Live, etc.)
    ↓
ProviderOutputEvent (translation, audio)
    ↓
provider_inbound_bus (fan-out)
    ├─> ProviderOutputHandler (format for ACS)
    └─> ControlPlaneBusHandler (update playback state)
    ↓
ACS-formatted payload
    ↓
acs_outbound_bus
    ├─> AcsWebsocketSendHandler
    ↓
ACS WebSocket
```

---

## Session Lifecycle

### Complete Session Lifecycle Diagram

```
┌──────────────────────┐
│  ACS Connects        │
│  (WebSocket)         │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ ConnectionContext    │
│ - Extract headers    │
│ - call_connection_id │
│ - correlation_id     │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ SessionManager       │
│ - Generate UUID      │
│ - Create Session     │
│ - Track in dict      │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────────────────────┐
│ Session.run()                        │
│ ┌──────────────────────────────────┐ │
│ │ Phase 1: ACS Processing          │ │
│ │ - Create SessionPipeline         │ │
│ │ - Register ACS handlers          │ │
│ │ - Subscribe to acs_outbound_bus  │ │
│ │ - Stage: ACS_PROCESSING          │ │
│ └──────────────────────────────────┘ │
│ ┌──────────────────────────────────┐ │
│ │ Receive Loop                     │ │
│ │ - Wait for messages              │ │
│ │ - Parse JSON                     │ │
│ │ - Create GatewayInputEvent       │ │
│ │ - Publish to pipeline            │ │
│ └──────────────────────────────────┘ │
└──────────────────┬───────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
┌────────────────┐    ┌────────────────┐
│ Regular Message│    │ AudioMetadata  │
│ - Process      │    │ Message        │
│ - Route to     │    │                │
│   handlers     │    └────────┬───────┘
└────────────────┘             │
                               ▼
                    ┌──────────────────────────────┐
                    │ Phase 2: Provider Processing │
                    │ - Select provider (priority) │
                    │ - Create provider            │
                    │ - Start provider connection  │
                    │ - Register provider handlers │
                    │ - Stage: PROVIDER_PROCESSING │
                    └──────────┬───────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ Process Messages     │
                    │ (bidirectional)      │
                    │ - ACS → Provider     │
                    │ - Provider → ACS     │
                    └──────────┬───────────┘
                               │
                ┌──────────────┴──────────────┐
                │                             │
                ▼                             ▼
        ┌────────────────┐          ┌────────────────┐
        │ ACS Disconnect │          │ Error/Timeout  │
        └────────┬───────┘          └────────┬───────┘
                 │                           │
                 └─────────────┬─────────────┘
                               ▼
                    ┌──────────────────────┐
                    │ Session.cleanup()    │
                    │ - Cancel tasks       │
                    │ - Stop provider      │
                    │ - Shutdown buses     │
                    │ - Close WebSocket    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ SessionManager       │
                    │ - Remove from dict   │
                    │ - Log metrics        │
                    └──────────────────────┘
```

### State Transitions

**Pipeline Stages**:
```
NOT_STARTED
    ↓ (start_acs_processing)
ACS_PROCESSING
    ↓ (start_provider_processing)
PROVIDER_PROCESSING
```

**Why Staged Initialization?**
1. **Flexibility**: Provider selection based on actual metadata
2. **Buffering**: Can queue messages before provider ready
3. **Error Handling**: Clean failure modes
4. **Separation**: ACS protocol vs provider protocol decoupled

---

## Provider System

### Provider Factory (`providers/provider_factory.py`)

**Dynamic provider selection with priority-based logic.**

```python
class ProviderFactory:
    @staticmethod
    def create_provider(
        config: Config,
        provider_name: str,
        provider_outbound_bus: EventBus,
        provider_inbound_bus: EventBus,
        metadata: Dict[str, Any],
        translation_settings: Dict[str, Any]
    ) -> TranslationProvider:
        """Create provider instance based on name."""

        # Priority 1: Test settings override
        if "provider" in translation_settings:
            provider_name = translation_settings["provider"]
            logger.info(f"provider_selected source=test_settings provider={provider_name}")

        # Priority 2: Session metadata
        elif "provider" in metadata:
            provider_name = metadata["provider"]
            logger.info(f"provider_selected source=metadata provider={provider_name}")

        # Priority 3: Feature flags (legacy)
        elif metadata.get("feature_flags", {}).get("use_voicelive"):
            provider_name = "voicelive"
            logger.info(f"provider_selected source=feature_flag provider={provider_name}")

        # Priority 4: Config default
        else:
            provider_name = config.system.default_provider
            logger.info(f"provider_selected source=config_default provider={provider_name}")

        # Create provider instance
        provider_config = config.providers.get(provider_name)
        if not provider_config:
            raise ValueError(f"Provider '{provider_name}' not found in config")

        provider_type = provider_config.type

        if provider_type == "mock":
            return MockProvider(
                config=provider_config,
                provider_inbound_bus=provider_inbound_bus
            )
        elif provider_type == "openai":
            return OpenAIProvider(
                config=provider_config,
                provider_outbound_bus=provider_outbound_bus,
                provider_inbound_bus=provider_inbound_bus,
                metadata=metadata
            )
        elif provider_type == "voice_live":
            return VoiceLiveProvider(
                config=provider_config,
                provider_outbound_bus=provider_outbound_bus,
                provider_inbound_bus=provider_inbound_bus,
                metadata=metadata
            )
        elif provider_type == "live_interpreter":
            return LiveInterpreterProvider(
                config=provider_config,
                provider_outbound_bus=provider_outbound_bus,
                provider_inbound_bus=provider_inbound_bus,
                metadata=metadata
            )
        elif provider_type == "role_based":
            return RoleBasedProvider(
                config=provider_config,
                all_providers=config.providers,
                provider_outbound_bus=provider_outbound_bus,
                provider_inbound_bus=provider_inbound_bus,
                metadata=metadata
            )
        else:
            raise ValueError(f"Unknown provider type: {provider_type}")
```

### Provider Protocol

All providers implement this interface:

```python
class TranslationProvider(Protocol):
    async def start(self) -> None:
        """Connect to external service, initialize resources."""

    async def close(self) -> None:
        """Disconnect, cleanup resources."""

    async def health(self) -> str:
        """Return health status."""

    async def cancel_response(self, response_id: str) -> None:
        """Cancel in-flight response (optional)."""
```

### Available Providers

#### 1. Mock Provider

**Configuration**:
```yaml
providers:
  mock:
    type: mock
```

**Behavior**:
- No external calls
- 50ms simulated delay
- Generates partial + final transcripts
- Ideal for testing

#### 2. OpenAI Realtime

**Configuration**:
```yaml
providers:
  openai:
    type: openai
    endpoint: wss://api.openai.com/v1/realtime
    api_key: ${OPENAI_API_KEY}
    settings:
      model: gpt-4o-realtime-preview-2024-10-01
      deployment: gpt-4o-realtime-preview
```

**Features**:
- GPT-based translation
- 24 kHz PCM16 audio
- Server VAD
- Customizable prompts

#### 3. Voice Live

**Configuration**:
```yaml
providers:
  voicelive:
    type: voice_live
    endpoint: wss://example.cognitiveservices.azure.com/openai/realtime
    api_key: ${VOICELIVE_API_KEY}
    region: eastus
    settings:
      model: gpt-realtime-mini
      session_options:
        voice: alloy
```

**Features**:
- Azure AI Foundry Realtime API
- 24 kHz PCM16 audio
- Built-in neural voices
- Conversational AI

#### 4. Live Interpreter (v2)

**Configuration**:
```yaml
providers:
  live_interpreter:
    type: live_interpreter
    region: eastus2
    api_key: ${LIVE_INTERPRETER_API_KEY}
    settings:
      languages: [en-US, es-ES, fr-FR]
      voice: es-ES-ElviraNeural
```

**Features**:
- **Automatic language detection** (76+ languages)
- No source language config needed
- Real-time language switching
- 16 kHz PCM16 audio
- Neural voice synthesis

#### 5. Role-Based Provider

**Configuration**:
```yaml
providers:
  role_based:
    type: role_based
    settings:
      role_providers:
        agent: live_interpreter_spanish
        caller: live_interpreter_english
```

**Features**:
- Routes by participant role
- Different provider per role
- Asymmetric translation

#### 6. Participant-Based Provider

**Configuration**:
```yaml
providers:
  participant_based:
    type: participant_based
    settings:
      provider: live_interpreter
```

**Features**:
- Creates a provider instance per participant on first message
- Routes participant audio to the dedicated instance
- Shared inbound bus for provider output events

---

## Control Plane

### SessionControlPlane (`session/control/session_control_plane.py`)

**Tracks session state for intelligent orchestration.**

```python
class SessionControlPlane:
    """Per-session control plane for state tracking and orchestration."""

    # Constants
    PLAYBACK_IDLE_TIMEOUT_MS = 500
    INPUT_SILENCE_TIMEOUT_MS = 350
    INPUT_VOICE_HYSTERESIS_MS = 100

    def __init__(
        self,
        session_id: str,
        pipeline_actuator: SessionPipelineProtocol
    ):
        self.session_id = session_id
        self._pipeline = pipeline_actuator

        # State machines
        self.playback = PlaybackState()
        self.input_state = InputState()

        # Session state
        self.active_speaker_id: Optional[str] = None
        self.current_provider_response_id: Optional[str] = None
        self.barge_in_armed: bool = False

    async def process_provider_input(self, event: ProviderInputEvent):
        """Update input state based on audio metadata."""
        now_ms = MonotonicClock.now_ms()
        self._check_idle_timeout(now_ms)
        self._update_input_state(event, now_ms)

    async def process_provider_output(self, event: ProviderOutputEvent):
        """Update playback state based on provider responses."""
        now_ms = MonotonicClock.now_ms()
        self._check_idle_timeout(now_ms)

        control_event = ControlEvent.from_provider(event)
        event_type = control_event.type

        if event_type == "provider.audio.delta":
            self.current_provider_response_id = control_event.provider_response_id
            return

        if event_type == "provider.audio.done":
            self._transition_playback(
                lambda: self.playback.on_provider_done(control_event.provider_response_id),
                reason="provider_audio_done",
                response_id=control_event.provider_response_id
            )

    def _update_input_state(self, event: ProviderInputEvent, now_ms: int):
        """Update input state machine."""
        old_status = self.input_state.status
        is_silence = event.metadata["is_silence"]

        if is_silence:
            transitioned = self.input_state.on_silence_detected(
                now_ms,
                self.INPUT_SILENCE_TIMEOUT_MS
            )
        else:
            transitioned = self.input_state.on_voice_detected(
                now_ms,
                self.INPUT_VOICE_HYSTERESIS_MS
            )

        if transitioned:
            logger.info(
                f"input_state_changed session={self.session_id} "
                f"from={old_status} to={self.input_state.status}"
            )

    def _transition_playback(self, updater, *, reason: str, response_id: Optional[str]):
        """Update playback state machine."""
        old_status = self.playback.status
        updater()
        new_status = self.playback.status

        if old_status != new_status:
            logger.info(
                f"playback_status_changed session={self.session_id} "
                f"from={old_status} to={new_status} reason={reason}"
            )

    def _check_idle_timeout(self, now_ms: int):
        """Check for playback idle timeout."""
        old_status = self.playback.status
        timed_out = self.playback.maybe_timeout_idle(
            now_ms,
            self.PLAYBACK_IDLE_TIMEOUT_MS
        )

        if timed_out:
            logger.info(
                f"playback_idle_timeout session={self.session_id} "
                f"last_audio_sent_ms={self.playback.last_audio_sent_ms}"
            )
```

### PlaybackState (`session/control/playback_state.py`)

**Tracks outbound audio state.**

```python
@dataclass
class PlaybackState:
    """Tracks whether outbound audio is playing."""

    status: PlaybackStatus = PlaybackStatus.IDLE
    current_response_id: Optional[str] = None
    last_audio_sent_ms: int = 0
    provider_done: bool = False
    gate_closed: bool = False

    def on_outbound_audio_sent(self, now_ms: int, response_id: Optional[str]) -> bool:
        """Transition to SPEAKING when audio sent."""
        if self.status == PlaybackStatus.IDLE:
            self.status = PlaybackStatus.SPEAKING
            self.current_response_id = response_id
            self.last_audio_sent_ms = now_ms
            return True  # Transitioned
        self.last_audio_sent_ms = now_ms
        return False

    def on_provider_done(self, response_id: Optional[str]) -> bool:
        """Mark provider as done."""
        if self.current_response_id == response_id:
            self.provider_done = True
        return False

    def maybe_timeout_idle(self, now_ms: int, timeout_ms: int) -> bool:
        """Check for idle timeout."""
        if self.status == PlaybackStatus.SPEAKING:
            if (now_ms - self.last_audio_sent_ms) > timeout_ms:
                self.status = PlaybackStatus.IDLE
                self.current_response_id = None
                self.provider_done = False
                return True
        return False
```

**States**:
- `IDLE`: No audio in playback
- `SPEAKING`: Audio being sent to ACS
- `FINISHED`: Provider sent done signal
- `GATE_CLOSED`: Gate explicitly closed

### InputState (`session/control/input_state.py`)

**Tracks voice activity.**

```python
@dataclass
class InputState:
    """Tracks whether inbound audio contains speech."""

    status: InputStatus = InputStatus.SILENT
    voice_detected_from_ms: Optional[int] = None  # Onset time
    voice_detected_last_ms: int = 0  # Most recent

    def on_voice_detected(self, now_ms: int, hysteresis_ms: int = 0) -> bool:
        """Transition to SPEAKING (with hysteresis)."""
        if self.status == InputStatus.SILENT:
            # First voice detection
            if self.voice_detected_from_ms is None:
                self.voice_detected_from_ms = now_ms

            # Check hysteresis
            elapsed = now_ms - self.voice_detected_from_ms
            if elapsed < hysteresis_ms:
                return False  # Not enough sustained voice

            # Transition to SPEAKING
            self.status = InputStatus.SPEAKING
            self.voice_detected_last_ms = now_ms
            return True

        # Already speaking - just update timestamp
        self.voice_detected_last_ms = now_ms
        return False

    def on_silence_detected(self, now_ms: int, silence_threshold: int) -> bool:
        """Transition to SILENT."""
        if self.status == InputStatus.SPEAKING:
            if (now_ms - self.voice_detected_last_ms) > silence_threshold:
                self.status = InputStatus.SILENT
                self.voice_detected_from_ms = None
                return True
        return False
```

**States**:
- `SILENT`: No voice detected
- `SPEAKING`: Voice detected (with hysteresis)

**Transitions**:
- Voice detected (100ms hysteresis) → `SPEAKING`
- Silence detected (350ms threshold) → `SILENT`

---

## Audio Processing Pipeline

### Audio Batching (`gateways/acs/audio.py`)

**Auto-commit on three triggers.**

```python
class AudioMessageHandler:
    """Buffer and batch audio per participant."""

    def __init__(self, pipeline: SessionPipeline, config: Config):
        self.pipeline = pipeline
        self.config = config
        self.batching = config.dispatch.batching

        # Per-participant buffers
        self.buffers: Dict[Tuple[str, str], ParticipantBuffer] = {}

    async def handle(self, event: GatewayInputEvent):
        """Handle audio message: buffer, check triggers, auto-commit."""
        participant_id = event.payload["audioData"]["participantRawID"]
        audio_data = event.payload["audioData"]["data"]  # Base64

        # Decode base64 → PCM bytes
        pcm_bytes = base64.b64decode(audio_data)

        # Get or create buffer
        key = (event.session_id, participant_id)
        if key not in self.buffers:
            self.buffers[key] = ParticipantBuffer()

        buffer = self.buffers[key]

        # Append to buffer
        buffer.append(pcm_bytes)

        # Calculate duration
        duration_ms = AudioDurationCalculator.calculate(
            byte_count=len(buffer.data),
            sample_rate=16000,
            channels=1
        )

        # Check auto-commit triggers
        trigger = self._check_triggers(buffer, duration_ms)

        if trigger:
            await self._commit(event.session_id, participant_id, buffer, trigger)
            buffer.clear()

    def _check_triggers(self, buffer: ParticipantBuffer, duration_ms: float) -> Optional[str]:
        """Check if any trigger condition met."""
        now_ms = MonotonicClock.now_ms()

        # Trigger 1: Size
        if len(buffer.data) >= self.batching.max_batch_bytes:
            return "size_threshold"

        # Trigger 2: Duration
        if duration_ms >= self.batching.max_batch_ms:
            return "duration_threshold"

        # Trigger 3: Idle
        if buffer.last_append_ms:
            idle_ms = now_ms - buffer.last_append_ms
            if idle_ms >= self.batching.idle_timeout_ms:
                return "idle_timeout"

        return None

    async def _commit(
        self,
        session_id: str,
        participant_id: str,
        buffer: ParticipantBuffer,
        trigger: str
    ):
        """Commit buffer to provider."""
        commit_id = str(uuid.uuid4())

        # Encode PCM → Base64
        b64_audio = base64.b64encode(buffer.data).decode("utf-8")

        # Calculate silence (RMS energy)
        rms = calculate_rms(buffer.data)
        is_silence = rms < 50.0

        # Create provider input event
        event = ProviderInputEvent(
            commit_id=commit_id,
            session_id=session_id,
            participant_id=participant_id,
            b64_audio_string=b64_audio,
            metadata={
                "timestamp": MonotonicClock.now_ms(),
                "rms": rms,
                "is_silence": is_silence,
                "trigger": trigger
            }
        )

        # Publish to provider outbound bus
        await self.pipeline.provider_outbound_bus.publish(event)

        logger.info(
            f"auto_commit_triggered session={session_id} participant={participant_id} "
            f"trigger={trigger} bytes={len(buffer.data)} is_silence={is_silence}"
        )
```

**Three Auto-Commit Triggers**:
1. **Size**: `accumulated_bytes >= max_batch_bytes` (default: 65536)
2. **Duration**: `accumulated_duration_ms >= max_batch_ms` (default: 200ms)
3. **Idle**: No new audio for `>= idle_timeout_ms` (default: 500ms)

### Silence Detection

**RMS Energy Calculation**:
```python
def calculate_rms(pcm_bytes: bytes) -> float:
    """Calculate RMS energy of PCM16 audio."""
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    rms = np.sqrt(np.mean(samples.astype(np.float32) ** 2))
    return float(rms)
```

**Threshold**: 50.0
- Below threshold → `is_silence = True`
- Above threshold → `is_silence = False`

**Usage**: Control plane uses `is_silence` flag for input state transitions.

### Audio Format Conversion

**PCM Utilities** (`audio/pcm.py`):
```python
class PcmConverter:
    @staticmethod
    def mono_to_stereo(mono_pcm: bytes) -> bytes:
        """Duplicate mono channel to create stereo."""

    @staticmethod
    def stereo_to_mono(stereo_pcm: bytes) -> bytes:
        """Average left and right channels."""

    @staticmethod
    def resample(pcm: bytes, from_rate: int, to_rate: int, channels: int) -> bytes:
        """Resample audio using audioop.ratecv."""
```

**Format Resolution** (`gateways/provider/audio/format_resolver.py`):
- Detect ACS format from metadata
- Detect provider format from provider type
- Determine if conversion needed

---

## Configuration System

### Three-Layer Configuration

**Priority (highest to lowest)**:
1. **Environment Variables** (`VT_*` prefix)
2. **YAML Files** (merged left-to-right)
3. **Default Config** (hardcoded)

### YAML Configuration Format

```yaml
system:
  host: 0.0.0.0               # Server host address
  port: 8080                  # Server port
  log_level: INFO             # DEBUG, INFO, WARNING, ERROR
  log_wire: false             # Enable wire-level logging
  log_wire_dir: logs/server   # Wire log directory
  default_provider: mock      # Default provider name

dispatch:
  batching:
    enabled: true
    max_batch_ms: 200         # Duration trigger
    max_batch_bytes: 65536    # Size trigger
    idle_timeout_ms: 500      # Idle trigger

providers:
  mock:
    type: mock

  openai:
    type: openai
    endpoint: wss://api.openai.com/v1/realtime
    api_key: ${OPENAI_API_KEY}
    settings:
      model: gpt-4o-realtime-preview-2024-10-01

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

  live_interpreter:
    type: live_interpreter
    region: eastus2
    api_key: ${LIVE_INTERPRETER_API_KEY}
    settings:
      languages: [en-US, es-ES, fr-FR, de-DE]
      voice: es-ES-ElviraNeural

buffering:
  ingress_queue_max: 2000     # Max ACS inbound queue size
  egress_queue_max: 2000      # Max ACS outbound queue size
  overflow_policy: DROP_OLDEST
```

### Environment Variable Overrides

**Format**: `VT_{SECTION}_{SUBSECTION}_{PROPERTY}`

**Examples**:
```bash
# System
VT_SYSTEM_LOG_LEVEL=DEBUG
VT_SYSTEM_LOG_WIRE=true

# Provider
VT_DISPATCH_DEFAULT_PROVIDER=voicelive
VT_PROVIDERS_VOICELIVE_API_KEY=your-api-key
VT_PROVIDERS_VOICELIVE_SETTINGS_MODEL=gpt-realtime-mini

# Batching
VT_DISPATCH_BATCHING_ENABLED=true
VT_DISPATCH_BATCHING_MAX_BATCH_MS=300

# Buffering
VT_BUFFERING_INGRESS_QUEUE_MAX=5000
```

**Type Conversion**:
- Boolean: `true/false`, `yes/no`, `1/0`, `on/off`
- Integer: `123`, `-456`
- Float: `1.5`, `0.8`
- String: passthrough
- None: `null`, `none`, `""` (empty)

**Implementation**: `utils/env_config.py` with `apply_env_overrides()`.

See [ENV_CONFIG.md](ENV_CONFIG.md) for complete reference.

---

## Message Flow Examples

### Example 1: Complete Translation Flow

```
1. ACS Client → WebSocket Connect
   ↓
2. ACSServer accepts connection
   ↓
3. SessionManager creates Session with UUID
   ↓
4. Session.run() starts
   ├─ Create SessionPipeline
   ├─ Call start_acs_processing()
   ├─ Subscribe to acs_outbound_bus
   └─ Start receive loop
   ↓
5. ACS Client → First AudioData message:
   {
     "kind": "AudioData",
     "metadata": {"provider": "voicelive"},
     "audioData": {
       "participantRawID": "user-123",
       "data": "UklGR...",  // Base64 PCM
       "sampleRate": 16000,
       "channels": 1
     }
   }
   ↓
6. Session receive loop:
   ├─ Parse JSON
   ├─ Create GatewayInputEvent
   └─ Publish to acs_inbound_bus
   ↓
7. AudioMetadataHandler:
   ├─ Extract metadata: provider=voicelive
   ├─ Call pipeline.start_provider_processing("voicelive")
   ├─ VoiceLiveProvider created and started
   └─ Provider handlers registered
   ↓
8. AudioMessageHandler (subsequent messages):
   ├─ Decode Base64 → PCM bytes
   ├─ Append to participant buffer
   ├─ Check auto-commit triggers
   └─ Commit triggered (duration: 220ms >= 200ms)
   ↓
9. Create ProviderInputEvent:
   {
     commit_id: "abc-123",
     session_id: "sess-001",
     participant_id: "user-123",
     b64_audio_string: "UklGR...",
     metadata: {
       timestamp: 1234567890,
       rms: 150.5,
       is_silence: false,
       trigger: "duration_threshold"
     }
   }
   ↓
10. Publish to provider_outbound_bus
    ↓
11. VoiceLiveProvider egress handler:
    ├─ Consume from bus
    ├─ Format for Voice Live protocol
    └─ Send via WebSocket to Voice Live
    ↓
12. Voice Live processes audio
    ↓
13. Voice Live → Translation response:
    {
      "type": "response.audio_transcript.delta",
      "delta": "Hola, ¿cómo estás?"
    }
    ↓
14. VoiceLiveProvider ingress handler:
    ├─ Receive from WebSocket
    ├─ Create ProviderOutputEvent
    └─ Publish to provider_inbound_bus
    ↓
15. ProviderOutputHandler:
    ├─ Consume from bus
    ├─ Convert to ACS format
    └─ Publish to acs_outbound_bus
    ↓
16. AcsWebsocketSendHandler:
    ├─ Consume from bus
    └─ Send via WebSocket to ACS
    ↓
17. ACS Client ← Translation result:
    {
      "type": "translation.text_delta",
      "participantRawID": "user-123",
      "text": "Hola, ¿cómo estás?"
    }
```

### Example 2: Provider Selection Priority

**Scenario A: Test Settings Override**
```json
// First message
{"kind": "AudioData", "metadata": {"provider": "openai"}}

// Later: Control message
{"type": "control.test.settings", "provider": "voicelive"}

// Result: Provider switches to voicelive
```

**Scenario B: Metadata Provider**
```json
// First message
{"kind": "AudioData", "metadata": {"provider": "voicelive"}}

// Result: Uses voicelive (no test settings)
```

**Scenario C: Feature Flag**
```json
// First message
{"kind": "AudioData", "metadata": {"feature_flags": {"use_voicelive": true}}}

// Result: Uses voicelive (legacy support)
```

**Scenario D: Config Default**
```yaml
# config.yml
system:
  default_provider: mock
```
```json
// First message (no metadata)
{"kind": "AudioData", "audioData": {...}}

// Result: Uses mock provider
```

---

## Testing Strategy

### Unit Tests

**Components to Test**:
- SessionManager (create, remove, shutdown)
- EventBus (publish, fan-out, overflow)
- BoundedQueue (overflow policies)
- AudioBatching (trigger detection)
- InputState (state transitions with hysteresis)
- PlaybackState (state transitions)
- Environment config (type conversion, overrides)

**Example**:
```python
@pytest.mark.asyncio
async def test_session_manager_create():
    config = Config()
    manager = SessionManager(config)

    session = await manager.create_session(mock_websocket, mock_context)

    assert session.session_id in manager.sessions
    assert manager.get_active_count() == 1
```

### Integration Tests with Mock Provider

**Full Pipeline Test**:
```python
@pytest.mark.asyncio
async def test_full_translation_pipeline():
    # Start server
    config = Config(system=SystemConfig(default_provider="mock"))
    server = ACSServer(config, host="127.0.0.1", port=8765)

    # Start server in background
    server_task = asyncio.create_task(server.start())

    # Connect as ACS client
    async with websockets.connect("ws://127.0.0.1:8765") as ws:
        # Send audio message
        await ws.send(json.dumps({
            "kind": "AudioData",
            "metadata": {"provider": "mock"},
            "audioData": {
                "participantRawID": "test-user",
                "data": base64_audio,
                "sampleRate": 16000,
                "channels": 1
            }
        }))

        # Receive translation
        response = await ws.recv()
        result = json.loads(response)

        assert result["type"] == "translation.text_final"
        assert "translated" in result["text"]
```

### Load Testing

**Concurrent Sessions**:
```python
async def test_concurrent_sessions():
    config = Config()
    server = ACSServer(config)

    # Start server
    server_task = asyncio.create_task(server.start())

    # Create 100 concurrent connections
    tasks = []
    for i in range(100):
        task = asyncio.create_task(connect_and_translate(i))
        tasks.append(task)

    # Wait for all
    await asyncio.gather(*tasks)

    # Verify isolation
    assert server.session_manager.get_active_count() == 100
```

---

## Design Patterns

### 1. Event-Driven Architecture (Pub/Sub)

**Pattern**: Fan-out pub/sub with independent queues per subscriber.

**Benefits**:
- Decouples producers from consumers
- Each handler processes at own pace
- Easy to add new handlers
- Clean separation of concerns

**Example**: `EventBus` with multiple handlers on `acs_inbound_bus`.

### 2. Pipeline Pattern

**Pattern**: Chain of processing stages (ACS → Pipeline → Provider → Pipeline → ACS).

**Benefits**:
- Clear data flow
- Easy to insert new stages
- Testable in isolation

**Example**: `SessionPipeline` with 4 event buses.

### 3. State Machine Pattern

**Pattern**: Explicit states with defined transitions.

**Benefits**:
- Clear state representation
- Prevents invalid transitions
- Easy to debug

**Examples**:
- `PlaybackState` (IDLE → SPEAKING → FINISHED)
- `InputState` (SILENT ↔ SPEAKING)

### 4. Factory Pattern

**Pattern**: Dynamic object creation based on type.

**Benefits**:
- Centralized creation logic
- Easy to add new types
- Encapsulates configuration

**Example**: `ProviderFactory.create_provider()`.

### 5. Protocol/Interface Pattern

**Pattern**: Define interfaces without concrete implementation.

**Benefits**:
- Loose coupling
- Substitutability (Liskov)
- Easy mocking for tests

**Examples**:
- `TranslationProvider` protocol
- `SessionPipelineProtocol` for control plane actuator

### 6. Bounded Context Pattern

**Pattern**: Complete isolation of session state.

**Benefits**:
- No cross-session contamination
- Horizontal scalability
- Independent failure domains

**Example**: Each `Session` with own `SessionPipeline`, buses, provider.

### 7. Gateway Pattern

**Pattern**: Protocol adapters convert between formats.

**Benefits**:
- Isolates protocol details
- Easy to swap protocols
- Testable adapters

**Examples**:
- `AudioMessageHandler` (ACS → internal)
- `ProviderOutputHandler` (provider → ACS)

---

## Summary

The Voice Translation Server implements a **production-ready, event-driven architecture** with:

✅ **Server-side WebSocket** pattern (listens for connections)
✅ **Complete session isolation** (no cross-session state)
✅ **Event bus fan-out** (independent handler queues)
✅ **Dynamic provider selection** (per session, priority-based)
✅ **Control plane** (playback/input state management)
✅ **Audio batching** (size/duration/idle triggers)
✅ **Configurable system** (YAML + environment overrides)
✅ **Horizontal scalability** (stateless, session-isolated)
✅ **Multi-provider support** (Mock, OpenAI, Voice Live, Live Interpreter, Role-Based)

The architecture is designed for **production deployment** with clean abstractions, comprehensive error handling, and operational observability.

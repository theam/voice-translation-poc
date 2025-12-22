# Translation Service Architecture Summary

![High-level architecture](Translation%20Service%20Architecture.pdf)

## Purpose
- Deliver real-time, two-way translation between two languages for phone conversations where the system joins as a third participant on the call.
- Keep latency low while handling multiple simultaneous participants and voice pipelines.
- Work with the existing signaling and media plumbing so callers do not need to change how they place or receive calls.

## Core Components (per `server/`)
- **ACS WebSocket Server (`core/acs_server.py`)**: Listens for inbound ACS WebSocket connections and spins up one session per connection.
- **Session Manager (`session/session_manager.py`)**: Creates and tracks sessions, ensuring cleanup on disconnect.
- **Session (`session/session.py`)**: Reads initial metadata to pick routing strategy (`shared` vs `per_participant`) and provider, then routes each envelope to the correct participant pipeline.
- **Participant Pipelines (`session/participant_pipeline.py`)**: One pipeline per participant, each with four dedicated event buses (ACS inbound/outbound, provider outbound/inbound), its own provider adapter, and isolated buffering.
- **Gateways/Handlers (`gateways/`)**: `AcsInboundMessageHandler` batches/dispatches audio to the provider; `ProviderResultHandler` converts provider responses back to ACS frames; `AuditHandler` records traffic for tracing.
- **Provider Adapters (`providers/`)**: Created via `ProviderFactory`; adapters start/close per pipeline so each participant can hold an independent provider session (e.g., VoiceLive, Mock) and avoid the single-output-language limitation of Live Interpreter.
- **Configuration (`config.py`)**: Controls defaults for provider choice, batching, queue sizes, and overflow policies that shape latency vs. cost per pipeline.

## Per-Participant Pipeline
- Each participant is assigned a **dedicated translation pipeline** (ASR → translation → TTS) with its own provider session.
- This design bypasses the Live Interpreter limitation of a **single output audio language per session** by isolating language targets per participant.
- Pipelines are independently configurable (target language, voice, latency/cost profiles) and can be scaled or restarted without impacting others or the orchestrator.

## Routing Strategies & Provider Choice
- **Routing modes**: The session reads the first ACS message’s metadata to decide between `shared` (all participants share one pipeline) and `per_participant` (one pipeline per caller). Feature flags can also force per-participant mode (`feature_flags.per_participant_pipelines`), and providers that require isolation push the same choice.
- **Provider selection**: For each pipeline, the session checks per-participant overrides (`participant_providers`), an explicit `provider` field, feature flags (e.g., `use_voicelive`), then falls back to the default in `dispatch.provider`. This keeps the provider session bound to the participant, which is crucial when Live Interpreter can emit only one audio language per session.
- **Dynamic startup**: In shared mode, the first participant message starts the shared pipeline immediately. In per-participant mode, pipelines are created lazily when each participant first speaks, conserving resources until needed.

## Flow Overview (grounded in `server/` implementation)
1. **Connect**: ACS opens a WebSocket to the ACS server; the Session Manager instantiates a `Session`.
2. **Initialize**: The first ACS frame provides metadata. The session chooses routing (`shared` or `per_participant`) and provider, then starts the needed pipeline(s) and subscribes their outbound buses back to the WebSocket.
3. **Ingest**: Incoming ACS frames are converted to `Envelope` objects and published to the participant’s `acs_inbound_bus`. `AcsInboundMessageHandler` applies batching per config and pushes audio requests onto the `provider_outbound_bus`.
4. **Provider Exchange**: The participant’s provider adapter (from `ProviderFactory`) streams audio to the chosen provider over its own session and publishes translation results onto the `provider_inbound_bus`.
5. **Process & Emit**: `ProviderResultHandler` transforms provider responses into ACS-format messages and publishes them to `acs_outbound_bus`, which sends them back over the same WebSocket connection.
6. **Cleanup**: On disconnect or shutdown, each pipeline closes its provider session, drains/shuts down event buses, and releases per-participant resources without affecting other participants.

## Pipeline Internals (per participant)
- **Event buses**: Four isolated buses (`acs_inbound`, `provider_outbound`, `provider_inbound`, `acs_outbound`) keep backpressure local to one participant.
- **Handlers**: `AuditHandler` captures traffic traces; `AcsInboundMessageHandler` batches audio based on `dispatch.batching`; `ProviderResultHandler` reformats provider responses. Each handler inherits queue limits and overflow policy from `config.buffering`, preventing a noisy participant from blocking others.
- **Provider lifecycle**: Each pipeline instantiates and starts its own provider adapter, which maintains the live connection to the translation service. On cleanup, the adapter closes independently, ensuring other participants continue unaffected.

## Operational Notes
- **Resilience**: Per-pipeline isolation limits blast radius; retries and health checks are scoped to the affected participant.
- **Scalability**: Horizontal scaling by adding pipeline workers; orchestrator distributes load based on active participants.
- **Extensibility**: New providers or languages can be added by extending adapters without changing pipeline orchestration.

## End-to-End Conversation Fit
- **Phone-call posture**: The system acts as a neutral third participant, ingesting audio from both callers, translating bi-directionally, and emitting synthesized audio back to each caller in their preferred language.
- **Turn-taking and barge-in**: Pipelines handle partial ASR results to minimize delay, enabling near-live responses during overlapping speech common in phone dialogues.
- **Audio hygiene**: Normalization and optional noise reduction keep the translated output intelligible despite line-quality variability typical of telephony.

## What Stays Consistent Across Routing Modes
- **Single ACS connection per call**: One WebSocket connection anchors the call and carries all participant traffic; isolation happens inside the session via pipelines.
- **Envelope translation layer**: ACS frames are converted to `Envelope` objects at ingress and back to ACS payloads at egress, so downstream gateways stay consistent regardless of routing strategy.
- **Result contract**: Provider results are emitted as `translation.result` payloads with `partial` flags and `commit_id` fields, keeping client behavior identical whether the call uses shared or per-participant pipelines.

## Two-Way Call Timeline (per `per_participant` routing)
1. Caller A speaks first → metadata requests `per_participant` and provider `voicelive`; the session spins up Pipeline A and starts a VoiceLive adapter.
2. Caller B joins later → their first audio frame triggers Pipeline B creation; provider defaults to `dispatch.provider` if not overridden.
3. Each pipeline batches its own audio and receives its own translations. Partial results can be forwarded immediately while commits finalize the utterance.
4. If Caller A drops, Pipeline A closes its provider session and buses. Pipeline B keeps running so Caller B can continue receiving translations if they keep talking.

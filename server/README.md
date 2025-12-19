# Translation Service Core (server)

This directory contains a new implementation of the core translation service runtime. It focuses on a modular event-driven pipeline that receives messages from Azure Communication Services (ACS), applies bounded buffering and fan-out to independent handlers, dispatches work to translation providers, and delivers results to egress destinations.

## Goals
- Non-blocking WebSocket ingestion from ACS.
- Bounded queues with explicit overflow policies.
- Fan-out event buses so slow handlers do not block the translation path.
- Configurable provider selection (mock, VoiceLive, Live Interpreter placeholders).
- Structured logging and optional payload capture.

## Layout
- `config.py` — configuration models and loader.
- `envelope.py` — normalized envelope used internally.
- `queues.py` — bounded queue implementation with overflow policies.
- `event_bus.py` — fan-out event bus with per-handler queues.
- `handlers/` — independent handlers (audit, translation dispatch, provider result routing).
- `providers/` — provider interfaces and implementations.
- `adapters/` — ingress/egress adapters for ACS-compatible WebSockets.
- `service.py` — orchestrates the runtime, wiring buses, adapters, handlers, and providers.
- `payload_capture.py` — optional payload capture utilities.

## Running
A minimal bootstrap is provided via `ServiceApp` in `service.py`. Configure via YAML or environment variables, then start the service:

```bash
python -m server.service --config path/to/config.yml
```

The service is designed to be testable without external dependencies by using the `MockProvider`.

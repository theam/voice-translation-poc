# ACS Emulator Web Client

This subproject provides a FastAPI backend and Vite frontend for an ACS emulator web UI.

## Requirements

- Python 3.12+
- Poetry
- Node.js 18+

## Setup

```bash
make install
make fe-install
make fe-build
make fe-copy
```

## Run

```bash
make run
```

Open <http://localhost:8000> in your browser.

## Configuration

The backend connects upstream using the same ACS protocol as the production evaluations runner.

Environment variables:

- `TRANSLATION_WEBSOCKET_URL` (default: `ws://localhost:8080/ws`)
- `TRANSLATION_WS_AUTH` (optional)
- `TRANSLATION_CONNECT_TIMEOUT` (default: `10`)
- `TRANSLATION_DEBUG_WIRE` (`true`/`false`)
- `ACS_WEBCLIENT_CALL_TTL_MINUTES` (default: `10`)
- `ACS_WEBCLIENT_CLEANUP_INTERVAL_SECONDS` (default: `60`)
- `ACS_WEBCLIENT_SERVER_CONFIGS` (comma-separated paths to server config YAMLs)

The `/api/test-settings` endpoint reports providers from the server config and supports barge-in modes:
`play_through`, `pause_and_buffer`, `pause_and_drop`.

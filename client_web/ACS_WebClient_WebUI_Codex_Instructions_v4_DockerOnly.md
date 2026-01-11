# Codex Instructions (v4): Web UI ACS Emulator Client — Docker-only Build & Run

This updates v3 to enforce **Docker-only** workflows:

- **All building and running is done through Docker**.
- The `Makefile` and `README` must **not** include native commands like `poetry install`, `npm ci`, `npm run`, or `uvicorn`.
- The only allowed commands exposed to users are **`make docker-*`** targets (which invoke Docker).

Frontend stack remains:
- **Vite**
- **Vanilla JS (ES modules)**
- **Web Components**
- **Web Audio API**
- **Tiny CSS** (`base.css`)

Backend remains:
- **Python (FastAPI)**, single upstream WS per call to the translation service using **existing ACS protocol**.

---

## Non-negotiable constraints (unchanged)

1. **Upstream integration is WebSocket only**.
2. Upstream messages must use the **existing ACS protocol** already implemented in this repo.
3. **Do not invent new ACS message types/fields**.
4. Do **not** send/consume anything upstream that the **production/evaluations** framework does not already send/consume.
5. “Create call” supports **only** `provider` and `barge_in`, validated against `server/acs/test_settings`.
6. **Joining a call is emulator-local**: multiple participants join the same call code and their audio is multiplexed into a **single upstream WS**.
7. **Docker-only**: build and run via Docker (including FE build).

---

## 1) Subproject layout: `client_web/`

Create (or update) the subproject:

```
client_web/
  README.md
  Makefile
  Dockerfile               # multi-stage: FE build + Python runtime
  docker-compose.yml       # optional but recommended
  src/
    acs_webclient/
      __init__.py
      main.py
      config.py
      calls.py
      upstream.py
      protocol/
        __init__.py
        acs.py
      web/
        static/            # FE build artifacts copied here during docker build
  frontend/
    index.html
    vite.config.js
    package.json
    src/
      main.js
      router.js
      api.js
      state.js
      styles/base.css
      audio/capture.js
      audio/playback.js
      audio/pcm16.js
      components/
        app-shell.js
        create-call.js
        join-call.js
        call-room.js
        event-log.js
        participant-list.js
```

---

## 2) Makefile — Docker-only targets

### 2.1 Rules
- **No** targets that run `poetry`, `npm`, `node`, `uvicorn` directly on the host.
- Only Docker commands are allowed.
- If you provide non-make examples in the README, they must also be Docker-only.

### 2.2 Required Make targets
Implement these targets in `client_web/Makefile`:

- `docker-build`  
  Builds the Docker image for the webclient.

- `docker-run`  
  Runs the container (foreground) exposing the web UI port.

- `docker-run-detached`  
  Runs the container detached.

- `docker-logs`  
  Shows container logs.

- `docker-stop`  
  Stops the running container.

- `docker-clean`  
  Removes container(s) and optionally image.

If you prefer `docker compose`, then:
- `docker-build` → `docker compose build`
- `docker-run` → `docker compose up`
- `docker-stop` → `docker compose down`
etc.

> Choose **one** approach (plain docker or docker compose) and keep it consistent.

---

## 3) README — Docker-only usage

The `client_web/README.md` must include only Docker-based instructions.

### 3.1 Example README content (required pattern)

**Build**
- `make docker-build`

**Run**
- `make docker-run`

**Stop**
- `make docker-stop`

Then describe:
- Open the UI at `http://localhost:<port>/`

No mention of `npm`, `node`, `poetry`, or `uvicorn` commands.

---

## 4) Dockerfile — must build FE inside Docker

### 4.1 Multi-stage Dockerfile (required)
Implement a multi-stage build:

**Stage A: Frontend build**
- base: `node:<LTS>`
- workdir: `/app/frontend`
- copy `frontend/package.json` (+ lockfile if present)
- `npm ci`
- copy `frontend/`
- `npm run build` (outputs `/app/frontend/dist`)

**Stage B: Python runtime**
- base: python image consistent with repo (e.g. `python:3.11-slim`)
- install poetry *or* install dependencies via exported requirements

**Important:** even if you use Poetry, do it inside Docker only.  
No host Poetry usage.

- copy backend source (`src/`)
- copy FE build output from Stage A into:
  - `src/acs_webclient/web/static/`
- expose port (e.g., `8000`)
- entrypoint runs the FastAPI app (e.g. `uvicorn acs_webclient.main:app --host 0.0.0.0 --port 8000`)

### 4.2 Dependency strategy
You have two acceptable options:

**Option 1: Poetry inside Docker**
- Copy `pyproject.toml` and `poetry.lock` into image
- Install poetry in image
- `poetry install --only main` (or equivalent)

**Option 2: Export requirements**
- Keep Poetry for dependency definition
- During Docker build:
  - install poetry
  - `poetry export -f requirements.txt ...`
  - `pip install -r requirements.txt`

Pick whichever is consistent with the rest of your repo’s Docker patterns.

---

## 5) docker-compose.yml (recommended)

Provide `client_web/docker-compose.yml` to simplify running:

- service `client-web`
  - build: `./`
  - ports: `"8000:8000"`
  - environment:
    - translation service WS endpoint
    - any required auth/config env vars
  - restart: unless-stopped (optional)

If you use compose, update Make targets accordingly.

---

## 6) Frontend instructions (unchanged from v3, but ensure Docker build copies dist)

Frontend must remain:
- Vite + Vanilla JS + Web Components
- base.css styling
- mic capture + PCM16 framing
- playback queues for participant/service audio

**Critical build requirement:** the FE build output must be copied into backend static folder during docker build.

---

## 7) Backend instructions (unchanged, but ensure Docker env driven)

Backend must:
- host `/` static FE
- expose `/api/test-settings` (proxy to `server/acs/test_settings`)
- expose `/api/call/create` (provider + barge_in only)
- expose `WS /ws/participant`
- maintain one upstream WS per call and multiplex participants

All configuration (upstream endpoint, keys, etc.) must be supplied via **environment variables** in Docker / compose.

---

## 8) Acceptance criteria (Docker-only)

1. `make docker-build` succeeds from a clean machine with only Docker installed.
2. `make docker-run` starts the service; UI loads in browser.
3. Creating a call works (provider + barge_in from `/api/test-settings`).
4. Multiple laptops can join the same call code and exchange audio via the backend.
5. All upstream ACS messaging remains identical to evaluations (no new ACS messages).

---

## Notes to Codex

- Ensure the `Makefile` contains **only** Docker targets.
- Ensure the `README` contains **only** Docker-based commands.
- The Dockerfile must build both FE and backend without requiring any host tooling.

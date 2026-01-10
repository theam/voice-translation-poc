from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .calls import CallRegistry
from .config import WebClientConfig, load_server_config
from .upstream import UpstreamConfig

logger = logging.getLogger(__name__)

app = FastAPI()
config = WebClientConfig.from_env()
server_config = load_server_config(config.server_config_paths)

static_dir = Path(__file__).parent / "web" / "static"
assets_dir = static_dir / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

registry = CallRegistry(
    upstream_config=UpstreamConfig(
        websocket_url=config.translation_ws_url,
        auth_key=config.translation_ws_auth,
        connect_timeout=config.connect_timeout,
        debug_wire=config.debug_wire,
    ),
    ttl_minutes=config.call_ttl_minutes,
)


@app.on_event("startup")
async def _startup_cleanup_task() -> None:
    asyncio.create_task(_cleanup_loop())


async def _cleanup_loop() -> None:
    while True:
        try:
            await registry.cleanup_expired()
        except Exception as exc:
            logger.warning("Cleanup loop error: %s", exc)
        await asyncio.sleep(config.cleanup_interval_seconds)


@app.get("/")
async def serve_index() -> HTMLResponse:
    return _load_index()


@app.get("/join/{call_code}")
async def serve_join(call_code: str) -> HTMLResponse:
    return _load_index()


@app.get("/api/test-settings")
async def get_test_settings() -> Dict[str, Any]:
    providers = sorted(server_config.providers.providers.keys())
    barge_in = ["play_through", "pause_and_buffer", "pause_and_drop"]
    return {
        "providers": providers,
        "barge_in": barge_in,
    }


@app.post("/api/call/create")
async def create_call(payload: Dict[str, Any]) -> Dict[str, Any]:
    provider = payload.get("provider")
    barge_in = payload.get("barge_in")
    if not provider or not isinstance(provider, str):
        raise HTTPException(status_code=400, detail="provider is required")
    if not barge_in or not isinstance(barge_in, str):
        raise HTTPException(status_code=400, detail="barge_in is required")

    settings = await get_test_settings()
    if provider not in settings["providers"]:
        raise HTTPException(status_code=400, detail="unsupported provider")
    if barge_in not in settings["barge_in"]:
        raise HTTPException(status_code=400, detail="unsupported barge_in")

    session = await registry.create_call(provider=provider, barge_in=barge_in)
    return {
        "call_code": session.call_code,
        "provider": provider,
        "barge_in": barge_in,
    }


@app.websocket("/ws/participant")
async def participant_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    participant_id = None
    session = None
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            if "text" in message and message["text"] is not None:
                try:
                    payload = json.loads(message["text"])
                except json.JSONDecodeError:
                    await websocket.send_json({"type": "error", "message": "invalid JSON payload"})
                    continue
                message_type = payload.get("type")

                if message_type == "join":
                    call_code = payload.get("call_code")
                    display_name = payload.get("display_name")
                    if not call_code or not display_name:
                        await websocket.send_json({"type": "error", "message": "call_code and display_name required"})
                        continue
                    session = await registry.get_call(call_code)
                    if not session:
                        await websocket.send_json({"type": "error", "message": "call not found"})
                        continue
                    participant_id = await session.add_participant(websocket, display_name)
                    continue

                if message_type == "leave":
                    break

                if message_type == "mute" and participant_id and session:
                    muted = bool(payload.get("muted", False))
                    await session.set_muted(participant_id, muted)
                    continue

                if message_type == "audio.start":
                    continue

            if "bytes" in message and message["bytes"] is not None:
                if participant_id and session:
                    await session.handle_audio(participant_id, message["bytes"])
    except WebSocketDisconnect:
        pass
    finally:
        if participant_id and session:
            await session.remove_participant(participant_id)
        await websocket.close()


def _load_index() -> HTMLResponse:
    index_path = static_dir / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Frontend not built</h1>")
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    uvicorn.run(app, host="0.0.0.0", port=8000)


__all__ = ["app", "main"]

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .calls import CallManager
from .config import Settings

logger = logging.getLogger(__name__)

settings = Settings.from_env()
call_manager = CallManager(settings)

app = FastAPI()

static_root = Path(__file__).parent / "web" / "static"
app.mount("/assets", StaticFiles(directory=static_root / "assets"), name="assets")


@app.get("/")
async def index() -> FileResponse:
    index_path = static_root / "index.html"
    return FileResponse(index_path)


@app.get("/api/test-settings")
async def test_settings() -> Dict[str, Any]:
    return {
        "providers": settings.allowed_providers,
        "barge_in_modes": settings.allowed_barge_in_modes,
    }


@app.post("/api/call/create")
async def create_call(payload: Dict[str, Any]) -> Dict[str, Any]:
    provider = payload.get("provider")
    barge_in = payload.get("barge_in")

    if provider not in settings.allowed_providers:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    if barge_in not in settings.allowed_barge_in_modes:
        raise HTTPException(status_code=400, detail="Unsupported barge-in mode")

    call_state = call_manager.create_call(provider=provider, barge_in=barge_in)
    return {"call_code": call_state.call_code}


@app.websocket("/ws/participant")
async def participant_socket(websocket: WebSocket, call_code: str, participant_id: str) -> None:
    if not call_code:
        await websocket.close(code=4400)
        return
    if not participant_id:
        await websocket.close(code=4401)
        return

    call_state = call_manager.get_call(call_code)
    if not call_state:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    await call_manager.add_participant(call_code, participant_id, websocket)

    try:
        while True:
            message = await websocket.receive_json()
            await _handle_participant_message(call_state, participant_id, message)
    except WebSocketDisconnect:
        logger.info("Participant %s disconnected", participant_id)
    finally:
        await call_manager.remove_participant(call_state, participant_id)


async def _handle_participant_message(call_state, participant_id: str, message: Dict[str, Any]) -> None:
    message_type = message.get("type")
    if message_type == "audio_metadata":
        sample_rate = int(message.get("sample_rate", 0))
        channels = int(message.get("channels", 1))
        frame_bytes = int(message.get("frame_bytes", 0))
        if sample_rate and frame_bytes:
            await call_state.send_audio_metadata(sample_rate, channels, frame_bytes)
        return

    if message_type == "audio":
        data = message.get("data")
        timestamp_ms = message.get("timestamp_ms")
        if not data:
            return
        pcm_bytes = base64.b64decode(data, validate=False)
        await call_state.send_audio(participant_id, pcm_bytes, timestamp_ms)
        return

from __future__ import annotations

import base64
import logging
import logging.config
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .calls import CallManager
from .config import Settings


def configure_logging() -> None:
    """Configure logging to work properly with uvicorn."""
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "acs_webclient": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
        },
        "root": {
            "level": "INFO",
            "handlers": ["console"],
        },
    }
    logging.config.dictConfig(logging_config)


configure_logging()
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
        "services": settings.available_services,
        "providers": settings.allowed_providers,
        "barge_in_modes": settings.allowed_barge_in_modes,
    }


@app.get("/api/recent-calls")
async def recent_calls() -> Dict[str, Any]:
    return {
        "calls": call_manager.get_recent_calls()
    }


@app.post("/api/call/create")
async def create_call(payload: Dict[str, Any]) -> Dict[str, Any]:
    service = payload.get("service")
    provider = payload.get("provider")
    barge_in = payload.get("barge_in")

    if service not in settings.available_services:
        raise HTTPException(status_code=400, detail="Unsupported service")
    if provider not in settings.allowed_providers:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    if barge_in not in settings.allowed_barge_in_modes:
        raise HTTPException(status_code=400, detail="Unsupported barge-in mode")

    service_url = settings.available_services[service]
    call_state = call_manager.create_call(service=service, service_url=service_url, provider=provider, barge_in=barge_in)
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
        logger.warning("Call not found: %s", call_code)
        await websocket.close(code=4404)
        return

    await websocket.accept()

    # Send immediate acknowledgment to client
    await websocket.send_json({
        "type": "connection.established",
        "message": "WebSocket connected, initializing translation service..."
    })

    try:
        await call_manager.add_participant(call_code, participant_id, websocket)
    except Exception as e:
        logger.error("Failed to connect to upstream service: %s", e)
        await websocket.send_json({
            "type": "error",
            "message": f"Failed to connect to translation service: {str(e)}"
        })
        await websocket.close(code=1011, reason="Upstream connection failed")
        return

    # Notify client that initialization is complete
    await websocket.send_json({
        "type": "connection.ready",
        "message": "Translation service connected"
    })

    try:
        while True:
            message = await websocket.receive_json()
            await _handle_participant_message(call_state, participant_id, message)
    except WebSocketDisconnect:
        logger.info("Participant %s disconnected from call %s", participant_id, call_code)
    finally:
        await call_manager.remove_participant(call_state, participant_id)


async def _handle_participant_message(call_state, participant_id: str, message: Dict[str, Any]) -> None:
    message_type = message.get("type")

    if message_type == "audio":
        data = message.get("data")
        timestamp_ms = message.get("timestamp_ms")
        if not data:
            return
        pcm_bytes = base64.b64decode(data, validate=False)
        await call_state.send_audio(participant_id, pcm_bytes, timestamp_ms)
        return

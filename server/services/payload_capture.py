from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from ..models.gateway_input_event import GatewayInputEvent

logger = logging.getLogger(__name__)


class PayloadCapture:
    def __init__(self, output_dir: str, mode: str = "metadata_only"):
        self.output_dir = Path(output_dir)
        self.mode = mode
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def capture(self, event: GatewayInputEvent) -> None:
        async with self._lock:
            path = self.output_dir / f"{event.event_id}.json"
            payload = event.payload
            data = {
                "metadata": {
                    "session_id": event.session_id,
                    "received_at_utc": event.received_at_utc,
                    "source": event.source,
                },
            }
            if self.mode == "full":
                data["payload"] = payload
            try:
                path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                logger.debug("Captured payload for %s at %s", event.event_id, path)
            except Exception:
                logger.exception("Failed to capture payload for %s", event.event_id)

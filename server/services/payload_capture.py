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

    async def capture(self, envelope: GatewayInputEvent) -> None:
        async with self._lock:
            path = self.output_dir / f"{envelope.event_id}.json"
            data = {
                "metadata": {
                    "session_id": envelope.session_id,
                    "participant_id": envelope.participant_id,
                    "type": envelope.event_type,
                    "timestamp_utc": envelope.timestamp_utc,
                    "source": envelope.source,
                },
            }
            if self.mode == "full":
                data["payload"] = envelope.payload
                data["raw"] = envelope.raw_frame
            try:
                path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                logger.debug("Captured payload for %s at %s", envelope.event_id, path)
            except Exception:
                logger.exception("Failed to capture payload for %s", envelope.event_id)

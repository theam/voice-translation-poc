from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from ..models.envelope import Envelope

logger = logging.getLogger(__name__)


class PayloadCapture:
    def __init__(self, output_dir: str, mode: str = "metadata_only"):
        self.output_dir = Path(output_dir)
        self.mode = mode
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def capture(self, envelope: Envelope) -> None:
        async with self._lock:
            path = self.output_dir / f"{envelope.message_id}.json"
            data = {
                "metadata": {
                    "session_id": envelope.session_id,
                    "participant_id": envelope.participant_id,
                    "commit_id": envelope.commit_id,
                    "type": envelope.type,
                    "timestamp_utc": envelope.timestamp_utc,
                    "source": envelope.source,
                },
            }
            if self.mode == "full":
                data["payload"] = envelope.payload
                data["raw"] = envelope.raw
            try:
                path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                logger.debug("Captured payload for %s at %s", envelope.message_id, path)
            except Exception:
                logger.exception("Failed to capture payload for %s", envelope.message_id)


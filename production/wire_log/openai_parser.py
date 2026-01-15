"""OpenAI websocket log parser for JSONL files."""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .parser import WireLogMessage

logger = logging.getLogger(__name__)


class OpenAIWireLogParser:
    """Parse OpenAI websocket JSONL logs into WireLogMessage objects."""

    def load(self, file_path: Path) -> List[WireLogMessage]:
        """Load OpenAI wire log from JSONL file."""
        if not file_path.exists():
            raise FileNotFoundError(f"Wire log not found: {file_path}")

        messages: List[WireLogMessage] = []
        with open(file_path, "r") as f:
            for line_num, line in enumerate(f, 1):
                try:
                    entry = json.loads(line)
                    msg = self._parse_message(entry)
                    if msg:
                        messages.append(msg)
                except json.JSONDecodeError as exc:
                    logger.warning("Malformed JSON at line %d: %s", line_num, exc)
                except Exception as exc:
                    logger.warning("Failed to parse line %d: %s", line_num, exc)

        logger.info("Parsed %d messages from OpenAI wire log", len(messages))
        return messages

    def _parse_message(self, entry: Dict[str, Any]) -> Optional[WireLogMessage]:
        timestamp_str = entry.get("timestamp")
        if not timestamp_str:
            return None

        wall_clock_timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        message = entry.get("message", {})
        message_type = message.get("type", "")

        if message_type not in {"input_audio_buffer.append", "response.audio.delta"}:
            return None

        data_b64 = message.get("audio") or message.get("delta", "")
        audio_bytes = None
        if data_b64:
            try:
                audio_bytes = base64.b64decode(data_b64)
            except Exception as exc:
                logger.warning("Failed to decode OpenAI audio: %s", exc)

        if audio_bytes is None:
            return None

        if message_type == "input_audio_buffer.append":
            direction = "outbound"
        else:
            direction = "inbound"

        return WireLogMessage(
            wall_clock_timestamp=wall_clock_timestamp,
            direction=direction,
            kind="AudioData",
            audio_data=audio_bytes,
            raw_message=entry,
        )

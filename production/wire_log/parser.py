"""Wire log parser for JSONL files."""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class WireLogMessage:
    """Parsed wire log message."""

    wall_clock_timestamp: datetime  # When message was recorded
    direction: str  # "inbound" | "outbound"
    kind: str  # "AudioData" | "AudioMetadata" | "control.test.settings"

    # For AudioData messages
    participant_id: Optional[str] = None
    scenario_timestamp_ms: Optional[int] = None  # Converted from ISO
    audio_data: Optional[bytes] = None  # Decoded from base64
    is_silent: Optional[bool] = None

    # For text messages
    text_delta: Optional[str] = None

    # Raw message for passthrough
    raw_message: Optional[Dict[str, Any]] = None


class WireLogParser:
    """Parse JSONL wire logs."""

    def load(self, file_path: Path) -> List[WireLogMessage]:
        """Load wire log from JSONL file.

        Args:
            file_path: Path to wire log JSONL file

        Returns:
            List of parsed WireLogMessage objects

        Raises:
            FileNotFoundError: If wire log file doesn't exist
        """
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
                    logger.warning(
                        "Malformed JSON at line %d: %s", line_num, exc
                    )
                    continue
                except Exception as exc:
                    logger.warning(
                        "Failed to parse line %d: %s", line_num, exc
                    )
                    continue

        logger.info("Parsed %d messages from wire log", len(messages))
        return messages

    def _parse_message(self, entry: Dict[str, Any]) -> Optional[WireLogMessage]:
        """Parse a single wire log entry.

        Args:
            entry: JSON object from wire log line

        Returns:
            Parsed WireLogMessage or None if invalid
        """
        try:
            # Parse timestamp
            timestamp_str = entry.get("timestamp")
            if not timestamp_str:
                return None

            wall_clock_timestamp = datetime.fromisoformat(
                timestamp_str.replace("Z", "+00:00")
            )

            direction = entry.get("direction", "")
            message = entry.get("message", {})
            # Get kind from either "kind" or "type" field (control messages use "type")
            kind = message.get("kind") or message.get("type", "")

            # Parse AudioData messages
            if kind.lower() == "audiodata":
                audio_data = message.get("audioData", {})

                # Get participant ID (inbound uses participantRawID, outbound uses participant)
                participant_id = audio_data.get("participantRawID") or audio_data.get(
                    "participant"
                )

                # Parse scenario timestamp
                # Inbound: uses audioData.timestamp (ISO format from scenario)
                # Outbound: timestamp is null, use wall_clock_timestamp instead
                scenario_timestamp_str = audio_data.get("timestamp")
                scenario_timestamp_ms = None

                if scenario_timestamp_str:
                    scenario_timestamp_ms = self._parse_iso_timestamp(
                        scenario_timestamp_str
                    )
                elif direction == "outbound":
                    # For outbound with no scenario timestamp, use wall clock
                    # This gives us chronological ordering
                    scenario_timestamp_ms = self._parse_iso_timestamp(
                        timestamp_str
                    )

                # Decode base64 audio data
                data_b64 = audio_data.get("data", "")
                audio_bytes = None
                if data_b64:
                    try:
                        audio_bytes = base64.b64decode(data_b64)
                    except Exception as exc:
                        logger.warning("Failed to decode base64 audio: %s", exc)

                # Handle both "silent" (inbound) and "isSilent" (outbound)
                is_silent = audio_data.get("silent") or audio_data.get("isSilent", False)

                return WireLogMessage(
                    wall_clock_timestamp=wall_clock_timestamp,
                    direction=direction,
                    kind=kind,
                    participant_id=participant_id,
                    scenario_timestamp_ms=scenario_timestamp_ms,
                    audio_data=audio_bytes,
                    is_silent=is_silent,
                    raw_message=entry,
                )

            # Parse AudioMetadata messages
            elif kind == "AudioMetadata":
                return WireLogMessage(
                    wall_clock_timestamp=wall_clock_timestamp,
                    direction=direction,
                    kind=kind,
                    raw_message=entry,
                )

            # Parse text delta messages
            elif message.get("type") == "control.test.response.text_delta":
                text = message.get("delta", "")
                participant_id = message.get("participant_id")

                return WireLogMessage(
                    wall_clock_timestamp=wall_clock_timestamp,
                    direction=direction,
                    kind="text_delta",
                    participant_id=participant_id,
                    text_delta=text,
                    raw_message=entry,
                )

            # Generic message (preserve for other types)
            else:
                return WireLogMessage(
                    wall_clock_timestamp=wall_clock_timestamp,
                    direction=direction,
                    kind=kind,
                    raw_message=entry,
                )

        except Exception as exc:
            logger.warning("Error parsing message: %s", exc)
            return None

    @staticmethod
    def _parse_iso_timestamp(iso_str: str) -> int:
        """Convert ISO timestamp to milliseconds from epoch.

        Examples:
            - "1970-01-01T00:00:00Z" → 0
            - "1970-01-01T00:00:00.020000Z" → 20
            - "1970-01-01T00:01:02.420000Z" → 62420

        Args:
            iso_str: ISO timestamp string

        Returns:
            Milliseconds from Unix epoch
        """
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        return int((dt - epoch).total_seconds() * 1000)

    def filter_by_direction(
        self, messages: List[WireLogMessage], direction: str
    ) -> List[WireLogMessage]:
        """Filter messages by direction.

        Args:
            messages: List of wire log messages
            direction: Direction to filter ("inbound" or "outbound")

        Returns:
            Filtered list of messages with specified direction
        """
        return [m for m in messages if m.direction == direction]

    def filter_inbound(self, messages: List[WireLogMessage]) -> List[WireLogMessage]:
        """Extract only inbound messages.

        Args:
            messages: List of wire log messages

        Returns:
            Filtered list of inbound messages only
        """
        return self.filter_by_direction(messages, "inbound")

    def filter_outbound(self, messages: List[WireLogMessage]) -> List[WireLogMessage]:
        """Extract outbound messages.

        Args:
            messages: List of wire log messages

        Returns:
            Filtered list of outbound messages only
        """
        return self.filter_by_direction(messages, "outbound")

    def filter_for_replay(self, messages: List[WireLogMessage]) -> List[WireLogMessage]:
        """Filter messages for replay scenario.

        Filters for inbound messages and excludes control.test* messages
        (which will be sent by the framework).

        Args:
            messages: List of wire log messages

        Returns:
            Filtered list of messages ready for replay
        """
        return [
            m for m in messages
            if m.direction == "inbound" and not m.kind.startswith("control.test")
        ]

    def group_by_participant(
        self, messages: List[WireLogMessage]
    ) -> Dict[str, List[WireLogMessage]]:
        """Group messages by participant.

        Args:
            messages: List of wire log messages

        Returns:
            Dictionary mapping participant ID to list of messages
        """
        grouped: Dict[str, List[WireLogMessage]] = {}

        for msg in messages:
            if msg.participant_id:
                if msg.participant_id not in grouped:
                    grouped[msg.participant_id] = []
                grouped[msg.participant_id].append(msg)

        return grouped

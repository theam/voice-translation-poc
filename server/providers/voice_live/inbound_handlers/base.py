from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from ....models.messages import TranslationResponse


class VoiceLiveMessageHandler(Protocol):
    """Protocol for VoiceLive inbound message handlers."""

    async def handle(self, message: Dict[str, Any]) -> Optional[TranslationResponse]:
        ...


def extract_context(message: Dict[str, Any]) -> tuple[str, str, Optional[str]]:
    """Extract common context fields from a VoiceLive message."""
    response_meta = message.get("response", {}) if isinstance(message.get("response"), dict) else {}
    output_item = message.get("output", {}) if isinstance(message.get("output"), dict) else {}
    commit_id = (
        message.get("commit_id")
        or response_meta.get("commit_id")
        or output_item.get("commit_id")
        or response_meta.get("id")
        or message.get("id")
        or "unknown"
    )
    session_id = message.get("session_id") or response_meta.get("session_id") or "unknown"
    participant_id = message.get("participant_id") or response_meta.get("participant_id")
    return str(commit_id), str(session_id), participant_id

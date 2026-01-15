from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol


class OpenAIMessageHandler(Protocol):
    """Protocol for OpenAI inbound message handlers."""

    def can_handle(self, message: Dict[str, Any]) -> bool:
        """Check if this handler can process the given message."""
        ...

    async def handle(self, message: Dict[str, Any]) -> None:
        ...


@dataclass
class OpenAIContext:
    commit_id: str
    session_id: str
    participant_id: Optional[str]
    stream_id: Optional[str]
    provider_response_id: Optional[str]
    provider_item_id: Optional[str]


def extract_context(message: Dict[str, Any]) -> OpenAIContext:
    """Extract common context fields from an OpenAI message."""
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

    stream_id = (
        message.get("stream_id")
        or response_meta.get("id")
        or response_meta.get("response_id")
        or output_item.get("id")
        or message.get("id")
    )
    provider_response_id = response_meta.get("id") or response_meta.get("response_id")
    provider_item_id = output_item.get("id") or output_item.get("item_id") or message.get("item_id")

    return OpenAIContext(
        commit_id=str(commit_id),
        session_id=str(session_id),
        participant_id=participant_id,
        stream_id=str(stream_id) if stream_id is not None else None,
        provider_response_id=str(provider_response_id) if provider_response_id is not None else None,
        provider_item_id=str(provider_item_id) if provider_item_id is not None else None,
    )

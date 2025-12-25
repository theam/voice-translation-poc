"""Message models for streaming translation pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ProviderInputEvent:
    """
    Audio request to send to translation provider.
    Published to provider_outbound_bus when audio is committed.
    """

    commit_id: str
    session_id: str
    participant_id: Optional[str]
    b64_audio_string: str  # base64-encoded PCM audio (string)
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "commit_id": self.commit_id,
            "session_id": self.session_id,
            "participant_id": self.participant_id,
            "b64_audio_string": self.b64_audio_string,
            "metadata": self.metadata,
        }


@dataclass
class ProviderOutputEvent:
    """
    Normalized provider output event consumed by ACS outbound handler.
    """

    commit_id: str
    session_id: str
    participant_id: Optional[str]
    event_type: str
    payload: Dict[str, Any]
    provider: str
    stream_id: Optional[str] = None
    provider_response_id: Optional[str] = None
    provider_item_id: Optional[str] = None
    timestamp_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "commit_id": self.commit_id,
            "session_id": self.session_id,
            "participant_id": self.participant_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "provider": self.provider,
            "stream_id": self.stream_id,
            "provider_response_id": self.provider_response_id,
            "provider_item_id": self.provider_item_id,
            "timestamp_ms": self.timestamp_ms,
        }

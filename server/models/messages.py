"""Message models for streaming translation pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class AudioRequest:
    """
    Audio request to send to translation provider.
    Published to provider_outbound_bus when audio is committed.
    """

    commit_id: str
    session_id: str
    participant_id: Optional[str]
    audio_data: bytes  # base64-encoded PCM audio
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "commit_id": self.commit_id,
            "session_id": self.session_id,
            "participant_id": self.participant_id,
            "audio_data": self.audio_data.decode('utf-8'),
            "metadata": self.metadata,
        }


@dataclass
class TranslationResponse:
    """
    Translation response received from translation provider.
    Published to provider_inbound_bus when translation arrives.
    """

    commit_id: str
    session_id: str
    participant_id: Optional[str]
    text: str
    partial: bool  # True for partial/intermediate results, False for final

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "commit_id": self.commit_id,
            "session_id": self.session_id,
            "participant_id": self.participant_id,
            "text": self.text,
            "partial": self.partial,
        }

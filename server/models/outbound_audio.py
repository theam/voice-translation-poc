from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class OutboundAudioBytesEvent:
    session_id: str
    # Optional identifiers if available from ProviderOutputEvent
    participant_id: Optional[str] = None
    speaker_id: Optional[str] = None
    # A stable key used by playout store/engine to isolate streams
    stream_key: str = "default"
    # Raw audio bytes already in the ACS target format expected by AcsAudioPublisher
    audio_bytes: bytes = b""
    # Optional metadata
    sample_rate_hz: Optional[int] = None
    channels: Optional[int] = None


@dataclass(slots=True)
class OutboundAudioDoneEvent:
    session_id: str
    # Optional identifiers if available from ProviderOutputEvent
    participant_id: Optional[str] = None
    speaker_id: Optional[str] = None
    commit_id: Optional[str] = None
    stream_id: Optional[str] = None
    provider: Optional[str] = None
    # A stable key used by playout store/engine to isolate streams
    stream_key: str = "default"
    # Completion reason and error details
    reason: str = "completed"
    error: Optional[str] = None

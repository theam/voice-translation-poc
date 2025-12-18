"""Turn model."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


@dataclass
class LatencyMetrics:
    """Latency and timing metrics for a turn.

    All latency values are in milliseconds. Timestamps are relative to
    scenario start (scenario timeline, not wall-clock).
    """

    # Core latency metrics (what users care about)
    latency_ms: Optional[int] = None  # VAD-aware audio latency (last_outbound → first_audio)
    text_latency_ms: Optional[int] = None  # Text latency (last_outbound → first_text)
    first_chunk_latency_ms: Optional[int] = None  # Total latency (first_outbound → first_response)

    # Raw timestamps (for debugging and gap calculations)
    first_outbound_ms: Optional[int] = None  # When first audio sent
    last_outbound_ms: Optional[int] = None  # When last audio sent
    first_response_ms: Optional[int] = None  # First response (any type)
    first_audio_response_ms: Optional[int] = None  # First audio response
    last_audio_response_ms: Optional[int] = None  # Last audio response
    first_text_response_ms: Optional[int] = None  # First text response

    # Derived metrics
    audio_duration_ms: Optional[int] = None  # Speaking duration (last - first outbound)

    # Event counts (useful for debugging)
    audio_event_count: Optional[int] = None  # Number of translated_audio events
    text_event_count: Optional[int] = None  # Number of translated_delta events

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values for storage efficiency."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Turn:
    """Complete turn data for storage and reporting.

    Represents a single conversational turn with timing, content, and expectations.
    Stores both actual results and expected values for comparison in reports.
    """

    turn_id: str
    start_ms: int
    end_ms: Optional[int] = None
    source_text: Optional[str] = None
    translated_text: Optional[str] = None
    expected_text: Optional[str] = None
    source_language: Optional[str] = None
    expected_language: Optional[str] = None
    metric_expectations: Dict[str, float] = field(default_factory=dict)
    latency: Optional[LatencyMetrics] = None  # Latency and timing metrics

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB storage."""
        data = asdict(self)
        # Convert latency object to dict, excluding None if not present
        if self.latency:
            data['latency'] = self.latency.to_dict()
        return data


__all__ = ["Turn", "LatencyMetrics"]

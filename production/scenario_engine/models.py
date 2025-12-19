"""Scenario data structures."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Participant:
    name: str
    source_language: str
    target_language: str
    audio_files: Dict[str, Path] = field(default_factory=dict)


@dataclass
class ScenarioTurn:
    id: str
    type: str  # "play_audio", "silence", "hangup", "play_text"
    participant: str
    audio_file: Optional[str] = None
    text: Optional[str] = None  # For play_text turns
    start_at_ms: int = 0
    # Translation expectations
    source_language: Optional[str] = None
    expected_language: Optional[str] = None
    source_text: Optional[str] = None
    expected_text: Optional[str] = None
    # Metric-specific expectations (for calibration scenarios)
    metric_expectations: Dict[str, float] = field(default_factory=dict)


@dataclass
class Scenario:
    id: str
    description: str
    participants: Dict[str, Participant]
    turns: List[ScenarioTurn]
    tags: List[str] = field(default_factory=list)
    score_method: str = "average"  # Score calculator method ("average" or "garbled_turn")
    websocket_client: str = "websocket"  # WebSocket client type: "websocket" (real) or "loopback" (mock)
    metrics: List[str] = field(default_factory=list)  # Specific metrics to run; empty = run all metrics
    expected_score: Optional[float] = None  # Expected overall test score for calibration validation (0-100)
    tolerance: Optional[float] = None  # Optional per-scenario metric tolerance for calibration

    def sequence(self) -> List[str]:
        """Return the expected turn order based on declared turns."""

        return [turn.id for turn in self.turns]

    def turns_to_evaluate(self) -> List[ScenarioTurn]:
        """Return turns that should be evaluated (those with expected text)."""
        return [turn for turn in self.turns if turn.expected_text is not None]


__all__ = [
    "Participant",
    "ScenarioTurn",
    "Scenario",
]

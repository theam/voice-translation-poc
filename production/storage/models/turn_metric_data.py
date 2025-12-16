"""Per-turn metric data."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class TurnMetricData:
    """Metric data for a single turn."""

    turn_id: str
    score: float
    expected_score: Optional[float] = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


__all__ = ["TurnMetricData"]

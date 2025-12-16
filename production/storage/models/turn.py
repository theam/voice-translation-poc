"""Turn model."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


__all__ = ["Turn"]

"""Conversation-level metric data."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ConversationMetricData:
    """Conversation-level metric result for storage."""

    score: Optional[float] = None
    expected_score: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


__all__ = ["ConversationMetricData"]

"""Metric-level data container."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from production.metrics.base import MetricResult

from .conversation_metric_data import ConversationMetricData
from .turn_metric_data import TurnMetricData


@dataclass
class MetricData:
    """Individual metric result data for storage."""

    metric_name: str
    score: Optional[float] = None
    turns: List[TurnMetricData] = field(default_factory=list)
    conversation: Optional[ConversationMetricData] = None

    @classmethod
    def from_metric_result(
        cls,
        result: MetricResult,
        expected_scores_by_turn: Optional[Dict[str, float]] = None,
    ) -> "MetricData":
        """Map MetricResult to MetricData for MongoDB persistence.

        Handles two metric types:
        1. Per-turn metrics: Use details.turns array (backward compatible with details.results)
        2. Conversation-level metrics: Use details.conversation object
        """
        turns: List[TurnMetricData] = []
        conversation: Optional[ConversationMetricData] = None

        if not result.details:
            return cls(
                metric_name=result.metric_name,
                score=result.score,
                turns=turns,
                conversation=conversation,
            )

        # Handle per-turn metrics (with backward compatibility)
        turns_data = result.details.get("turns") or result.details.get("results")
        if turns_data:
            for turn_data in turns_data:
                # Skip turns without turn_id
                if "turn_id" not in turn_data:
                    continue

                # Get expected score for this turn
                expected_score = None
                if expected_scores_by_turn:
                    expected_score = expected_scores_by_turn.get(turn_data["turn_id"])

                # Create TurnMetricData
                # Extract score, turn_id, status - everything else goes to details
                turns.append(TurnMetricData(
                    turn_id=turn_data["turn_id"],
                    score=turn_data.get("score"),
                    expected_score=expected_score,
                    details={
                        k: v for k, v in turn_data.items()
                        if k not in ["turn_id", "score", "status"]
                    },
                ))

        # Handle conversation-level metrics
        if "conversation" in result.details:
            conv = result.details["conversation"]
            if isinstance(conv, dict):
                # Extract score, expected_score, status - everything else goes to details
                conversation = ConversationMetricData(
                    score=conv.get("score"),
                    expected_score=conv.get("expected_score"),
                    details={
                        k: v for k, v in conv.items()
                        if k not in ["score", "expected_score", "status"]
                    },
                )

        return cls(
            metric_name=result.metric_name,
            score=result.score,
            turns=turns,
            conversation=conversation,
        )

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "metric_name": self.metric_name,
            "score": self.score,
            "turns": [turn.to_dict() for turn in self.turns],
            "conversation": self.conversation.to_dict() if self.conversation else None,
        }
        return data


__all__ = ["MetricData"]

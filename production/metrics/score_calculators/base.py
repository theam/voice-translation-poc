"""Base protocol for test score calculators.

Score calculators aggregate individual metric results to produce
an overall test score, status, and optional details.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from production.metrics.base import MetricResult


@dataclass
class TestScore:
    """Result of test score calculation.

    Attributes:
        score: Overall test score (0-100)
        score_method: Name of calculator used (e.g., "average", "garbled_turn")
        details: Calculator-specific details (optional)
    """

    score: float  # 0-100
    score_method: str
    details: Optional[Dict[str, Any]] = None


class ScoreCalculator(Protocol):
    """Protocol for test score calculators.

    Implementations aggregate metric results to produce:
    - Overall test score (0-100)
    - Test status (calculator-specific)
    - Optional detailed breakdown

    Example implementations:
    - AverageScoreCalculator: Average of metric scores
    - GarbledTurnScoreCalculator: Based on conversational quality
    """

    name: str  # Unique calculator identifier

    def calculate(self, metric_results: List[MetricResult]) -> TestScore:
        """Calculate overall test score from metric results.

        Args:
            metric_results: List of metric results from test execution

        Returns:
            TestScore with score, method, status, and details
        """
        ...


__all__ = ["ScoreCalculator", "TestScore"]

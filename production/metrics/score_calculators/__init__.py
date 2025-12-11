"""Score calculators for test score aggregation."""
from __future__ import annotations

import logging
from typing import Optional

from .average import AverageScoreCalculator
from .base import ScoreCalculator, TestScore
from .garbled_turn import GarbledTurnScoreCalculator


logger = logging.getLogger(__name__)


def get_score_calculator(
    method: str = "average",
    **kwargs
) -> ScoreCalculator:
    """Get score calculator by method name.

    Args:
        method: Calculator method name ("average" or "garbled_turn")
        **kwargs: Additional calculator-specific parameters

    Returns:
        ScoreCalculator instance

    Raises:
        ValueError: If method is unknown

    Example:
        >>> calc = get_score_calculator("average")
        >>> calc = get_score_calculator("garbled_turn", garbled_threshold=0.15)
    """
    method = method.lower()

    if method == "average":
        return AverageScoreCalculator()

    elif method == "garbled_turn":
        # Extract garbled_threshold if provided
        garbled_threshold = kwargs.get("garbled_threshold", 0.10)
        return GarbledTurnScoreCalculator(garbled_threshold=garbled_threshold)

    else:
        available = ["average", "garbled_turn"]
        raise ValueError(
            f"Unknown score calculator method: '{method}'. "
            f"Available methods: {', '.join(available)}"
        )


__all__ = [
    "ScoreCalculator",
    "TestScore",
    "AverageScoreCalculator",
    "GarbledTurnScoreCalculator",
    "get_score_calculator",
]

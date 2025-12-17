"""Calibration data models."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List


@dataclass
class CalibrationResult:
    """Result of validating a single metric expectation.

    Used for both turn-level and conversation-level metric validation.
    Use validation_level to distinguish between the two use cases.
    """

    metric_name: str
    turn_id: Optional[str]  # None for conversation-level metrics
    expected: float  # Expected score (0-100 scale)
    actual: Optional[float]  # Actual score (0-100 scale)
    delta: Optional[float]  # actual - expected
    within_tolerance: bool
    tolerance: float  # Tolerance (0-100 scale)
    validation_level: str = "turn"  # "turn" or "conversation"

    @property
    def passed(self) -> bool:
        """Whether this calibration check passed."""
        return self.within_tolerance

    @property
    def status(self) -> str:
        """Status string for display."""
        if self.actual is None:
            return "MISSING"
        return "PASS" if self.within_tolerance else "FAIL"

    @property
    def is_conversation_level(self) -> bool:
        """Whether this is a conversation-level validation."""
        return self.validation_level == "conversation"

    @property
    def is_turn_level(self) -> bool:
        """Whether this is a turn-level validation."""
        return self.validation_level == "turn"


@dataclass
class CalibrationSummary:
    """Summary of all calibration validation results."""

    test_id: str
    turns: List[CalibrationResult] | None = None
    conversation: CalibrationResult | None = None
    expected_score: Optional[float] = None
    actual_score: Optional[float] = None
    score_delta: Optional[float] = None
    score_within_tolerance: bool = True
    score_tolerance: Optional[float] = None

    @property
    def num_checks(self) -> int:
        """Total number of calibration checks."""
        return (len(self.turns) if self.turns else 0) + (1 if self.conversation else 0)

    @property
    def num_passed(self) -> int:
        """Number of checks that passed."""
        passed_turns = sum(1 for r in (self.turns or []) if r.passed)
        passed_conv = 1 if self.conversation and self.conversation.passed else 0
        return passed_turns + passed_conv

    @property
    def num_failed(self) -> int:
        """Number of checks that failed."""
        failed_turns = sum(1 for r in (self.turns or []) if not r.passed)
        failed_conv = 1 if self.conversation and not self.conversation.passed else 0
        return failed_turns + failed_conv

    @property
    def overall_passed(self) -> bool:
        """Whether all calibration checks passed."""
        score_check = self.score_within_tolerance if self.expected_score is not None else True
        return self.num_failed == 0 and score_check


__all__ = ["CalibrationResult", "CalibrationSummary"]

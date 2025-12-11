"""Data models for metrics calibration system.

Calibration validates metric behavior against known expected outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ConversationTurn:
    """Single turn in conversation history (for context metric calibration)."""

    participant_id: str
    text: str
    timestamp_ms: int
    source_language: Optional[str] = None
    target_language: Optional[str] = None


@dataclass
class CalibrationCase:
    """Single calibration test case.

    Represents one test case with known expected outcome for metric validation.

    Attributes:
        id: Unique identifier for this case
        description: Human-readable description of what this tests
        text: The text to evaluate (translated/recognized text)
        metadata: Event metadata (languages, participant, timestamp)
        expected_scores: Expected metric scores (e.g., {"intelligibility_1_5": 5})
        expected_reasoning: Expected reasoning for the score (optional)
        conversation_history: Prior turns (for context metric)
        expected_text: Ground truth text (for WER, completeness, etc.)
    """

    id: str
    description: str
    text: str
    metadata: Dict[str, Any]
    expected_scores: Dict[str, float]
    expected_reasoning: Optional[str] = None
    conversation_history: List[ConversationTurn] = field(default_factory=list)
    expected_text: Optional[str] = None  # Ground truth for comparison


@dataclass
class CalibrationConfig:
    """Calibration configuration loaded from YAML file.

    Attributes:
        id: Unique identifier for this calibration set
        version: Schema version (e.g., "1.0")
        description: Description of calibration purpose
        metric: Target metric name ("intelligibility", "context", "all")
        created_at: Creation date (ISO format)
        tags: Tags for categorization (e.g., ["baseline", "medical"])
        llm_config: Optional LLM configuration override
        calibration_cases: List of test cases
        file_path: Path to source YAML file (set during loading)
    """

    id: str
    version: str
    description: str
    metric: str
    created_at: str
    tags: List[str] = field(default_factory=list)
    llm_config: Optional[Dict[str, Any]] = None
    calibration_cases: List[CalibrationCase] = field(default_factory=list)
    file_path: Optional[Path] = None


@dataclass
class CalibrationResult:
    """Result of calibrating a single case.

    Attributes:
        case_id: ID of calibration case
        case_description: Description of what was tested
        metric_name: Name of metric that was run
        actual_score: Score returned by metric (normalized 0-1)
        expected_score: Expected score from calibration case
        score_diff: Absolute difference |actual - expected|
        score_diff_percentage: Difference as percentage of scale
        passed: Whether result within tolerance
        actual_reasoning: Reasoning provided by metric/LLM
        expected_reasoning: Expected reasoning from calibration case
        tolerance: Tolerance threshold used
        text_evaluated: The text that was evaluated
    """

    case_id: str
    case_description: str
    metric_name: str
    actual_score: float
    expected_score: float
    score_diff: float
    score_diff_percentage: float
    passed: bool
    actual_reasoning: Optional[str] = None
    expected_reasoning: Optional[str] = None
    tolerance: float = 0.5
    text_evaluated: Optional[str] = None


@dataclass
class CalibrationSummary:
    """Summary of calibration run results.

    Attributes:
        config_id: ID of calibration config
        config_description: Description of calibration set
        metric_name: Name of metric that was calibrated
        total_cases: Total number of test cases
        passed_cases: Number of cases within tolerance
        failed_cases: Number of cases exceeding tolerance
        avg_score_diff: Average score difference across all cases
        max_score_diff: Maximum score difference (worst case)
        accuracy: Percentage of passed cases (passed / total)
        results: Detailed results for each case
        timestamp: When calibration was run
        llm_model: LLM model used (if applicable)
        tolerance: Tolerance threshold used
    """

    config_id: str
    config_description: str
    metric_name: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    avg_score_diff: float
    max_score_diff: float
    accuracy: float
    results: List[CalibrationResult]
    timestamp: datetime
    llm_model: Optional[str] = None
    tolerance: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/serialization.

        Returns:
            Dictionary representation
        """
        return {
            "config_id": self.config_id,
            "config_description": self.config_description,
            "metric_name": self.metric_name,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "avg_score_diff": self.avg_score_diff,
            "max_score_diff": self.max_score_diff,
            "accuracy": self.accuracy,
            "timestamp": self.timestamp.isoformat(),
            "llm_model": self.llm_model,
            "tolerance": self.tolerance,
            "results": [
                {
                    "case_id": r.case_id,
                    "case_description": r.case_description,
                    "metric_name": r.metric_name,
                    "actual_score": r.actual_score,
                    "expected_score": r.expected_score,
                    "score_diff": r.score_diff,
                    "score_diff_percentage": r.score_diff_percentage,
                    "passed": r.passed,
                    "actual_reasoning": r.actual_reasoning,
                    "expected_reasoning": r.expected_reasoning,
                    "text_evaluated": r.text_evaluated,
                }
                for r in self.results
            ],
        }


__all__ = [
    "ConversationTurn",
    "CalibrationCase",
    "CalibrationConfig",
    "CalibrationResult",
    "CalibrationSummary",
]

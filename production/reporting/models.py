"""Data models for PDF report generation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from production.storage.models import MetricData, Turn

if TYPE_CHECKING:
    from production.calibration.validator import CalibrationSummary


@dataclass
class EvaluationRunData:
    """Data for the evaluation run summary section."""

    evaluation_run_id: str
    started_at: datetime
    finished_at: datetime
    git_commit: str
    git_branch: str
    environment: str
    target_system: str
    score: float  # 0-100
    num_tests: int
    aggregated_metrics: dict[str, float]  # {metric_name: average_value}
    system_info_hash: str
    experiment_tags: list[str]
    calibration_status: Optional[str] = None  # "passed" or "failed" for calibration runs

    def is_calibration(self) -> bool:
        """Return True if this evaluation run is a calibration run."""
        return self.target_system == "calibration"


@dataclass
class TestReportData:
    """Data for a single test section."""

    test_id: str
    test_name: str
    test_run_id: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    score: float  # 0-100
    score_method: str
    metrics: dict[str, MetricData]  # {metric_name: MetricData}
    turns: list[Turn]  # Conversation turns
    scenario_metrics: list[str] = field(default_factory=list)  # Metrics defined in scenario
    expected_score: Optional[float] = None  # Expected score for calibration
    tolerance: Optional[float] = None  # Metric tolerance used for calibration
    calibration_summary: Optional["CalibrationSummary"] = None  # Calibration validation results


__all__ = ["EvaluationRunData", "TestReportData"]

"""Data models for metrics storage."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from production.metrics.base import MetricResult


@dataclass
class MetricData:
    """Individual metric result data for storage.

    Represents a single metric's outcome (e.g., WER, completeness)
    with pass/fail status, numeric value, and detailed analysis.

    Attributes:
        metric_name: Name of the metric (e.g., "wer", "completeness")
        passed: Whether metric passed its threshold
        value: Numeric score (0.0-1.0 for percentages, or other ranges)
        reason: Explanation for failure (if applicable)
        details: Additional metric-specific data (e.g., per-expectation results)
    """

    metric_name: str
    passed: bool
    value: Optional[float] = None
    reason: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    @classmethod
    def from_metric_result(cls, result: MetricResult) -> MetricData:
        """Create MetricData from MetricResult.

        Args:
            result: MetricResult from metrics execution

        Returns:
            MetricData instance
        """
        return cls(
            metric_name=result.metric_name,
            passed=result.passed,
            value=result.value,
            reason=result.reason,
            details=result.details
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to MongoDB-compatible dictionary.

        Returns:
            Dictionary representation for MongoDB storage
        """
        return asdict(self)


@dataclass
class TestRun:
    """Result for a single test execution.

    Stores detailed metrics for one test within a specific evaluation run,
    including timing, all metric results, and test metadata.

    Attributes:
        evaluation_run_id: ObjectId reference to parent evaluation_runs document
        test_run_id: Human-readable identifier for this specific test execution
        test_id: Stable test identifier from scenario YAML (scenario.id)
        test_name: Human-readable test name (scenario description)
        started_at: Test start timestamp
        finished_at: Test completion timestamp
        duration_ms: Test duration in milliseconds
        metrics: Dictionary of metric results (key = metric name)
        score: Overall test score (0-100) calculated by score calculator
        score_method: Calculator method used (e.g., "average", "garbled_turn")
        score_status: Status determined by calculator (e.g., "success", "garbled", "failed")
        error_summary: Error message if infrastructure failure occurred
        tags: Test tags from scenario definition
        participants: Participant names from scenario
        _id: MongoDB ObjectId (set after insertion)
    """

    # Identity & linkage
    evaluation_run_id: ObjectId
    test_run_id: str
    test_id: str
    test_name: str

    # Timing
    started_at: datetime
    finished_at: datetime
    duration_ms: int

    # Metrics
    metrics: Dict[str, MetricData]

    # Score (calculated by score calculator)
    score: float  # Overall score 0-100
    score_method: str  # Calculator method ("average", "garbled_turn", etc.)
    score_status: str  # Calculator-specific status ("success", "garbled", "failed", etc.)
    error_summary: Optional[str] = None

    # Metadata
    tags: List[str] = field(default_factory=list)
    participants: List[str] = field(default_factory=list)

    # MongoDB ID (set after insert)
    _id: Optional[ObjectId] = None

    def to_document(self) -> Dict[str, Any]:
        """Convert to MongoDB document.

        Returns:
            Dictionary suitable for MongoDB insertion
        """
        doc = {
            "evaluation_run_id": self.evaluation_run_id,
            "test_run_id": self.test_run_id,
            "test_id": self.test_id,
            "test_name": self.test_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "metrics": {k: v.to_dict() for k, v in self.metrics.items()},
            "score": self.score,
            "score_method": self.score_method,
            "score_status": self.score_status,
            "error_summary": self.error_summary,
            "tags": self.tags,
            "participants": self.participants
        }
        if self._id:
            doc["_id"] = self._id
        return doc


@dataclass
class EvaluationRun:
    """Metadata and aggregated metrics for a full evaluation run.

    Represents one execution of the test framework, tracking context
    (git info, system information), aggregated metrics, and overall status.

    Attributes:
        evaluation_run_id: Human-readable identifier (e.g., "2025-12-05T10-30Z-abcdef")
        started_at: Evaluation start timestamp
        finished_at: Evaluation completion timestamp (None while running)
        git_commit: Git commit hash at runtime
        git_branch: Git branch name at runtime
        framework_version: Version of the test framework
        environment: Environment name (dev/stage/prod/lab)
        target_system: Target system being tested (voice_live/live_interpreter/custom_llm)
        experiment_tags: Free-form labels for experiments
        system_information: Comprehensive system info from test runner and translation system
        system_info_hash: SHA-256 hash of system information for quick comparison
        metrics: Aggregated evaluation-level metrics (e.g., average_wer)
        num_tests: Total number of tests in evaluation
        num_passed: Number of tests that passed
        num_failed: Number of tests that failed
        status: Evaluation status ("running" | "completed" | "failed")
        score: Overall evaluation score (0-100) averaged from all test scores
        _id: MongoDB ObjectId (set after insertion)
    """

    # Identity & timestamps
    evaluation_run_id: str
    environment: str
    target_system: str
    started_at: datetime
    finished_at: Optional[datetime] = None

    # Context / provenance
    git_commit: Optional[str] = None
    git_branch: Optional[str] = None
    framework_version: str = "0.1.0"
    experiment_tags: List[str] = field(default_factory=list)

    # System information snapshot
    system_information: Dict[str, Any] = field(default_factory=dict)
    system_info_hash: str = ""

    # Aggregated metrics (computed after all tests complete)
    metrics: Dict[str, float] = field(default_factory=dict)
    num_tests: int = 0
    num_passed: int = 0
    num_failed: int = 0

    # Status
    status: str = "running"  # "running" | "completed" | "failed"
    score: Optional[float] = None  # Overall evaluation score 0-100 (average of test scores)

    # MongoDB ID
    _id: Optional[ObjectId] = None

    def to_document(self) -> Dict[str, Any]:
        """Convert to MongoDB document.

        Returns:
            Dictionary suitable for MongoDB insertion
        """
        doc = {
            "evaluation_run_id": self.evaluation_run_id,
            "environment": self.environment,
            "target_system": self.target_system,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "git_commit": self.git_commit,
            "git_branch": self.git_branch,
            "framework_version": self.framework_version,
            "experiment_tags": self.experiment_tags,
            "system_information": self.system_information,
            "system_info_hash": self.system_info_hash,
            "metrics": self.metrics,
            "num_tests": self.num_tests,
            "num_passed": self.num_passed,
            "num_failed": self.num_failed,
            "status": self.status,
            "score": self.score
        }
        if self._id:
            doc["_id"] = self._id
        return doc


@dataclass
class CalibrationCaseResult:
    """Result for a single calibration test case.

    Attributes:
        case_id: Calibration case identifier
        case_description: Human-readable description
        text: Text that was evaluated
        expected_score: Expected score from calibration config
        actual_score: Score produced by metric
        difference: Absolute difference between expected and actual
        passed: Whether result is within tolerance
        reasoning: LLM reasoning (if available)
        metadata: Additional case metadata
    """

    case_id: str
    case_description: str
    text: str
    expected_score: float
    actual_score: float
    difference: float
    passed: bool
    reasoning: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to MongoDB-compatible dictionary.

        Returns:
            Dictionary representation for MongoDB storage
        """
        return asdict(self)


@dataclass
class CalibrationRun:
    """Result for a complete calibration run.

    Tracks calibration execution for a specific metric configuration,
    including all test case results, accuracy, and system context.

    Attributes:
        calibration_run_id: Human-readable identifier (e.g., "2025-12-10T15-30Z-intelligibility")
        config_id: Calibration config identifier (from YAML)
        metric: Metric name being calibrated
        version: Calibration config version
        description: Human-readable description
        started_at: Calibration start timestamp
        finished_at: Calibration completion timestamp
        duration_ms: Calibration duration in milliseconds
        tolerance: Tolerance threshold used for pass/fail
        accuracy: Percentage of cases that passed (0.0-1.0)
        total_cases: Total number of test cases
        passed_cases: Number of cases that passed
        failed_cases: Number of cases that failed
        results: List of individual case results
        git_commit: Git commit hash at runtime
        git_branch: Git branch name at runtime
        framework_version: Version of the test framework
        model: LLM model used (if applicable)
        _id: MongoDB ObjectId (set after insertion)
    """

    # Identity & timestamps
    calibration_run_id: str
    config_id: str
    metric: str
    version: str
    description: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int

    # Results
    tolerance: float
    accuracy: float  # 0.0-1.0
    total_cases: int
    passed_cases: int
    failed_cases: int
    results: List[CalibrationCaseResult]

    # Context / provenance
    git_commit: Optional[str] = None
    git_branch: Optional[str] = None
    framework_version: str = "0.1.0"
    model: Optional[str] = None

    # MongoDB ID
    _id: Optional[ObjectId] = None

    def to_document(self) -> Dict[str, Any]:
        """Convert to MongoDB document.

        Returns:
            Dictionary suitable for MongoDB insertion
        """
        doc = {
            "calibration_run_id": self.calibration_run_id,
            "config_id": self.config_id,
            "metric": self.metric,
            "version": self.version,
            "description": self.description,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "tolerance": self.tolerance,
            "accuracy": self.accuracy,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "results": [r.to_dict() for r in self.results],
            "git_commit": self.git_commit,
            "git_branch": self.git_branch,
            "framework_version": self.framework_version,
            "model": self.model
        }
        if self._id:
            doc["_id"] = self._id
        return doc


__all__ = ["MetricData", "TestRun", "EvaluationRun", "CalibrationCaseResult", "CalibrationRun"]

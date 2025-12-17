"""EvaluationRun model."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId


@dataclass
class EvaluationRun:
    """Metadata and aggregated metrics for a full evaluation run."""

    environment: str
    target_system: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    git_commit: Optional[str] = None
    git_branch: Optional[str] = None
    framework_version: str = "0.1.0"
    experiment_tags: List[str] = field(default_factory=list)
    system_information: Dict[str, Any] = field(default_factory=dict)
    system_info_hash: str = ""
    metrics: Dict[str, float] = field(default_factory=dict)
    num_tests: int = 0
    status: str = "running"
    score: Optional[float] = None
    calibration_status: Optional[str] = None  # "passed" or "failed" for calibration runs
    _id: Optional[ObjectId] = None

    def is_calibration(self) -> bool:
        return self.target_system == "calibration"

    def to_document(self) -> Dict[str, Any]:
        doc = {
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
            "status": self.status,
            "score": self.score,
            "calibration_status": self.calibration_status,
        }
        if self._id:
            doc["_id"] = self._id
        return doc

    @classmethod
    def from_document(cls, doc: Dict[str, Any]) -> "EvaluationRun":
        return cls(
            environment=doc["environment"],
            target_system=doc["target_system"],
            started_at=doc["started_at"],
            finished_at=doc.get("finished_at"),
            git_commit=doc.get("git_commit"),
            git_branch=doc.get("git_branch"),
            framework_version=doc.get("framework_version", "0.1.0"),
            experiment_tags=doc.get("experiment_tags", []),
            system_information=doc.get("system_information", {}),
            system_info_hash=doc.get("system_info_hash", ""),
            metrics=doc.get("metrics", {}),
            num_tests=doc.get("num_tests", 0),
            status=doc.get("status", "running"),
            score=doc.get("score"),
            calibration_status=doc.get("calibration_status"),
            _id=doc.get("_id"),
        )


__all__ = ["EvaluationRun"]

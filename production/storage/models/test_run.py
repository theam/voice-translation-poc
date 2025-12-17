"""TestRun model."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from .metric_data import MetricData
from .conversation_metric_data import ConversationMetricData
from .turn import Turn
from .turn_metric_data import TurnMetricData


@dataclass
class TestRun:
    """Result for a single test execution."""

    evaluation_run_id: ObjectId
    test_id: str
    test_name: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    metrics: Dict[str, MetricData]
    turns: List[Turn]
    score: float
    score_method: str
    error_summary: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    participants: List[str] = field(default_factory=list)
    scenario_metrics: List[str] = field(default_factory=list)
    expected_score: Optional[float] = None
    tolerance: Optional[float] = None
    calibration_summary: Optional[Dict[str, Any]] = None
    _id: Optional[ObjectId] = None

    def to_document(self) -> Dict[str, Any]:
        doc = {
            "evaluation_run_id": self.evaluation_run_id,
            "test_id": self.test_id,
            "test_name": self.test_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "metrics": {k: v.to_dict() for k, v in self.metrics.items()},
            "turns": [turn.to_dict() for turn in self.turns],
            "score": self.score,
            "score_method": self.score_method,
            "error_summary": self.error_summary,
            "tags": self.tags,
            "participants": self.participants,
            "scenario_metrics": self.scenario_metrics,
            "expected_score": self.expected_score,
            "calibration_summary": self.calibration_summary,
            "tolerance": self.tolerance,
        }
        if self._id:
            doc["_id"] = self._id
        return doc

    @classmethod
    def from_document(cls, doc: Dict[str, Any]) -> "TestRun":
        metrics = {}
        for metric_name, metric_data in doc["metrics"].items():
            turn_metrics = []
            for turn_data in metric_data.get("turns", []):
                turn_metrics.append(TurnMetricData(
                    turn_id=turn_data["turn_id"],
                    score=turn_data.get("score"),
                    expected_score=turn_data.get("expected_score"),
                    details=turn_data.get("details"),
                ))

            conversation_data = metric_data.get("conversation")
            conversation = None
            if conversation_data is not None:
                conversation = ConversationMetricData(
                    score=conversation_data.get("score"),
                    expected_score=conversation_data.get("expected_score"),
                    details=conversation_data.get("details"),
                )

            metrics[metric_name] = MetricData(
                metric_name=metric_data["metric_name"],
                score=metric_data.get("score"),
                turns=turn_metrics,
                conversation=conversation,
            )

        turns = []
        for turn_data in doc["turns"]:
            turns.append(Turn(
                turn_id=turn_data["turn_id"],
                start_ms=turn_data["start_ms"],
                end_ms=turn_data.get("end_ms"),
                source_text=turn_data.get("source_text"),
                translated_text=turn_data.get("translated_text"),
                expected_text=turn_data.get("expected_text"),
                source_language=turn_data.get("source_language"),
                expected_language=turn_data.get("expected_language"),
                metric_expectations=turn_data.get("metric_expectations", {}),
            ))

        return cls(
            evaluation_run_id=doc["evaluation_run_id"],
            test_id=doc["test_id"],
            test_name=doc["test_name"],
            started_at=doc["started_at"],
            finished_at=doc["finished_at"],
            duration_ms=doc["duration_ms"],
            metrics=metrics,
            turns=turns,
            score=doc["score"],
            score_method=doc["score_method"],
            error_summary=doc.get("error_summary"),
            tags=doc.get("tags", []),
            participants=doc.get("participants", []),
            scenario_metrics=doc.get("scenario_metrics", []),
            expected_score=doc.get("expected_score"),
            tolerance=doc.get("tolerance"),
            calibration_summary=doc.get("calibration_summary"),
            _id=doc.get("_id"),
        )


__all__ = ["TestRun"]

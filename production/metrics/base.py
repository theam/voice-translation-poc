"""Metric interfaces and result containers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol


@dataclass
class MetricResult:
    """Outcome for a single metric execution.

    Attributes:
        metric_name: Name of the metric
        score: Numeric score (0.00-100.00)
        reason: Optional human-readable reason for context
        details: Additional metric-specific data
    """

    metric_name: str
    score: float | None = None
    reason: str | None = None
    details: Dict[str, Any] | None = None


class Metric(Protocol):
    """Common interface for all metrics."""

    name: str

    def run(self) -> MetricResult:  # pragma: no cover - Protocol definition
        ...


__all__ = ["Metric", "MetricResult"]

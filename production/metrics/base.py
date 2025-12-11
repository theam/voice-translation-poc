"""Metric interfaces and result containers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol


@dataclass
class MetricResult:
    """Outcome for a single metric execution."""

    metric_name: str
    passed: bool
    value: float | None = None
    reason: str | None = None
    details: Dict[str, Any] | None = None


class Metric(Protocol):
    """Common interface for all metrics."""

    name: str

    def run(self) -> MetricResult:  # pragma: no cover - Protocol definition
        ...


__all__ = ["Metric", "MetricResult"]

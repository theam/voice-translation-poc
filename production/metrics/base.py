"""Metric interfaces and result containers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol


@dataclass
class MetricResult:
    """Outcome for a single metric execution."""

    metric_name: str
    passed: bool
    value: Optional[float] = None
    reason: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class Metric(Protocol):
    """Common interface for all metrics."""

    name: str

    def run(self) -> MetricResult:  # pragma: no cover - Protocol definition
        ...


__all__ = ["Metric", "MetricResult"]

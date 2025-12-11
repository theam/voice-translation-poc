"""Sequence metric ensuring translations arrive in order."""
from __future__ import annotations

from typing import Dict, List

from production.capture.conversation_manager import ConversationManager
from production.scenario_engine.models import Expectations

from .base import Metric, MetricResult


class SequenceMetric(Metric):
    """Checks that translated events respect the expected order."""

    name = "translation_sequence"

    def __init__(self, expectations: Expectations, conversation_manager: ConversationManager) -> None:
        self.expectations = expectations
        self.conversation_manager = conversation_manager

    def run(self) -> MetricResult:
        expected_sequence = self.expectations.sequence
        if not expected_sequence:
            return MetricResult(metric_name=self.name, passed=True, value=1.0, details={"checked": False})

        order_map: Dict[str, int] = {event_id: idx for idx, event_id in enumerate(expected_sequence)}
        seen_order: List[int] = []
        for turn in self.conversation_manager.iter_turns():
            if turn.turn_id not in order_map:
                continue
            if not turn.translated_text_events:
                continue
            seen_order.append(order_map[turn.turn_id])

        passed = seen_order == sorted(seen_order)
        reason = None if passed else "Translated events arrived out of order"
        observed = [
            turn.turn_id
            for turn in self.conversation_manager.iter_turns()
            if turn.turn_id in order_map and turn.translated_text_events
        ]
        details = {"expected": expected_sequence, "observed": observed}
        value = 1.0 if passed else 0.0
        return MetricResult(metric_name=self.name, passed=passed, value=value, reason=reason, details=details)


__all__ = ["SequenceMetric"]

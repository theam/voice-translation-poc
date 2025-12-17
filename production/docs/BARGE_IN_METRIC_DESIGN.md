# Barge-In Metric Design Specification

## Overview

This document outlines the design for a new metric to evaluate how well the translation system handles **barge-in scenarios** where a speaker interrupts their own ongoing translation to correct or add information.

## Objective

The metric should score **highly** (close to 100) when:
1. Translation from the previous turn **stops quickly** after barge-in occurs
2. No translation content from the previous turn appears after the barge-in
3. The new turn's translation starts promptly without mixing previous content

The metric should score **poorly** (close to 0) when:
- Translation from the previous turn continues for a long time after barge-in
- Translation content gets mixed between turns
- The system fails to respond to the new turn

## Available Data

### From ConversationManager

```python
class TurnSummary:
    turn_id: str
    metadata: Optional[dict]  # Contains {"type": "play_audio", "start_at_ms": 0, ...}
    turn_start_ms: Optional[int]  # When turn started in scenario timeline
    turn_end_ms: Optional[int]  # When turn ended (next turn started)
    outbound_messages: List[dict]  # Audio/messages we sent
    inbound_events: List[CollectedEvent]  # Translation events received
    first_outbound_ms: Optional[int]  # First message sent
    first_response_ms: Optional[int]  # First translation received
    completion_ms: Optional[int]  # Last translation received
```

### From CollectedEvent

```python
class CollectedEvent:
    event_type: str  # "translated_delta", "translated_audio", etc.
    timestamp_ms: int  # When event was received
    participant_id: Optional[str]
    text: Optional[str]  # Translation text delta
    audio_payload: Optional[bytes]
```

### From Scenario

```python
class ScenarioTurn:
    id: str
    barge_in: bool  # Flag indicating this turn is a barge-in
    start_at_ms: int  # When audio starts in timeline
```

## Metric Implementation Strategy

### 1. Identify Barge-In Scenarios

```python
def _find_barge_in_turns(self) -> List[Tuple[ScenarioTurn, ScenarioTurn]]:
    """Find pairs of (previous_turn, barge_in_turn).

    Returns:
        List of tuples where second element has barge_in=True
    """
    barge_in_pairs = []
    turns = self.scenario.turns

    for i, turn in enumerate(turns):
        if turn.barge_in and i > 0:
            previous_turn = turns[i - 1]
            barge_in_pairs.append((previous_turn, turn))

    return barge_in_pairs
```

### 2. Measure Barge-In Handling Quality

For each barge-in pair, calculate:

#### A. **Translation Cutoff Latency** (Primary Signal)

How quickly did translations from the previous turn stop after barge-in started?

```python
def _calculate_cutoff_latency(
    self,
    previous_turn: TurnSummary,
    barge_in_turn: TurnSummary
) -> Optional[int]:
    """Calculate time from barge-in start until last previous translation.

    Returns:
        Milliseconds from barge-in start to last previous turn translation,
        or None if no translations after barge-in
    """
    barge_in_start_ms = barge_in_turn.turn_start_ms

    # Find translation events from previous turn that arrived AFTER barge-in started
    late_translations = [
        event for event in previous_turn.inbound_events
        if event.event_type == "translated_delta"
        and event.timestamp_ms > barge_in_start_ms
    ]

    if not late_translations:
        # Perfect! No translations after barge-in
        return 0

    # Find the last translation from previous turn
    last_translation_ms = max(event.timestamp_ms for event in late_translations)

    # Calculate how long it took to stop
    cutoff_latency_ms = last_translation_ms - barge_in_start_ms

    return cutoff_latency_ms
```

**Scoring:**
- 0ms (no translations after barge-in): **100 points**
- 0-500ms: **90-100 points** (excellent)
- 500-1000ms: **70-90 points** (good)
- 1000-2000ms: **40-70 points** (acceptable)
- 2000-5000ms: **10-40 points** (poor)
- 5000ms+: **0-10 points** (very poor)

#### B. **Content Mixing Detection** (Secondary Signal)

Did translation text from the previous turn get mixed with the new turn's translation?

```python
def _detect_content_mixing(
    self,
    previous_turn_summary: TurnSummary,
    barge_in_turn_summary: TurnSummary,
    previous_turn_expected: str,
    barge_in_expected: str
) -> dict:
    """Detect if translations from both turns got mixed together.

    Returns:
        dict with:
            - mixed: bool (True if mixing detected)
            - previous_text_in_barge_in: bool
            - barge_in_text_in_previous: bool
            - score: float (0-100)
    """
    # Get actual translation texts
    previous_translation = previous_turn_summary.translation_text() or ""
    barge_in_translation = barge_in_turn_summary.translation_text() or ""

    # Check for mixing patterns:
    # 1. Does barge-in translation contain content from previous turn?
    # 2. Does previous turn translation contain barge-in keywords?

    # Simple approach: check for key phrases
    # Previous turn expected: "...moderate pain..."
    # Barge-in expected: "Sorry, I was wrong. It's quite severe..."

    # If barge-in translation contains "moderate" instead of "severe", mixing occurred
    # This can be refined with more sophisticated text analysis or LLM

    # For now, use a heuristic: check timing
    barge_in_start = barge_in_turn_summary.turn_start_ms

    # Get translation events for barge-in turn
    barge_in_translations = [
        event for event in barge_in_turn_summary.inbound_events
        if event.event_type == "translated_delta"
    ]

    # Check if any barge-in translations arrived BEFORE previous turn stopped
    early_barge_in_translations = [
        event for event in barge_in_translations
        if event.timestamp_ms < (barge_in_start + 2000)  # Within 2s of barge-in
    ]

    previous_completion = previous_turn_summary.completion_ms or 0

    mixing_detected = len(early_barge_in_translations) > 0 and previous_completion > barge_in_start

    return {
        "mixed": mixing_detected,
        "score": 0 if mixing_detected else 100,
        "reason": "Content mixing detected" if mixing_detected else "No mixing detected"
    }
```

**Scoring:**
- No mixing detected: **100 points**
- Mixing detected: **0 points**

#### C. **New Turn Response Time** (Tertiary Signal)

How quickly did the system respond to the new (barge-in) turn?

```python
def _calculate_barge_in_response_time(
    self,
    barge_in_turn_summary: TurnSummary
) -> Optional[int]:
    """Calculate time from barge-in audio start to first translation.

    Returns:
        Milliseconds from first audio to first translation response
    """
    return barge_in_turn_summary.latency_ms
```

**Scoring:**
- 0-1000ms: **100 points** (excellent responsiveness)
- 1000-2000ms: **80-100 points**
- 2000-3000ms: **60-80 points**
- 3000-5000ms: **30-60 points**
- 5000ms+: **0-30 points**

### 3. Aggregate Scoring

```python
def _calculate_barge_in_score(
    self,
    cutoff_latency_ms: int,
    mixing_score: float,
    response_time_ms: Optional[int]
) -> float:
    """Calculate overall barge-in handling score.

    Weighting:
        - Cutoff latency: 60% (most important)
        - Content mixing: 30% (critical for correctness)
        - Response time: 10% (less critical, nice to have)

    Returns:
        Score from 0-100
    """
    # Score cutoff latency
    if cutoff_latency_ms == 0:
        cutoff_score = 100.0
    elif cutoff_latency_ms <= 500:
        cutoff_score = 90.0 + (500 - cutoff_latency_ms) / 500 * 10
    elif cutoff_latency_ms <= 1000:
        cutoff_score = 70.0 + (1000 - cutoff_latency_ms) / 500 * 20
    elif cutoff_latency_ms <= 2000:
        cutoff_score = 40.0 + (2000 - cutoff_latency_ms) / 1000 * 30
    elif cutoff_latency_ms <= 5000:
        cutoff_score = 10.0 + (5000 - cutoff_latency_ms) / 3000 * 30
    else:
        cutoff_score = max(0.0, 10.0 - (cutoff_latency_ms - 5000) / 1000)

    # Score response time
    if response_time_ms is None:
        response_score = 0.0
    elif response_time_ms <= 1000:
        response_score = 100.0
    elif response_time_ms <= 2000:
        response_score = 80.0 + (2000 - response_time_ms) / 1000 * 20
    elif response_time_ms <= 3000:
        response_score = 60.0 + (3000 - response_time_ms) / 1000 * 20
    elif response_time_ms <= 5000:
        response_score = 30.0 + (5000 - response_time_ms) / 2000 * 30
    else:
        response_score = max(0.0, 30.0 - (response_time_ms - 5000) / 1000)

    # Weighted average
    total_score = (
        cutoff_score * 0.60 +
        mixing_score * 0.30 +
        response_score * 0.10
    )

    return total_score
```

## Full Metric Implementation

### File: `production/metrics/barge_in.py`

```python
"""Barge-in handling metric for evaluating translation interruption quality.

Evaluates how well the translation system handles scenarios where a speaker
interrupts their own ongoing translation to correct or add information.

Scoring criteria:
- Translation from previous turn stops quickly after barge-in (60% weight)
- No content mixing between turns (30% weight)
- Quick response to new turn (10% weight)
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from production.capture.conversation_manager import ConversationManager, TurnSummary
from production.scenario_engine.models import Scenario, ScenarioTurn

from .base import Metric, MetricResult

logger = logging.getLogger(__name__)


class BargeInMetric(Metric):
    """Evaluate barge-in handling quality.

    Measures how effectively the system handles speaker interruptions
    by analyzing translation cutoff timing, content mixing, and responsiveness.
    """

    name = "barge_in"

    def __init__(
        self,
        scenario: Scenario,
        conversation_manager: ConversationManager,
        threshold: float = 70.0
    ) -> None:
        """Initialize barge-in metric.

        Args:
            scenario: Scenario with barge_in flags on turns
            conversation_manager: Conversation manager with timing data
            threshold: Minimum acceptable score (default: 70.0)
        """
        self.scenario = scenario
        self.conversation_manager = conversation_manager
        self.threshold = threshold

    def run(self) -> MetricResult:
        """Evaluate barge-in handling for all barge-in turns.

        Returns:
            MetricResult with barge-in handling scores
        """
        barge_in_pairs = self._find_barge_in_turns()

        if not barge_in_pairs:
            return MetricResult(
                metric_name=self.name,
                score=None,
                reason="No barge-in turns found in scenario",
                details={"barge_in_evaluations": []}
            )

        evaluations = []
        total_score = 0.0

        for prev_turn, barge_in_turn in barge_in_pairs:
            # Get turn summaries
            prev_summary = self.conversation_manager.get_turn_summary(prev_turn.id)
            barge_in_summary = self.conversation_manager.get_turn_summary(barge_in_turn.id)

            if not prev_summary or not barge_in_summary:
                logger.warning(f"Missing turn summary for barge-in pair: {prev_turn.id}, {barge_in_turn.id}")
                continue

            # Calculate metrics
            cutoff_latency = self._calculate_cutoff_latency(prev_summary, barge_in_summary)
            mixing_result = self._detect_content_mixing(prev_summary, barge_in_summary)
            response_time = barge_in_summary.latency_ms

            # Calculate score
            score = self._calculate_barge_in_score(
                cutoff_latency if cutoff_latency is not None else 10000,
                mixing_result["score"],
                response_time
            )

            evaluation = {
                "previous_turn_id": prev_turn.id,
                "barge_in_turn_id": barge_in_turn.id,
                "barge_in_start_ms": barge_in_summary.turn_start_ms,
                "score": score,
                "cutoff_latency_ms": cutoff_latency,
                "mixing_detected": mixing_result["mixed"],
                "response_time_ms": response_time,
                "interpretation": self._interpret_score(score)
            }

            evaluations.append(evaluation)
            total_score += score

        # Calculate average score
        avg_score = total_score / len(evaluations) if evaluations else 0.0

        return MetricResult(
            metric_name=self.name,
            score=avg_score,
            reason=None,
            details={
                "threshold": self.threshold,
                "barge_in_count": len(evaluations),
                "turns": evaluations,
                "overall_interpretation": self._interpret_score(avg_score)
            }
        )

    def _find_barge_in_turns(self) -> List[Tuple[ScenarioTurn, ScenarioTurn]]:
        """Find pairs of (previous_turn, barge_in_turn)."""
        barge_in_pairs = []
        turns = self.scenario.turns

        for i, turn in enumerate(turns):
            if turn.barge_in and i > 0:
                previous_turn = turns[i - 1]
                barge_in_pairs.append((previous_turn, turn))

        return barge_in_pairs

    def _calculate_cutoff_latency(
        self,
        previous_turn: TurnSummary,
        barge_in_turn: TurnSummary
    ) -> Optional[int]:
        """Calculate time from barge-in start until last previous translation."""
        barge_in_start_ms = barge_in_turn.turn_start_ms

        # Find translation events from previous turn after barge-in
        late_translations = [
            event for event in previous_turn.inbound_events
            if event.event_type == "translated_delta"
            and event.timestamp_ms > barge_in_start_ms
        ]

        if not late_translations:
            return 0  # Perfect! No translations after barge-in

        last_translation_ms = max(event.timestamp_ms for event in late_translations)
        cutoff_latency_ms = last_translation_ms - barge_in_start_ms

        return cutoff_latency_ms

    def _detect_content_mixing(
        self,
        previous_turn_summary: TurnSummary,
        barge_in_turn_summary: TurnSummary
    ) -> dict:
        """Detect if translations from both turns got mixed together."""
        barge_in_start = barge_in_turn_summary.turn_start_ms

        # Get translation events for barge-in turn
        barge_in_translations = [
            event for event in barge_in_turn_summary.inbound_events
            if event.event_type == "translated_delta"
        ]

        # Check if any barge-in translations arrived while previous turn was still translating
        previous_completion = previous_turn_summary.completion_ms or 0

        early_barge_in_count = sum(
            1 for event in barge_in_translations
            if event.timestamp_ms < previous_completion
        )

        mixing_detected = early_barge_in_count > 0 and previous_completion > barge_in_start

        return {
            "mixed": mixing_detected,
            "score": 0 if mixing_detected else 100,
            "reason": "Content mixing detected" if mixing_detected else "No mixing detected"
        }

    def _calculate_barge_in_score(
        self,
        cutoff_latency_ms: int,
        mixing_score: float,
        response_time_ms: Optional[int]
    ) -> float:
        """Calculate overall barge-in handling score."""
        # Score cutoff latency (0-100)
        if cutoff_latency_ms == 0:
            cutoff_score = 100.0
        elif cutoff_latency_ms <= 500:
            cutoff_score = 90.0 + (500 - cutoff_latency_ms) / 500 * 10
        elif cutoff_latency_ms <= 1000:
            cutoff_score = 70.0 + (1000 - cutoff_latency_ms) / 500 * 20
        elif cutoff_latency_ms <= 2000:
            cutoff_score = 40.0 + (2000 - cutoff_latency_ms) / 1000 * 30
        elif cutoff_latency_ms <= 5000:
            cutoff_score = 10.0 + (5000 - cutoff_latency_ms) / 3000 * 30
        else:
            cutoff_score = max(0.0, 10.0 - (cutoff_latency_ms - 5000) / 1000)

        # Score response time (0-100)
        if response_time_ms is None:
            response_score = 0.0
        elif response_time_ms <= 1000:
            response_score = 100.0
        elif response_time_ms <= 2000:
            response_score = 80.0 + (2000 - response_time_ms) / 1000 * 20
        elif response_time_ms <= 3000:
            response_score = 60.0 + (3000 - response_time_ms) / 1000 * 20
        elif response_time_ms <= 5000:
            response_score = 30.0 + (5000 - response_time_ms) / 2000 * 30
        else:
            response_score = max(0.0, 30.0 - (response_time_ms - 5000) / 1000)

        # Weighted average: 60% cutoff, 30% mixing, 10% response
        total_score = (
            cutoff_score * 0.60 +
            mixing_score * 0.30 +
            response_score * 0.10
        )

        return total_score

    def _interpret_score(self, score: float) -> str:
        """Provide human-readable interpretation of score."""
        if score >= 90:
            return "Excellent barge-in handling"
        elif score >= 70:
            return "Good barge-in handling"
        elif score >= 50:
            return "Acceptable barge-in handling"
        elif score >= 30:
            return "Poor barge-in handling"
        else:
            return "Very poor barge-in handling"


__all__ = ["BargeInMetric"]
```

## Integration

### 1. Register Metric in `production/metrics/__init__.py`

```python
from .barge_in import BargeInMetric

METRIC_REGISTRY = {
    # ... existing metrics ...
    "barge_in": BargeInMetric,
}
```

### 2. Update `get_metrics()` function

```python
def get_metrics(scenario: Scenario, conversation_manager: ConversationManager) -> List[Metric]:
    if not scenario.metrics:
        return [
            # ... existing metrics ...
            BargeInMetric(scenario, conversation_manager),  # Add this
        ]
    # ...
```

### 3. Enable for Specific Test

In `patient_correction_barge_in.yaml`:

```yaml
id: patient_correction_barge_in
# ... existing config ...
metrics:
  - barge_in  # Only run barge-in metric for this test
  - wer  # Optional: also check translation accuracy
```

Or run all metrics (barge-in will only score when barge_in turns exist).

## Example Output

```json
{
  "metric_name": "barge_in",
  "score": 87.5,
  "reason": null,
  "details": {
    "threshold": 70.0,
    "barge_in_count": 1,
    "turns": [
      {
        "previous_turn_id": "patient_initial_statement",
        "barge_in_turn_id": "patient_correction",
        "barge_in_start_ms": 22000,
        "score": 87.5,
        "cutoff_latency_ms": 450,
        "mixing_detected": false,
        "response_time_ms": 1200,
        "interpretation": "Excellent barge-in handling"
      }
    ],
    "overall_interpretation": "Excellent barge-in handling"
  }
}
```

## Testing Recommendations

### 1. Baseline Test (Expected: High Score)
- System properly handles barge-in
- Translations stop within 500ms
- No content mixing
- Quick response to new turn

### 2. Failure Test Cases

Create additional test scenarios to validate metric:

**Slow Cutoff Test** (Expected: Medium Score):
- Adjust system to continue previous translation for 2+ seconds
- Should score 40-70 points

**Content Mixing Test** (Expected: Low Score):
- System delivers mixed translations
- Should score < 30 points

**No Barge-In Test** (Expected: N/A):
- Scenario with no `barge_in: true` turns
- Metric should return "No barge-in turns found"

## Future Enhancements

1. **LLM-Based Content Mixing Detection**: Use LLM to detect semantic mixing
2. **Audio Analysis**: Analyze translated audio timing vs text timing
3. **Multi-Participant Barge-In**: Support doctor interrupting patient (different participants)
4. **Barge-In Types**: Distinguish self-correction vs topic change vs interruption
5. **Adaptive Thresholds**: Adjust scoring based on audio duration and complexity

# Score Calculators Implementation

## Overview

Implemented a flexible score calculator system that allows different strategies for calculating overall test scores from metric results.

### Key Changes

1. **New Score Calculator Architecture**
   - Protocol-based design for pluggable calculators
   - Two implementations: `AverageScoreCalculator` and `GarbledTurnScoreCalculator`
   - Factory function for easy instantiation

2. **Updated TestRun Model**
   - ✅ Added: `score_method` (str) - Calculator used
   - ✅ Added: `score_status` (str) - Calculator-determined status
   - ✅ Kept: `score` (float) - Overall score 0-100
   - ❌ Removed: `status` (str) - Replaced by `score_status`
   - ❌ Removed: `passed` (bool) - Replaced by `score_status`

3. **Updated Scenario Model**
   - ✅ Added: `score_method` (str) - Configurable in YAML (default: "average")

4. **Updated MetricsRunner**
   - ✅ Added: `score_method` parameter to `__init__`
   - ✅ Uses score calculators in `_persist_test_result`
   - ✅ Logs score calculation details

---

## Score Calculators

### 1. AverageScoreCalculator (Default)

**Method:** `"average"`

**Description:** Calculates score as percentage of passed metrics.

**Formula:**
```python
score = (passed_metrics / total_metrics) * 100
```

**Status:**
- `"success"` - All metrics passed
- `"failed"` - At least one metric failed

**Example:**
```python
# 8 out of 10 metrics passed
{
    "score": 80.0,
    "score_method": "average",
    "score_status": "failed",
    "details": {
        "total_metrics": 10,
        "passed_metrics": 8,
        "failed_metrics": 2,
        "all_passed": false
    }
}
```

---

### 2. GarbledTurnScoreCalculator

**Method:** `"garbled_turn"`

**Description:** Calculates score based on conversational quality. Flags turns as "garbled" if any quality dimension is low (≤ 2 out of 5).

**Requirements:**
- Must have `intelligibility`, `segmentation`, and `context` metrics in results
- Each metric must have per-event scores in `details.results[]`

**Garbled Detection Rule:**
```python
garbled = (intelligibility_score <= 2) OR
          (segmentation_score <= 2) OR
          (context_score <= 2)

# On 0-1 scale: score_normalized <= 0.25
```

**Formula:**
```python
garbled_turn_rate = garbled_turns / total_turns
score = (1 - garbled_turn_rate) * 100
```

**Status:**
- `"success"` - garbled_turn_rate ≤ threshold (default 10%)
- `"garbled"` - garbled_turn_rate > threshold
- `"error"` - Missing required metrics

**Configuration:**
```python
# Default 10% threshold
calculator = GarbledTurnScoreCalculator()

# Custom 15% threshold
calculator = GarbledTurnScoreCalculator(garbled_threshold=0.15)
```

**Example Output:**
```python
{
    "score": 85.0,
    "score_method": "garbled_turn",
    "score_status": "garbled",  # 15% exceeds 10% threshold
    "details": {
        "garbled_turn_rate": "15.00%",
        "threshold": "10.00%",
        "total_turns": 20,
        "garbled_turns": 3,
        "clean_turns": 17,
        "event_scores": [
            {
                "event_id": "patient_turn_1",
                "intelligibility_score": 5,
                "segmentation_score": 5,
                "context_score": 4,
                "garbled": false,
                "reason": null
            },
            {
                "event_id": "nurse_turn_1",
                "intelligibility_score": 5,
                "segmentation_score": 5,
                "context_score": 2,  # ≤ 2!
                "garbled": true,
                "reason": "Low scores: context (2/5)"
            }
        ],
        "avg_intelligibility": 4.8,
        "avg_segmentation": 4.9,
        "avg_context": 3.2
    }
}
```

---

## Usage

### 1. Scenario Configuration (YAML)

```yaml
id: my_test_scenario
description: Test conversational quality
tags: [medical]

# NEW: Specify score calculator
score_method: garbled_turn  # or "average" (default)

participants:
  # ... participant config ...

events:
  # ... event config ...

expectations:
  # ... expectations config ...
```

### 2. Programmatic Usage

```python
from production.metrics import MetricsRunner
from production.metrics.score_calculators import get_score_calculator

# Option A: Pass score_method to runner
runner = MetricsRunner(
    expectations=expectations,
    events=events,
    score_method="garbled_turn"  # or "average"
)

# Option B: Use calculator directly
calculator = get_score_calculator("garbled_turn", garbled_threshold=0.15)
test_score = calculator.calculate(metric_results)

print(f"Score: {test_score.score:.2f}")
print(f"Status: {test_score.score_status}")
print(f"Method: {test_score.score_method}")
```

### 3. Test Execution Flow

```
1. Load Scenario YAML
   ↓ (includes score_method)

2. Execute Test
   ↓ (collect events)

3. Run Metrics
   ↓ (intelligibility, segmentation, context, ...)

4. Calculate Test Score
   ↓ (using configured calculator)

5. Persist TestRun
   ↓ (includes score, score_method, score_status)

6. MongoDB Storage
   {
     "score": 85.0,
     "score_method": "garbled_turn",
     "score_status": "garbled",
     ...
   }
```

---

## Integration Points

### 1. Scenario Loading

The scenario loader must pass `score_method` from YAML to MetricsRunner:

```python
scenario = load_scenario("test.yaml")

runner = MetricsRunner(
    expectations=scenario.expectations,
    events=collected_events,
    score_method=scenario.score_method  # ← From YAML
)
```

### 2. TestRun Persistence

The updated TestRun model stores all score information:

```python
test_run = TestRun(
    evaluation_run_id=eval_id,
    test_run_id=test_run_id,
    test_id=scenario.id,
    test_name=scenario.description,
    started_at=start_time,
    finished_at=end_time,
    duration_ms=duration,
    metrics=metrics_dict,
    score=test_score.score,           # ← From calculator
    score_method=test_score.score_method,  # ← From calculator
    score_status=test_score.score_status,  # ← From calculator
    tags=scenario.tags,
    participants=participant_names
)
```

### 3. Querying Results

MongoDB queries can now filter by score calculator:

```javascript
// Find all tests using garbled_turn calculator
db.test_runs.find({ "score_method": "garbled_turn" })

// Find tests with garbled status
db.test_runs.find({ "score_status": "garbled" })

// Find tests with score < 90
db.test_runs.find({ "score": { $lt: 90 } })

// Aggregate by score_status
db.test_runs.aggregate([
  { $group: { _id: "$score_status", count: { $sum: 1 } } }
])
```

---

## Files Created

### Core Calculator Files

1. **`production/metrics/score_calculators/base.py`** (67 lines)
   - `ScoreCalculator` protocol
   - `TestScore` dataclass

2. **`production/metrics/score_calculators/average.py`** (82 lines)
   - `AverageScoreCalculator` implementation
   - Original/default behavior

3. **`production/metrics/score_calculators/garbled_turn.py`** (276 lines)
   - `GarbledTurnScoreCalculator` implementation
   - Conversational quality scoring

4. **`production/metrics/score_calculators/__init__.py`** (52 lines)
   - Package exports
   - `get_score_calculator()` factory

### Modified Files

5. **`production/storage/models.py`**
   - Updated `TestRun` dataclass
   - Removed `status`, `passed`
   - Added `score_method`, `score_status`
   - Updated `to_document()`

6. **`production/scenario_engine/models.py`**
   - Added `score_method` field to `Scenario`
   - Default value: `"average"`

7. **`production/metrics/runner.py`**
   - Added `score_method` parameter to `__init__`
   - Updated `_persist_test_result()` to use calculators
   - Removed dependency on old `_calculate_test_score()` in persistence

---

## Backward Compatibility

### Breaking Changes

1. **TestRun Model**
   - ❌ `status` field removed → Use `score_status` instead
   - ❌ `passed` field removed → Use `score_status == "success"` instead

2. **MongoDB Documents**
   - Existing documents will not have `score_method` or `score_status`
   - Migration may be needed for historical data

### Migration Strategy

```python
# MongoDB migration script
db.test_runs.updateMany(
    { "score_method": { $exists: false } },
    {
        $set: {
            "score_method": "average",
            "score_status": { $cond: [ "$passed", "success", "failed" ] }
        },
        $unset: { "status": "", "passed": "" }
    }
)
```

### Compatibility Layer (Optional)

If needed, add properties to TestRun for backward compatibility:

```python
@dataclass
class TestRun:
    # ... existing fields ...

    @property
    def status(self) -> str:
        """Backward compatibility: map score_status to old status field."""
        return self.score_status

    @property
    def passed(self) -> bool:
        """Backward compatibility: passed = success status."""
        return self.score_status == "success"
```

---

## Testing

### Unit Tests

Create tests for calculators:

```python
# production/metrics/score_calculators/test_calculators.py

def test_average_calculator():
    results = [
        MetricResult("wer", passed=True, value=0.9),
        MetricResult("completeness", passed=True, value=0.85),
        MetricResult("context", passed=False, value=0.60),
    ]

    calc = AverageScoreCalculator()
    score = calc.calculate(results)

    assert score.score == 66.67  # 2/3 passed
    assert score.score_method == "average"
    assert score.score_status == "failed"

def test_garbled_turn_calculator():
    # Create mock metric results with per-event scores
    intell_result = MetricResult(
        "intelligibility",
        passed=True,
        value=0.85,
        details={
            "results": [
                {"event_id": "turn1", "status": "evaluated", "score_1_5": 5, "score_normalized": 1.0},
                {"event_id": "turn2", "status": "evaluated", "score_1_5": 2, "score_normalized": 0.25},
            ]
        }
    )
    # ... similar for segmentation, context ...

    calc = GarbledTurnScoreCalculator(garbled_threshold=0.10)
    score = calc.calculate([intell_result, segment_result, context_result])

    assert score.score_status == "garbled"  # 50% garbled rate > 10%
    assert score.details["garbled_turns"] == 1
```

### Integration Tests

Test with actual scenario execution:

```bash
# Test with garbled_turn calculator
poetry run python -m production.cli run-test \
    production/tests/scenarios/context_loss_uti.yaml

# Verify TestRun has correct fields
mongo metrics --eval 'db.test_runs.findOne({test_id: "context_loss_uti"})'
```

---

## Adding New Calculators

To add a new calculator:

### 1. Create Calculator Class

```python
# production/metrics/score_calculators/my_calculator.py

from .base import ScoreCalculator, TestScore

class MyScoreCalculator(ScoreCalculator):
    name = "my_method"

    def __init__(self, my_param: float = 0.5):
        self.my_param = my_param

    def calculate(self, metric_results: List[MetricResult]) -> TestScore:
        # Custom scoring logic
        score = ...  # 0-100
        status = ...  # custom status

        return TestScore(
            score=score,
            score_method=self.name,
            score_status=status,
            details={...}
        )
```

### 2. Register in Factory

```python
# production/metrics/score_calculators/__init__.py

from .my_calculator import MyScoreCalculator

def get_score_calculator(method: str = "average", **kwargs) -> ScoreCalculator:
    # ... existing code ...

    elif method == "my_method":
        my_param = kwargs.get("my_param", 0.5)
        return MyScoreCalculator(my_param=my_param)

    # ... existing code ...
```

### 3. Update Documentation

Add to scenario YAML options:

```yaml
score_method: my_method  # New calculator
```

---

## Summary

✅ **Implemented flexible score calculator system**
- Two calculators: `average` (default), `garbled_turn`
- Pluggable architecture via protocol

✅ **Updated TestRun model**
- Added `score_method`, `score_status`
- Removed `status`, `passed`

✅ **Scenario configuration**
- YAML field: `score_method` (default: "average")

✅ **Integration complete**
- MetricsRunner uses calculators
- TestRun persistence updated
- MongoDB schema aligned

✅ **Ready for use**
- Default behavior preserved (average calculator)
- Garbled turn calculator ready for conversational quality tests
- Extensible for future calculators

**Files:** 7 files created/modified (~700 lines of code)

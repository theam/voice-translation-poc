# Conversational Quality Metrics Implementation

## Phase 2 - Complete ✓

Implementation of three new conversational quality metrics for evaluating bot turns:
- **IntelligibilityMetric** - Text clarity and readability
- **SegmentationMetric** - Sentence boundaries and turn segmentation
- **ContextMetric** - Conversational context and relevance

---

## Implemented Files

### 1. `production/metrics/intelligibility.py`
- Evaluates how clear, readable, and understandable the translated text is
- Uses LLM (OpenAI GPT-4o-mini) to score on 1-5 scale
- Converts to 0-100% scale: `(score - 1) / 4 * 100`
- Default threshold: 80% (requires score ≥ 4.2/5)

**Scoring Guide (1-5):**
- 5: Perfect clarity, natural flow
- 4: Clear, minor awkwardness
- 3: Understandable but awkward phrasing
- 2: Difficult to understand, clarity issues (⚠️ garbled)
- 1: Unintelligible, garbled (⚠️ garbled)

### 2. `production/metrics/segmentation.py`
- Evaluates sentence boundaries and turn segmentation
- Checks for proper punctuation and natural breaks
- Same 1-5 scale conversion as intelligibility
- Default threshold: 80%

**Scoring Guide (1-5):**
- 5: Perfect segmentation, natural breaks
- 4: Good segmentation, one minor issue
- 3: Acceptable, multiple minor issues
- 2: Poor segmentation, incorrect splits (⚠️ garbled)
- 1: Severely fragmented or run-on (⚠️ garbled)

### 3. `production/metrics/context.py`
- Evaluates conversational context and relevance
- Uses conversation history (last 5 turns by default)
- Detects context loss and topic drift
- Same 1-5 scale conversion
- Default threshold: 80%

**Scoring Guide (1-5):**
- 5: Perfect context awareness
- 4: Good context, minor deviation
- 3: Acceptable, some drift
- 2: Poor context, significant drift (⚠️ garbled) - **UTI example**
- 1: Complete context loss (⚠️ garbled)

**Special Features:**
- Includes prior conversation turns in LLM prompt
- Configurable history window (`max_history_turns=5`)
- Handles first turn (no prior context)

### 4. `production/metrics/__init__.py` (Updated)
- Registered all three new metrics in `get_metrics()` factory
- Added to `__all__` exports
- Integrated with existing metric pipeline

### 5. `production/metrics/test_conversational_quality.py`
- Unit tests for all three metrics
- Score conversion validation
- Prior events extraction tests
- Mock LLM evaluation tests
- Garbled detection logic tests

---

## Score Conversion

### 1-5 Scale → 0-100% Scale

Formula: `(score - 1) / 4`

```
Score 1 → 0.00 (0%)    ← Garbled threshold
Score 2 → 0.25 (25%)   ← Garbled threshold
Score 3 → 0.50 (50%)
Score 4 → 0.75 (75%)
Score 5 → 1.00 (100%)
```

### Thresholds

**Pass/Fail Threshold:** 80% (0.80)
- Requires average score ≥ 4.2 out of 5
- Scores 1-4 fail the threshold
- Only score 5 passes

**Garbled Detection:** ANY score ≤ 2
- Used in Phase 3 for GarbledTurnMetric
- Flags turns with serious quality issues

---

## MetricResult Structure

Each metric returns the standard `MetricResult` format:

```python
MetricResult(
    metric_name="intelligibility",  # or "segmentation", "context"
    passed=True,                     # True if overall_score >= threshold
    value=0.85,                      # Overall average (0-1 scale)
    reason=None,                     # Error message if failed
    details={
        "overall_score": "85.00%",
        "threshold": 0.80,
        "evaluations": 3,
        "results": [
            {
                "id": "patient_turn_1_translation",
                "event_id": "patient_turn_1",
                "status": "evaluated",
                "score_1_5": 5,              # Original 1-5 score
                "score_normalized": 1.0,     # Converted to 0-1
                "score_percentage": "100.00%",
                "passed": True,
                "reasoning": "Perfect clarity and natural flow",
                "text": "I have a fever and body aches",
                "tokens_used": 45,
                "model": "gpt-4o-mini"
            }
        ],
        # Session aggregates
        "avg_intelligibility_1_5": 4.67,    # Average on 1-5 scale
        "avg_intelligibility_0_100": 91.75  # Average as percentage
    }
)
```

### Per-Event Scores

Each expectation is scored individually in `details.results[]`:
- `score_1_5`: Original LLM score (1-5)
- `score_normalized`: Converted score (0-1)
- `score_percentage`: Percentage string for display
- `reasoning`: LLM explanation
- `text`: The evaluated text

### Session Aggregates

Available in `details`:
- `avg_<metric>_1_5`: Average score on 1-5 scale
- `avg_<metric>_0_100`: Average score as percentage
- `overall_score`: Percentage string of normalized average

---

## LLM Prompts

### Intelligibility Prompt

**System:**
```
You are an expert evaluator for conversational quality.
Evaluate the INTELLIGIBILITY of the translated text.

Score from 1-5:
- 5: Perfect clarity, natural flow, easily understandable
- 4: Clear and understandable, minor awkwardness or grammatical issues
- 3: Understandable but with awkward phrasing or unnatural word order
- 2: Difficult to understand, significant clarity or grammatical issues
- 1: Unintelligible, garbled, or incomprehensible text

Respond ONLY with valid JSON:
{
    "intelligibility_score": <integer 1-5>,
    "reasoning": "<brief explanation in English>"
}
```

**User:**
```
Translated text:
"<text>"

Evaluate the intelligibility (clarity and readability) on a scale of 1-5.
```

### Segmentation Prompt

Similar structure, focuses on:
- Sentence boundaries
- Punctuation
- Turn segmentation
- Over-fragmentation vs run-on sentences

### Context Prompt

**Unique Feature:** Includes conversation history

**User:**
```
Conversation history:
Speaker 1: "I have a fever and body aches"
Speaker 2: "Have you been near anyone sick?"

Current response:
"Yes, my son had the flu last week"

Evaluate the context (relevance to conversation history) on a scale of 1-5.
```

---

## Usage Examples

### Basic Usage (Automatic Registration)

```python
from production.metrics import get_metrics
from production.scenario_engine.models import Expectations
from production.capture.collector import CollectedEvent

# Metrics are automatically included
metrics = get_metrics(expectations, events)
# Returns: [SequenceMetric, WERMetric, ..., IntelligibilityMetric, SegmentationMetric, ContextMetric]

# Run all metrics
for metric in metrics:
    result = metric.run()
    print(f"{metric.name}: {result.value:.2%}")
```

### Custom Thresholds

```python
from production.metrics import IntelligibilityMetric

# Require 90% intelligibility (score ≥ 4.6/5)
metric = IntelligibilityMetric(
    expectations,
    events,
    threshold=0.90
)
```

### Custom LLM Model

```python
from production.metrics import ContextMetric

# Use GPT-4o for better context understanding
metric = ContextMetric(
    expectations,
    events,
    model="gpt-4o"
)
```

### Custom Context Window

```python
# Include last 10 turns instead of default 5
metric = ContextMetric(
    expectations,
    events,
    max_history_turns=10
)
```

---

## Testing

### Run Unit Tests

```bash
cd /Users/abujeda/dev/vt/vt-translations/vt-voice-translation-poc

# Run all conversational quality tests
pytest production/metrics/test_conversational_quality.py -v

# Run specific test class
pytest production/metrics/test_conversational_quality.py::TestIntelligibilityMetric -v

# Run with coverage
pytest production/metrics/test_conversational_quality.py --cov=production.metrics
```

### Test Coverage

Current tests cover:
- ✅ Score conversion (1-5 → 0-100%)
- ✅ Metric initialization
- ✅ No expectations edge case
- ✅ Custom thresholds
- ✅ Custom model override
- ✅ Average score calculation
- ✅ Prior events extraction (ContextMetric)
- ✅ Max history limit (ContextMetric)
- ✅ First turn handling (ContextMetric)
- ✅ Garbled detection logic
- ✅ Pass/fail thresholds
- ✅ Mock LLM evaluation

---

## Integration with Existing Framework

### ✅ Follows Existing Patterns

1. **Same structure as TechnicalTermsMetric:**
   - `__init__(expectations, events, threshold, ...)`
   - `run() -> MetricResult`
   - `_evaluate_expectation()`
   - `_call_llm_evaluation()`

2. **Uses existing utilities:**
   - `EventMatcher` for finding matching events
   - `get_llm_service()` for LLM client
   - `LLMResponse` for response handling

3. **Standard MetricResult format:**
   - `value`: Overall score (0-1)
   - `details.results[]`: Per-expectation scores
   - `details.<aggregates>`: Session-level stats

### ✅ Registered in Factory

All three metrics are automatically included when calling `get_metrics()`:

```python
# production/metrics/__init__.py
return [
    SequenceMetric(expectations, events),
    WERMetric(expectations, events),
    TechnicalTermsMetric(expectations, events),
    CompletenessMetric(expectations, events),
    IntentPreservationMetric(expectations, events),
    LanguageCorrectnessMetric(expectations, events),
    IntelligibilityMetric(expectations, events),    # ← NEW
    SegmentationMetric(expectations, events),       # ← NEW
    ContextMetric(expectations, events),            # ← NEW
]
```

### ✅ Works with Existing YAML Scenarios

No changes needed to YAML structure. Metrics evaluate existing `expectations.transcripts[]`:

```yaml
expectations:
  transcripts:
    - id: patient_turn_1_translation
      event_id: patient_turn_1
      source_language: en-US
      target_language: es-ES
      expected_text: "I have a fever and body aches"
      # ← Will be evaluated by all 3 new metrics
```

---

## Next Steps (Phase 3)

### GarbledTurnMetric

Create a derived metric that:
1. Runs (or receives) the 3 quality metrics
2. Flags turns as garbled if ANY score ≤ 2
3. Calculates `garbled_turn_rate` for session
4. Returns pass/fail based on rate threshold (< 10%)

**Implementation:**
```python
class GarbledTurnMetric(Metric):
    name = "garbled_turn"

    def run(self) -> MetricResult:
        # Get results from the 3 metrics
        # Check if ANY score ≤ 2 per turn
        # Calculate garbled_turn_rate
        # Return pass if rate < threshold
```

### Test Scenarios

Create YAML scenarios for validation:
1. **UTI context loss** → context ≤ 2, garbled = true
2. **Paddle→soccer drift** → intelligibility ≥ 4, segmentation ≥ 4, context 2-3
3. **Good conversation** → all ≥ 4, garbled_rate < 10%

---

## Configuration

### Environment Variables

Uses existing LLM configuration:
- `AZURE_AI_FOUNDRY_KEY` - OpenAI API key
- `OPENAI_BASE_URL` - Azure OpenAI endpoint
- `LLM_MODEL` - Model name (default: gpt-4o-mini)

### Defaults

```python
# Thresholds
INTELLIGIBILITY_THRESHOLD = 0.80  # 80% = score ≥ 4.2/5
SEGMENTATION_THRESHOLD = 0.80     # 80% = score ≥ 4.2/5
CONTEXT_THRESHOLD = 0.80          # 80% = score ≥ 4.2/5

# Context window
MAX_HISTORY_TURNS = 5             # Last 5 turns

# LLM settings
LLM_MODEL = "gpt-4o-mini"         # Fast, cost-effective
LLM_TEMPERATURE = 0.1             # Deterministic scoring
```

---

## Dependencies

All dependencies already exist in the framework:
- ✅ `production.services.llm_service` - LLM client
- ✅ `production.capture.collector` - Event collection
- ✅ `production.scenario_engine.models` - Scenario models
- ✅ `production.metrics.base` - Metric protocol
- ✅ `production.metrics.utils` - EventMatcher

No new dependencies added.

---

## Performance Considerations

### LLM Calls per Test

Each metric makes **1 LLM call per transcript expectation**:
- IntelligibilityMetric: N calls
- SegmentationMetric: N calls
- ContextMetric: N calls
- **Total: 3N calls** (where N = number of transcript expectations)

### Optimization Opportunity (Phase 5)

Could combine all 3 scores in a single LLM call:

```python
# Combined prompt requesting all 3 scores
{
    "intelligibility_score": 5,
    "segmentation_score": 5,
    "context_score": 4,
    "reasoning": "..."
}

# Reduces: 3N calls → N calls (3x faster, 3x cheaper)
```

---

## Troubleshooting

### Invalid Score from LLM

If LLM returns score outside 1-5 range:
- Defaults to score of 1 (most conservative)
- Logs warning message
- Continues evaluation

### Missing Text in Event

If matched event has no text:
- Returns status "failed"
- Score defaults to 1 (0%)
- Includes reason in result

### LLM Service Error

If LLM service fails to initialize or call fails:
- Returns status "error"
- Overall metric fails with error message
- Details include error information

---

## Summary

✅ **Phase 2 Complete**
- 3 new metrics implemented
- Following existing patterns
- Integrated with framework
- Unit tests written
- Ready for Phase 3 (GarbledTurnMetric)

**Files Created:**
1. `production/metrics/intelligibility.py` (265 lines)
2. `production/metrics/segmentation.py` (261 lines)
3. `production/metrics/context.py` (330 lines)
4. `production/metrics/test_conversational_quality.py` (326 lines)
5. `production/metrics/__init__.py` (updated)

**Total:** ~1,200 lines of production code + tests

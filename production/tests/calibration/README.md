# Metrics Calibration System

## Overview

The calibration system validates that metrics produce expected scores on known test cases. This is critical for LLM-based metrics where model updates or prompt changes could cause drift.

**Key Features:**
- **Validate metric consistency** - Ensure metrics score as expected
- **Detect metric drift** - Track scoring changes over time
- **Deterministic testing** - Uses loopback client for repeatable results
- **Standard scenario format** - Uses regular scenario YAML with `metric_expectations`

## Architecture

Calibration scenarios are **standard scenario tests** with two key differences:

1. **Loopback client** - Uses `websocket_client: loopback` to avoid real service dependencies
2. **Metric expectations** - Each turn includes `metric_expectations` field with expected scores

```
Scenario YAML (with metric_expectations)
    ↓
ScenarioLoader
    ↓
ScenarioEngine (with loopback client)
    ↓
MetricsRunner (compares actual vs expected scores)
    ↓
Results (pass/fail per turn)
```

## Running Calibration

### Command Line

```bash
# Run all calibrations
make calibrate

# Run specific metric (matches scenario tags or folder names)
make calibrate ARGS="--metric intelligibility"

# Run a single calibration scenario
poetry run python -m production.cli calibrate \
    --file tests/calibration/segmentation/segmentation_baseline.yaml

# Custom glob pattern (defaults to **/*.yaml)
poetry run python -m production.cli calibrate \
    --pattern "context/*.yaml"

# Store results to MongoDB (requires MONGODB_* env vars)
make calibrate ARGS="--store"
```

### Python API

```python
from production.cli.calibrate import calibrate_async
from pathlib import Path

# Run calibration programmatically
await calibrate_async(
    file=None,
    directory=Path("tests/calibration"),
    pattern="**/*.yaml",
    metric="intelligibility",
    log_level="INFO",
    store=True
)
```

## YAML Schema

Calibration scenarios use the **standard scenario format** with additional `metric_expectations` field on turns.

### Basic Example

```yaml
id: intelligibility_calibration_baseline
description: Baseline calibration for intelligibility metric
websocket_client: loopback  # Use loopback client for deterministic results
tags: [calibration, intelligibility, baseline]

participants:
  patient:
    source_language: en
    target_language: es

turns:
  - id: perfect_clarity
    type: loopback_text
    participant: patient
    text: "I have a fever and body aches."
    start_at_ms: 0
    source_language: en
    expected_language: es
    source_text: "I have a fever and body aches."
    expected_text: "I have a fever and body aches."
    metric_expectations:
      intelligibility: 100.0  # Expected score (0-100 scale)
```

### Required Fields

**Scenario-level:**
- `id` - Unique scenario identifier
- `description` - What this calibration tests
- `websocket_client: loopback` - Use loopback client
- `tags` - Must include "calibration" tag

**Turn-level:**
- `id` - Unique turn identifier
- `type: loopback_text` - Loopback text turn processor
- `text` - The text to evaluate
- `expected_text` - Ground truth (what should have been said)
- `metric_expectations` - Dictionary of expected scores by metric name

### Score Scale

**All scores use 0-100 scale:**
- **100.0** - Perfect (100%)
- **75.0** - Good (75%)
- **50.0** - Acceptable (50%)
- **25.0** - Poor (25%)
- **0.0** - Complete failure (0%)

Use this scale for all metric expectations and tolerances.

**Tolerance** is also on 0-100 scale:
- Default: `10.0` (±10 points)
- Set globally via `CALIBRATION_TOLERANCE` env var or `FrameworkConfig.calibration_tolerance`
- Override per-scenario via `Scenario.tolerance` field in YAML

## Supported Metrics

### Per-Turn Metrics
These metrics evaluate **each turn individually**. Use `metric_expectations` on turns:

1. **intelligibility** - Text clarity and readability (0-100)
2. **segmentation** - Sentence boundaries and punctuation (0-100)
3. **technical_terms** - Technical terminology preservation (0-100)
4. **completeness** - Information completeness (0-100)
5. **intent_preservation** - Communicative intent (0-100)
6. **target_language** - Language boundary preservation (0-100)
7. **wer** - Word Error Rate (0-100, inverted from error rate)

**Example:**
```yaml
turns:
  - id: turn_1
    metric_expectations:
      intelligibility: 100.0  # Per-turn expectation
      segmentation: 95.0
```

### Conversation-Level Metrics
These metrics evaluate the **entire conversation context**. Use scenario `expected_score` only:

1. **context** - Conversational relevance (0-100)

**Example:**
```yaml
id: my_test
expected_score: 90.0  # Conversation metric expectation
turns:
  - id: turn_1
    # NO metric_expectations for conversation metrics!
```

**Important:** Do NOT add conversation metrics to turn `metric_expectations`!

## File Organization

```
production/tests/calibration/
├── README.md                          # This file
├── intelligibility/
│   ├── perfect_clarity.yaml           # Perfect intelligibility (1.0)
│   ├── awkward_structure.yaml         # Moderate issues (0.50)
│   └── word_order_issues.yaml         # Severe issues (0.25)
├── segmentation/
│   ├── perfect_segmentation.yaml      # Perfect punctuation (1.0)
│   ├── missing_punctuation.yaml       # Moderate issues (0.50)
│   └── no_punctuation.yaml            # Severe issues (0.25)
└── context/
    ├── perfect_context.yaml           # Perfect relevance (1.0)
    ├── loose_context.yaml             # Moderate drift (0.50)
    └── context_loss.yaml              # Complete loss (0.0)
```

## Loopback Client

The loopback client echoes messages back with configurable delay, providing deterministic results for calibration.

**Benefits:**
- No external service dependencies
- Repeatable results
- Fast execution
- Ideal for CI/CD pipelines

**How it works:**
1. Turn processor sends expected text as `translation.text_delta` message
2. Loopback client echoes it back after configured delay
3. Metrics evaluate the text
4. Actual scores are compared against `metric_expectations`

## Results & Storage

### Console Output

Calibration runs surface pass/fail in the CLI with detailed per-turn results.

### MongoDB Storage (Optional)

Use the `--store` flag to persist calibration results to MongoDB:

```bash
poetry run python -m production.cli calibrate --store
```

**Requirements:**
- `MONGODB_ENABLED=true` or `--store` flag
- `MONGODB_CONNECTION_STRING` environment variable
- `MONGODB_DATABASE` environment variable

**What's stored:**
- Evaluation run metadata (git commit, timestamp, environment)
- Test results per scenario
- Metric scores (actual vs expected)
- `target_system: "calibration"` for easy filtering

### Artifacts

Calibration runs produce the same artifacts as regular scenario tests:
- Transcripts
- Metrics reports
- Raw WebSocket logs
- PDF reports (if enabled)

## Creating New Calibration Scenarios

### 1. Choose Target Metric

What are you testing?
- Specific metric behavior
- Edge cases
- Known failure modes
- Boundary conditions

### 2. Create Test Cases

Include variety across the score spectrum:
- **Perfect cases (1.0)** - Ideal translations
- **Good cases (0.75)** - Minor issues
- **Acceptable cases (0.50)** - Noticeable problems
- **Poor cases (0.25)** - Significant issues
- **Complete failure (0.0)** - Unintelligible output
- **Edge cases** - Single words, empty, special characters

### 3. Use Real Examples

Base calibration cases on actual translation failures observed in production or testing.

### 4. Test Thoroughly

Run your calibration to ensure:
- Expected scores are reasonable
- Edge cases are handled
- Metrics behave consistently

## Example: Creating Intelligibility Calibration

```yaml
id: intelligibility_new_cases
description: Additional intelligibility test cases
websocket_client: loopback
tags: [calibration, intelligibility]

participants:
  patient:
    source_language: en
    target_language: es

turns:
  # Perfect case
  - id: perfect
    type: loopback_text
    participant: patient
    text: "I have a headache."
    start_at_ms: 0
    source_language: en
    expected_language: es
    source_text: "I have a headache."
    expected_text: "I have a headache."
    metric_expectations:
      intelligibility: 1.0

  # Poor case (word order issues)
  - id: poor
    type: loopback_text
    participant: patient
    text: "Headache have I."
    start_at_ms: 1000
    source_language: en
    expected_language: es
    source_text: "Headache have I."
    expected_text: "I have a headache."
    metric_expectations:
      intelligibility: 0.25
```

## Best Practices

### 1. Use Descriptive IDs
Turn IDs should indicate what's being tested:
- `perfect_clarity_medical`
- `minor_awkwardness`
- `completely_garbled`

### 2. Cover Edge Cases
- Very short text ("Yes", "No")
- Very long text (run-on sentences)
- Missing punctuation
- Garbled text
- Perfect examples

### 3. Group Related Tests
Organize calibration files by metric:
```
intelligibility/
├── intelligibility_baseline.yaml
├── intelligibility_medical.yaml
└── intelligibility_casual.yaml
```

### 4. Tag Appropriately
Use tags for filtering:
- `calibration` (required)
- Metric name (`intelligibility`, `context`, etc.)
- Domain (`medical`, `casual`, `technical`)
- Category (`baseline`, `edge_cases`, `regression`)

### 5. Test Regularly
Run calibrations:
- After metric prompt changes
- After LLM model updates
- Before major releases
- In CI/CD pipelines

### 6. Track Over Time
Use `--store` flag to track calibration results in MongoDB and detect drift.

## Troubleshooting

### "Scenario contains no loopback_text turns"

**Cause:** Using wrong turn type

**Solution:** Use `type: loopback_text` for calibration turns

### "No calibration scenarios found"

**Cause:** Files don't match pattern or missing tags

**Solution:**
- Ensure files have `.yaml` extension
- Add `calibration` tag to scenarios
- Check file path matches pattern

### "Metric expectations not met"

**Cause:** LLM scoring differently than expected

**Solution:**
1. Review actual scores in output
2. Adjust expected scores if LLM reasoning is valid
3. Refine metric prompt if LLM is wrong
4. Check LLM configuration (temperature, model version)

### MongoDB Connection Errors

**Cause:** Storage not configured

**Solution:**
```bash
export MONGODB_CONNECTION_STRING="mongodb://localhost:27017"
export MONGODB_DATABASE="metrics"
export MONGODB_ENABLED=true
```

## Contributing

### Adding New Calibration Cases

1. Choose existing or create new calibration file
2. Add turn with clear expected score
3. Include diverse test cases (perfect → failure)
4. Run calibration to validate: `poetry run python -m production.cli calibrate --file <your-file>`
5. Adjust expected scores if needed

### Adding New Metrics

1. Implement metric in `production/metrics/`
2. Create calibration file in `tests/calibration/<metric-name>/`
3. Add 5-10 test cases covering the score spectrum
4. Document expected behavior in turn descriptions
5. Run calibration to establish baseline

## Summary

The calibration system validates metrics using **standard scenario tests** with the loopback client for deterministic results. Key points:

- ✅ Uses regular scenario YAML format
- ✅ Loopback client for repeatability
- ✅ Metric expectations per turn
- ✅ MongoDB storage for historical tracking
- ✅ Standard artifacts (transcripts, reports, logs)
- ✅ CI/CD friendly

**Current Status:**
- 9 calibration scenarios (3 per metric)
- 3 metrics covered (intelligibility, segmentation, context)
- Each scenario tests one specific score level (perfect, moderate, severe)
- Loopback client integration
- MongoDB storage support
- CLI integration complete

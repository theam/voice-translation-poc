# Production Live Translation Testing Framework

Automated evaluation framework for live speech translation services conforming to the Azure Communication Services (ACS) WebSocket protocol. Drives scenario-based tests with multi-participant audio playback, captures translated outputs, and validates quality via WER and LLM-based metrics.

## Overview

**Core capabilities:**
- **Scenario-driven testing** – Define multi-turn conversations in YAML with participants, audio files, timing, and expectations
- **ACS protocol emulation** – WebSocket client streaming 16-bit PCM audio with ACS-compatible JSON framing
- **Quality metrics** – WER, completeness, technical term preservation, intent preservation, language correctness, sequence validation
- **Capture & artifacts** – Stores translated audio, transcripts, raw WebSocket logs, and full call tape under `production_results/`
- **MongoDB integration** – Optional metrics storage for evaluation runs with git context, system info, and aggregated scores

## Quickstart

```bash
# Run single test
poetry run python -m production.cli run-test production/tests/scenarios/allergy_ceph.yaml

# Run test suite
poetry run python -m production.cli run-suite production/tests/scenarios/
```

Configure via environment variables (see `.env.example`) or defaults in `production/utils/config.py`.

## Architecture

- **cli.py** – Typer commands for single tests and suites with MongoDB orchestration
- **scenario_engine/** – Timeline orchestration, event processors (audio, silence, hangup), timing control
- **acs_emulator/** – WebSocket client, protocol adapter (encode/decode), media engine (PCM streaming, silence generation)
- **scenarios/** – YAML/JSON loader for test definitions
- **capture/** – Audio sink, transcript sink, raw log sink, conversation tape (full call mix)
- **metrics/** – WER, sequence validation, LLM-based quality metrics (completeness, technical terms, intent, language)
- **storage/** – MongoDB client, models (EvaluationRun, TestRun, MetricData), service layer
- **services/** – LLM service (OpenAI-compatible), system information collector
- **utils/** – Config, logging, debugging, time utils, text normalization

## Key Concepts

**Scenarios** define multi-participant conversations with:
- Participants (source/target languages, audio assets)
- Events (play_audio, silence, hangup) with precise timing
- Expectations (transcript matching, event sequence, latency thresholds)

**Metrics** validate translation quality:
- **WER** – Word Error Rate against expected transcripts
- **Completeness** – LLM judges information preservation
- **Technical Terms** – LLM verifies domain-specific terminology
- **Intent Preservation** – LLM checks communicative intent
- **Language Correctness** – LLM confirms target language usage
- **Sequence** – Validates event ordering and latency

**Storage** tracks evaluation runs:
- Links test results to git commits and system configuration
- Computes aggregated metrics across test suites
- Enables historical trend analysis and A/B experiments

**Calibration** validates metric behavior:
- Tests metrics against known expected outcomes
- Detects drift in LLM-based evaluation
- YAML-based test cases with expected scores
- Supports all metrics with configurable tolerance
- Generates JSON/Markdown reports

## Calibration

The calibration system validates that metrics produce expected scores on known test cases. This is critical for LLM-based metrics where model updates or prompt changes could cause drift.

### Running Calibration

```bash
# Run all calibrations
make calibrate

# Run specific metric
make calibrate ARGS="--metric intelligibility"

# Custom tolerance (default: 0.5 on 1-5 scale)
make calibrate ARGS="--tolerance 0.3"

# Generate JSON report
make calibrate ARGS="--output reports/calibration.json"

# Generate Markdown report
make calibrate ARGS="--output reports/calibration.md"

# Hide passed tests (only show failures)
make calibrate ARGS="--hide-passed"

# Store results to MongoDB
make calibrate ARGS="--store"

# Combine options: store and generate report
make calibrate ARGS="--store --output reports/calibration.json"
```

### Calibration Files

Calibration test cases are defined in `production/tests/calibration/*.yaml`:

```yaml
id: intelligibility_calibration_baseline
version: "1.0"
metric: intelligibility
description: "Validates intelligibility scoring on varied text samples"

calibration_cases:
  - id: perfect_clarity_medical
    description: "Perfect clarity medical question"
    text: "I have a fever and body aches."
    expected_scores:
      intelligibility_1_5: 5
      intelligibility_normalized: 1.0
    expected_reasoning: "Clear, natural, grammatically correct"

  - id: garbled_unintelligible
    description: "Completely unintelligible garbled text"
    text: "hav fvr bdy ach"
    expected_scores:
      intelligibility_1_5: 1
      intelligibility_normalized: 0.0
    expected_reasoning: "No recognizable words, cannot be understood"
```

### Context Metric Calibration

The context metric requires conversation history for evaluation:

```yaml
calibration_cases:
  - id: context_loss_uti
    description: "Complete context loss mid-conversation"
    text: "Sure, soccer practice is at 5."
    conversation_history:
      - speaker: "user"
        text: "What time is my appointment with Dr. Smith?"
      - speaker: "bot"
        text: "Your appointment is at 3 PM tomorrow."
      - speaker: "user"
        text: "And what about my daughter's paddle game?"
    expected_scores:
      context_1_5: 1
      context_normalized: 0.0
```

### Tolerance

Calibration uses tolerance thresholds to account for LLM scoring variability:
- **Default**: 0.5 on 1-5 scale (allows scores within ±0.5 of expected)
- **Strict**: 0.3 for more precise validation
- **Lenient**: 1.0 for early-stage calibration

### Report Output

JSON reports include per-case details:
```json
{
  "config_id": "intelligibility_calibration_baseline",
  "accuracy": 0.90,
  "passed_cases": 9,
  "failed_cases": 1,
  "results": [
    {
      "case_id": "perfect_clarity_medical",
      "passed": true,
      "actual_score": 5.0,
      "expected_score": 5.0,
      "difference": 0.0
    }
  ]
}
```

Markdown reports provide summary tables for tracking across calibration runs.

### MongoDB Storage

Use the `--store` flag to persist calibration results to MongoDB for historical tracking:

```bash
make calibrate ARGS="--store"
```

Stored calibration runs include:
- Complete test case results with actual vs expected scores
- Accuracy and pass/fail counts
- Git commit and branch for provenance
- Timestamp and duration
- LLM model used (if applicable)

**Benefits of storage:**
- Track metric behavior over time
- Detect drift after LLM model updates
- Compare calibration runs across git commits
- Generate historical trend reports

**Querying stored calibration runs:**

The storage service provides methods for querying historical data:

```python
from production.storage.client import MongoDBClient
from production.storage.service import MetricsStorageService

# Initialize storage
client = MongoDBClient("mongodb://localhost:27017", "vt_metrics")
service = MetricsStorageService(client)

# Get recent calibrations for a specific metric
history = await service.get_calibration_history(
    metric="intelligibility",
    days=30
)

# Get calibrations filtered by accuracy
low_accuracy = await service.get_calibration_runs(
    metric="context",
    min_accuracy=0.7,
    limit=10
)
```

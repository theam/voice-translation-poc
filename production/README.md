# Production Live Translation Testing Framework

Automated evaluation framework for live speech translation services conforming to the Azure Communication Services (ACS) WebSocket protocol. Drives scenario-based tests with multi-participant audio playback, captures translated outputs, and validates quality via WER and LLM-based metrics.

## Overview

**Core capabilities:**
- **Scenario-driven testing** – Define multi-turn conversations in YAML with participants, audio files, timing, and expectations
- **Parallel execution** – Run tests concurrently to simulate multiple users or accelerate test runs
- **ACS protocol emulation** – WebSocket client streaming 16-bit PCM audio with ACS-compatible JSON framing
- **Quality metrics** – WER, completeness, technical term preservation, intent preservation, language correctness, sequence validation
- **Capture & artifacts** – Stores translated audio, transcripts, raw WebSocket logs, and full call tape under `production_results/`
- **MongoDB integration** – Optional metrics storage for evaluation runs with git context, system info, and aggregated scores

## Quickstart

```bash
# Run single test
poetry run prod run-test production/tests/scenarios/allergy_ceph.yaml

# Run test suite
poetry run prod run-suite production/tests/scenarios/

# Run tests in parallel (4 concurrent workers)
poetry run prod parallel tests production/tests/scenarios/ -j 4

# Simulate 10 users all hitting the same test at once (load testing)
poetry run prod parallel simulate-test production/tests/scenarios/allergy_ceph.yaml -u 10

# Or via Make from host
make simulate_test TEST_PATH=production/tests/scenarios/allergy_ceph.yaml USERS=10
```

Configure via environment variables (see `.env.example`) or defaults in `production/utils/config.py`.

## Architecture

- **cli/** – Typer commands for single tests, suites, parallel execution, and MongoDB orchestration
  - `run_test.py` – Single test execution
  - `run_suite.py` – Test suite execution
  - `run_parallel.py` – Parallel test runner for multi-user simulation
  - `calibrate.py` – Metric calibration
  - `generate_report.py` – PDF report generation
- **scenario_engine/** – Timeline orchestration, turn processors (audio, silence, hangup), timing control
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
- Turns (play_audio, silence, hangup) with precise timing
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
- YAML scenario tests with `metric_expectations` under `tests/calibration/`
- Loopback client keeps runs deterministic and repeatable
- Artifacts land beside standard scenario results for side-by-side comparison

## Calibration

The calibration system validates that metrics produce expected scores on known test cases. This is critical for LLM-based metrics where model updates or prompt changes could cause drift.

### Running Calibration

```bash
# Run all calibrations
make calibrate

# Filter by metric/tag (matches scenario tags or folder names)
make calibrate ARGS="--metric intelligibility"

# Run a single calibration scenario
poetry run python -m production.cli calibrate --file tests/calibration/segmentation/segmentation_baseline.yaml

# Custom glob (defaults to **/*.yaml)
poetry run python -m production.cli calibrate --pattern "context/*.yaml"

# Store results to MongoDB (requires MONGODB_* env vars)
make calibrate ARGS="--store"
```

### Calibration Files

Calibration scenarios live under `tests/calibration/**` and use the standard scenario schema with `metric_expectations` on turns:

```yaml
id: intelligibility_calibration_baseline
description: Baseline calibration for intelligibility metric - tests clarity and readability
websocket_client: loopback
tags: [calibration, intelligibility]

turns:
  - id: perfect_clarity_medical
    type: loopback_text
    participant: patient
    text: "I have a fever and body aches. I took acetaminophen four hours ago, but it hasn't gone down."
    expected_language: es-ES
    metric_expectations:
      intelligibility: 1.0
```

### Results & Storage

Calibration runs produce the same artifacts as other scenario tests (transcripts, metrics, logs) and surface pass/fail in the CLI. Report generation is no longer part of the workflow.

Use the `--store` flag to persist calibration results to MongoDB for historical tracking (requires `MONGODB_ENABLED=true` or `--store` plus connection vars). Runs are stored as standard evaluation runs with git metadata, timing, and metric details.

## Parallel Testing

The framework supports parallel test execution to simulate multiple concurrent users and accelerate test runs. Tests execute in isolated environments with unique output directories, ensuring no conflicts.

### Running Tests in Parallel

**Individual Tests** – Distribute test files across N parallel workers:

```bash
# Inside container
poetry run prod parallel tests production/tests/scenarios/ -j 4

# Via Make (from host)
make test_parallel_tests TEST_PATH=production/tests/scenarios/ JOBS=4

# Custom pattern with 8 workers
poetry run prod parallel tests production/tests/scenarios/ -p "**/*.yaml" -j 8
```

**Suite Simulation** – Run entire test suite N times concurrently (simulates N users):

```bash
# Inside container
poetry run prod parallel suites production/tests/scenarios/ -n 4

# Via Make (from host)
make test_parallel_suites COUNT=4

# Custom suite path with 8 concurrent runs
make test_parallel_suites SUITE_PATH=production/tests/scenarios/ COUNT=8

# Filter tests within each suite run
poetry run prod parallel suites production/tests/scenarios/ -n 4 -p "allergy*.yaml"
```

**Concurrent User Load Testing** – Simulate N users all starting the same test/suite simultaneously:

```bash
# Inside container
poetry run prod parallel simulate-test production/tests/scenarios/allergy_ceph.yaml -u 10

# Via Make (from host)
make simulate_test TEST_PATH=production/tests/scenarios/allergy_ceph.yaml USERS=10

# Simulate 5 users running the same suite
poetry run prod parallel simulate-suite production/tests/scenarios/ -u 5

# Via Make (from host) - defaults to 4 users
make simulate_suite SUITE_PATH=production/tests/scenarios/ USERS=5

# With pattern filtering (inside container)
poetry run prod parallel simulate-suite production/tests/scenarios/ -u 20 -p "allergy*.yaml"
```

### Parallel Execution Modes

**1. Distributed Tests (`parallel tests`)** - Distribute different tests across workers with concurrency control
- Tests are queued and run N at a time (controlled by `--jobs`)
- Best for: Running many tests efficiently with resource limits
- Use case: CI/CD test suite execution

**2. Suite Repetition (`parallel suites`)** - Run same suite N times with concurrency control
- Each suite run is queued and runs when a slot is available
- Best for: Moderate load testing with controlled resource usage
- Use case: Testing stability across multiple runs

**3. Concurrent User Simulation (`simulate-test`, `simulate-suite`)** - All N users start simultaneously
- **No concurrency limits** - all users start at the exact same time
- Best for: Load testing, stress testing, simulating traffic spikes
- Use case: Testing how the system handles sudden user load

### Parallel Execution Features

- **Isolated output**: Each run creates unique directories under `production_results/<evaluation_run_id>/<scenario_id>/`
- **Concurrent MongoDB writes**: Each test gets unique `ObjectId` for safe parallel storage
- **Progress tracking**: Real-time status updates for running tests
- **Summary reports**: Aggregated success/failure counts and timing statistics
- **Pattern matching**: Filter tests with glob patterns (`*.yaml`, `**/*.yaml`, `allergy*.yaml`)
- **Configurable concurrency**: Adjust parallel job count based on system resources (modes 1 & 2)

### Output Examples

**Distributed Tests:**
```
================================================================================
PARALLEL TEST RUN SUMMARY
================================================================================
Total tests:     12
Successful:      11
Failed:          1
Parallel jobs:   4
Total duration:  45.23s
Avg per test:    3.77s
================================================================================
```

**Concurrent User Simulation:**
```
================================================================================
CONCURRENT USER SIMULATION SUMMARY
================================================================================
Test:            allergy_ceph.yaml
Concurrent users: 10
Successful:      10
Failed:          0
Total duration:  23.45s
Avg per user:    22.18s
Min duration:    21.34s
Max duration:    23.12s
================================================================================
```

### Resource Considerations

- **WebSocket endpoint**: Verify your translation service handles concurrent connections (especially important for `simulate-*` commands which create all connections simultaneously)
- **System resources**: Monitor CPU/memory with `docker stats` when running parallel tests
- **LLM API limits**: Check OpenAI/LLM provider rate limits if running many parallel jobs
- **Recommended starting points**:
  - `parallel tests`: Start with 2-4 jobs, scale based on resources
  - `parallel suites`: Start with 2-4 concurrent runs
  - `simulate-*`: Start with 5-10 users, increase gradually to test system limits
- **Load testing**: Use `simulate-*` commands to find breaking points and capacity limits

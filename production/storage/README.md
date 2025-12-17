# Metrics Storage

Persistent storage for test metrics using MongoDB. Tracks evaluation runs and individual test results over time for trend analysis and performance evaluation.

## Overview

The storage module provides:
- **Evaluation Run Tracking**: Records git commit, branch, configuration, and aggregated metrics for each full test execution
- **Test Result Persistence**: Stores detailed per-test metrics linked to evaluation runs
- **Historical Analysis**: Query test evolution over time, compare configurations, and track performance trends
- **Optional Integration**: Storage is optional and backward-compatible with existing workflows

## Quick Start

### 1. Install MongoDB

**macOS:**
```bash
brew install mongodb-community
brew services start mongodb-community
```

**Linux (Ubuntu):**
```bash
sudo apt-get install mongodb
sudo systemctl start mongodb
```

**Docker:**
```bash
docker run -d -p 27017:27017 --name mongodb mongo:latest
```

### 2. Install Dependencies

```bash
poetry install --with evaluations
```

This installs:
- `pymongo ^4.10.1` - MongoDB driver
- `motor ^3.6.0` - Async MongoDB driver
- `gitpython ^3.1.43` - Git integration

### 3. Configure Environment Variables

Create or update `.env`:

```bash
# Enable storage
MONGODB_ENABLED=true

# MongoDB connection (local)
MONGODB_CONNECTION_STRING=mongodb://localhost:27017
MONGODB_DATABASE=vt_metrics

# Environment classification
ENVIRONMENT=dev

# Optional experiment tags (comma-separated)
EXPERIMENT_TAGS=baseline,config-tweak
```

### 4. Run Tests with Storage

```bash
# Single test
poetry run prod run-test production/scenarios/example.yaml

# Full suite
poetry run prod run-suite production/scenarios/
```

Storage will automatically:
- Create evaluation run with git info and system information snapshot
- Save detailed metrics for each test
- Compute and save aggregated metrics
- Close connection on completion

## Configuration

### Environment Variables

| Variable | Required | Default                     | Description |
|----------|----------|-----------------------------|-------------|
| `MONGODB_ENABLED` | No | `false`                     | Enable/disable storage |
| `MONGODB_CONNECTION_STRING` | No | `mongodb://localhost:27017` | MongoDB connection URI |
| `MONGODB_DATABASE` | No | `vt_metrics`                | Database name |
| `ENVIRONMENT` | No | `dev`                       | Environment tag (dev/stage/prod/lab) |
| `EXPERIMENT_TAGS` | No | `""`                        | Comma-separated experiment labels |

### MongoDB Atlas (Production)

For production deployments, use MongoDB Atlas:

```bash
export MONGODB_CONNECTION_STRING="mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority"
export MONGODB_DATABASE=vt_metrics_prod
export ENVIRONMENT=prod
```

## Data Model

### Collections

#### `evaluation_runs`
Tracks one full execution of the test framework.

**Key Fields:**
- `evaluation_run_id`: Human-readable ID (e.g., `2025-12-05T10-30-00Z-main-abcdef`)
- `started_at`, `finished_at`: Timestamps
- `git_commit`, `git_branch`: Git provenance
- `environment`: Environment classification
- `experiment_tags`: Experiment labels
- `system_information`: Full system information snapshot (test runner and translation system)
- `system_info_hash`: SHA-256 hash for quick system comparison
- `metrics`: Aggregated metrics (e.g., `wer`, `completeness`)
- `num_tests`, `num_passed`, `num_failed`: Test counts
- `status`: `running | completed | failed`
- `score`: Overall evaluation score (0-100) averaged from all test scores

**Indexes:**
- `started_at` (time-series queries)
- `evaluation_run_id` (unique lookup)
- `system_info_hash` (group by configuration)
- `experiment_tags` (filter by tags)
- `score` (for score-based queries and graphing)

#### `test_runs`
Stores detailed metrics for one test execution within an evaluation run.

**Key Fields:**
- `evaluation_run_id`: Reference to parent evaluation run (ObjectId)
- `test_run_id`: Human-readable identifier for this specific test execution
- `test_id`: Stable test identifier from scenario.id (for tracking test evolution)
- `test_name`: Human-readable name (scenario.description)
- `started_at`, `finished_at`, `duration_ms`: Timing
- `metrics`: Dictionary of metric results (WER, completeness, etc.)
- `score`: Overall test score (0-100) calculated from metrics
- `score_method`: Calculator used (e.g., `average`, `garbled_turn`)
- `tags`: Test tags from scenario
- `participants`: Participant names

**Indexes:**
- `test_run_id` (unique identifier lookup)
- `(test_id, finished_at)` (test evolution over time)
- `evaluation_run_id` (fetch all tests for an evaluation run)
- `status` (filter by success/failure)
- `score` (for score-based queries and graphing)

## Querying Data

### Using MongoDB Shell

```bash
# Connect to database
mongosh vt_metrics

# Recent evaluation runs
db.evaluation_runs.find().sort({started_at: -1}).limit(10).pretty()

# Evaluation run details
db.evaluation_runs.findOne({evaluation_run_id: "2025-12-05T10-30-00Z-main-abcdef"})

# Test runs for an evaluation run
db.test_runs.find({evaluation_run_id: ObjectId("...")}).pretty()

# Test evolution over time
db.test_runs.find({test_id: "doctor-patient-es-en"}).sort({finished_at: -1}).limit(10).pretty()

# Score trend over time for a specific test
db.test_runs.find({test_id: "doctor-patient-es-en"}, {finished_at: 1, score: 1, passed: 1}).sort({finished_at: -1})

# Average WER trend
db.evaluation_runs.find({}, {evaluation_run_id: 1, started_at: 1, "metrics.wer": 1}).sort({started_at: -1})

# Evaluation score trend over time
db.evaluation_runs.find({}, {started_at: 1, score: 1, num_passed: 1, num_tests: 1}).sort({started_at: -1})
```

### Using Python

```python
import asyncio
from production.storage import MongoDBClient, MetricsStorageService

async def main():
    # Connect
    client = MongoDBClient("mongodb://localhost:27017", "vt_metrics")
    service = MetricsStorageService(client)

    # Recent evaluation runs
    recent = await service.get_recent_evaluation_runs(limit=10)
    for run in recent:
        print(f"{run['evaluation_run_id']}: {run['status']} ({run['num_passed']}/{run['num_tests']} passed)")

    # Test history
    history = await service.get_test_history("doctor-patient-es-en", limit=20)
    for result in history:
        wer = result['metrics'].get('wer', {}).get('score', 'N/A')
        print(f"{result['finished_at']}: WER = {wer}")

    # Close
    await client.close()

asyncio.run(main())
```

## Use Cases

### 1. Track Performance Over Time

Monitor how metrics evolve across commits:

```bash
# Query: Show average WER per day
db.evaluation_runs.aggregate([
  {$group: {
    _id: {$dateToString: {format: "%Y-%m-%d", date: "$started_at"}},
    avg_wer: {$avg: "$metrics.wer"},
    count: {$sum: 1}
  }},
  {$sort: {_id: -1}}
])

# Query: Track test score over time (for graphing)
db.test_runs.aggregate([
  {$match: {test_id: "doctor-patient-es-en"}},
  {$project: {
    date: {$dateToString: {format: "%Y-%m-%d", date: "$finished_at"}},
    score: 1,
    passed: 1
  }},
  {$sort: {finished_at: 1}}
])

# Query: Average score per test across all runs
db.test_runs.aggregate([
  {$group: {
    _id: "$test_id",
    avg_score: {$avg: "$score"},
    min_score: {$min: "$score"},
    max_score: {$max: "$score"},
    runs: {$sum: 1}
  }},
  {$sort: {avg_score: -1}}
])

# Query: Evaluation score trend over time (for graphing)
db.evaluation_runs.aggregate([
  {$project: {
    date: {$dateToString: {format: "%Y-%m-%d", date: "$started_at"}},
    score: 1,
    num_passed: 1,
    num_tests: 1
  }},
  {$sort: {started_at: 1}}
])
```

### 2. Compare Configurations

Find regressions after config changes:

```bash
# Get runs with different system information hashes
db.evaluation_runs.find({}, {system_info_hash: 1, "metrics.wer": 1, evaluation_run_id: 1})
```

### 3. Identify Flaky Tests

Find tests with inconsistent results:

```bash
# Group test runs by test_id, show pass rate
db.test_runs.aggregate([
  {$group: {
    _id: "$test_id",
    total: {$sum: 1},
    passed: {$sum: {$cond: ["$passed", 1, 0]}},
    pass_rate: {$avg: {$cond: ["$passed", 1, 0]}}
  }},
  {$match: {pass_rate: {$gt: 0, $lt: 1}}},
  {$sort: {pass_rate: 1}}
])
```

### 4. Filter by Experiment

Compare baseline vs experimental runs:

```python
# Baseline runs
baseline = await service.get_evaluation_runs_by_tags(["baseline"])

# Experimental runs
experimental = await service.get_evaluation_runs_by_tags(["config-tweak"])
```

## Architecture

### Data Flow

```
User runs CLI
    ↓
CLI creates EvaluationRun document
    ↓
For each test:
    ScenarioEngine executes test
    → MetricsRunner calculates metrics
    → MetricsRunner saves TestRun document
    ↓
CLI finalizes EvaluationRun with aggregated metrics
```

### Key Components

- **MongoDBClient** (`client.py`): Async MongoDB connection and index management
- **Models** (`models.py`): Data models for EvaluationRun, TestRun, MetricData
- **MetricsStorageService** (`service.py`): CRUD operations and queries
- **FrameworkConfig** (`utils/config.py`): Centralized configuration
- **Utilities** (`utils.py`): System info hashing, git info, evaluation/test run ID generation

## Troubleshooting

### Storage Not Enabled

**Symptom**: Logs show "Storage disabled (MONGODB_ENABLED=false)"

**Solution**: Set `MONGODB_ENABLED=true` in `.env`

### Connection Failed

**Symptom**: "Failed to connect to MongoDB"

**Solutions**:
- Verify MongoDB is running: `brew services list` or `systemctl status mongodb`
- Check connection string: `mongodb://localhost:27017`
- Test connection: `mongosh mongodb://localhost:27017`

### Git Info Not Captured

**Symptom**: `git_commit` and `git_branch` are `null` in evaluation runs

**Solutions**:
- Ensure GitPython is installed: `poetry install --with evaluations`
- Run from within a git repository
- Check git status: `git status`

### Missing Indexes

**Symptom**: Slow queries

**Solution**: Indexes are created automatically on first connection. To recreate:

```python
client = MongoDBClient("mongodb://localhost:27017", "vt_metrics")
await client.create_indexes()
```

## Best Practices

### 1. Use Experiment Tags

Tag runs for easy comparison:

```bash
# Baseline
export EXPERIMENT_TAGS=baseline
poetry run prod run-suite production/scenarios/

# After config change
export EXPERIMENT_TAGS=config-tweak,latency-optimization
poetry run prod run-suite production/scenarios/
```

### 2. Set Environment Correctly

Separate dev, stage, and prod data:

```bash
export ENVIRONMENT=prod
export MONGODB_DATABASE=vt_metrics_prod
```

### 3. Monitor Aggregated Metrics

Focus on evaluation-level trends first, then drill into individual tests:

```bash
# Evaluation-level: Quick overview
db.evaluation_runs.find().sort({started_at: -1}).limit(10)

# Test-level: Detailed analysis
db.test_runs.find({test_id: "problem-test"})
```

### 4. Archive Old Data

Set up retention policies for old evaluation runs (optional):

```bash
# Delete evaluation runs older than 90 days
db.evaluation_runs.deleteMany({
  started_at: {$lt: new Date(Date.now() - 90*24*60*60*1000)}
})
```

## Next Steps

- **Phase 2**: Web UI for visualizing metrics and trends
- **Prometheus Export**: Expose metrics for Grafana dashboards
- **Automated Alerts**: Detect regressions and notify team
- **Comparison Views**: Side-by-side comparison of evaluation runs

## Support

For issues or questions:
- Check implementation plan: `production/METRICS_STORAGE_IMPLEMENTATION_PLAN.md`
- Review specification: `production/test-metrics-storage-high-level-design.md`
- MongoDB documentation: https://docs.mongodb.com/

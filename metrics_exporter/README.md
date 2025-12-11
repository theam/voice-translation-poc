# Metrics Exporter

A standalone Prometheus exporter that surfaces evaluation and test metrics stored in MongoDB. It relies on the existing evaluation data model and does not mutate the database.

## Configuration
Set the following environment variables before running:

- `MONGO_URI` (required) – MongoDB connection string.
- `MONGO_DB_NAME` (required) – Database containing the evaluation collections.
- `MONGO_EVALUATION_RUNS_COLLECTION` – Collection name for evaluation runs (default: `evaluation_runs`).
- `MONGO_TEST_RUNS_COLLECTION` – Collection name for test runs (default: `test_runs`).
- `EXPORTER_PORT` – Port to expose the metrics endpoint (default: `9100`).
- `LOOKBACK_DAYS` – Number of days of history to include in scrapes (default: `7`).

## Running locally

Install dependencies directly from the exporter folder:

```bash
pip install -r metrics_exporter/requirements.txt
```

```bash
python -m metrics_exporter.main
```

Prometheus-formatted metrics will be available on `http://localhost:$EXPORTER_PORT/metrics`.

## Docker

A standalone container image can be built from within the `metrics_exporter` directory:

```bash
cd metrics_exporter
make build
```

To run the image and expose the metrics endpoint (pass your Mongo configuration via environment variables or `RUN_FLAGS`):

```bash
make run RUN_FLAGS="--env MONGO_URI=... --env MONGO_DB_NAME=..."
```

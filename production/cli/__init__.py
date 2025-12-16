"""Command-line interface for the production ACS testing framework."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer

from production.cli.calibrate import calibrate_async
from production.cli.generate_report import generate_report_async
from production.cli.run_test import run_test_async
from production.cli.run_suite import run_suite_async
from production.cli.reset_db import reset_db_async
from production.cli.run_parallel import app as parallel_app

app = typer.Typer(help="ACS Live Translation production-grade test harness")

# Add parallel command group
app.add_typer(parallel_app, name="parallel", help="Run tests in parallel to simulate multiple users")


@app.command("run-test")
def run_test(
    scenario_path: Path,
    log_level: str = typer.Option("INFO", help="Logging level")
) -> None:
    """Run a single scenario file with optional storage."""
    asyncio.run(run_test_async(scenario_path, log_level))


@app.command("run-suite")
def run_suite(
    folder: Path,
    pattern: str = typer.Option("*.yaml", help="Glob for scenario files"),
    log_level: str = "INFO"
) -> None:
    """Run all scenarios within a folder with optional storage."""
    asyncio.run(run_suite_async(folder, pattern, log_level))


@app.command("reset-db")
def reset_db(
    log_level: str = typer.Option("INFO", help="Logging level"),
    confirm: bool = typer.Option(
        False,
        "--confirm",
        help="Skip confirmation prompt (use with caution)"
    )
) -> None:
    """Reset MongoDB database by dropping all collections and recreating indexes.

    WARNING: This permanently deletes all evaluation runs and test results.
    Use only in development/testing when schema changes require a clean slate.
    """
    asyncio.run(reset_db_async(log_level, confirm))


@app.command("calibrate")
def calibrate(
    file: Optional[Path] = typer.Option(
        None,
        "--file",
        "-f",
        help="Path to specific calibration scenario YAML file"
    ),
    directory: Path = typer.Option(
        Path("production/tests/calibration"),
        "--dir",
        "-d",
        help="Directory containing calibration scenarios"
    ),
    pattern: str = typer.Option(
        "**/*.yaml",
        "--pattern",
        "-p",
        help="Glob pattern for calibration scenarios (recursive by default)"
    ),
    metric: Optional[str] = typer.Option(
        None,
        "--metric",
        "-m",
        help="Filter by metric/tag name (e.g., intelligibility, context)"
    ),
    store: bool = typer.Option(
        False,
        "--store",
        "-s",
        help="Force-enable MongoDB storage for this run"
    ),
    log_level: str = "INFO",
) -> None:
    """Run calibration scenarios using the standard scenario engine."""
    asyncio.run(calibrate_async(
        file=file,
        directory=directory,
        pattern=pattern,
        metric=metric,
        store=store,
        log_level=log_level
    ))


@app.command("generate-report")
def generate_report(
    evaluation_run_id: str = typer.Argument(
        ...,
        help="MongoDB ObjectId of the evaluation run (24-char hex string)"
    ),
    log_level: str = typer.Option("INFO", help="Logging level")
) -> None:
    """Generate PDF report for an existing evaluation run.

    The evaluation_run_id is the MongoDB ObjectId (_id field) from the
    evaluation_runs collection. You can find it by running MongoDB queries
    or checking the logs from previous test runs.

    Example:
        poetry run prod generate-report 507f1f77bcf86cd799439011
    """
    asyncio.run(generate_report_async(evaluation_run_id, log_level))


__all__ = ["app"]

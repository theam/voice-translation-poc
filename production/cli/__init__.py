"""Command-line interface for the production ACS testing framework."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer

from production.cli.calibrate import calibrate_async
from production.cli.run_test import run_test_async
from production.cli.run_suite import run_suite_async
from production.cli.reset_db import reset_db_async

app = typer.Typer(help="ACS Live Translation production-grade test harness")


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
    file: Optional[str] = typer.Option(
        None,
        "--file",
        "-f",
        help="Path to specific calibration YAML file"
    ),
    directory: str = typer.Option(
        "production/tests/calibration",
        "--dir",
        "-d",
        help="Directory containing calibration files"
    ),
    metric: Optional[str] = typer.Option(
        None,
        "--metric",
        "-m",
        help="Filter by metric name (e.g., intelligibility, context)"
    ),
    tolerance: float = typer.Option(
        0.5,
        "--tolerance",
        "-t",
        help="Acceptable score difference (default: 0.5 on 1-5 scale)"
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output report file (.json or .md)"
    ),
    show_passed: bool = typer.Option(
        True,
        "--show-passed/--hide-passed",
        help="Show passed test cases in detailed output"
    ),
    show_failed: bool = typer.Option(
        True,
        "--show-failed/--hide-failed",
        help="Show failed test cases in detailed output"
    ),
    store: bool = typer.Option(
        False,
        "--store",
        "-s",
        help="Store calibration results to MongoDB"
    ),
) -> None:
    """Run metric calibration tests.

    Validates metric behavior against known expected outcomes.

    Examples:

        # Run all calibrations
        python -m production.cli calibrate

        # Run specific file
        python -m production.cli calibrate -f production/tests/calibration/intelligibility_samples.yaml

        # Run only intelligibility calibrations
        python -m production.cli calibrate --metric intelligibility

        # Custom tolerance
        python -m production.cli calibrate --tolerance 0.3

        # Generate reports
        python -m production.cli calibrate --output reports/calibration.json
        python -m production.cli calibrate --output reports/calibration.md

        # Store results to MongoDB
        python -m production.cli calibrate --store
    """
    asyncio.run(calibrate_async(
        file=file,
        directory=directory,
        metric=metric,
        tolerance=tolerance,
        output=output,
        show_passed=show_passed,
        show_failed=show_failed,
        store=store
    ))


__all__ = ["app"]

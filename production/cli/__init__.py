"""Command-line interface for the production ACS testing framework."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer

from production.cli.calibrate import calibrate_async
from production.cli.generate_report import generate_report_async
from production.cli.replay import replay_async
from production.cli.export_audio import export_audio_async, export_audio_batch_async
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


@app.command("replay")
def replay(
    wire_log_path: Path = typer.Argument(..., help="Path to wire log JSONL file"),
    log_level: str = typer.Option("INFO", help="Logging level"),
    store: bool = typer.Option(
        False,
        "--store",
        "-s",
        help="Force-enable MongoDB storage for this run"
    ),
) -> None:
    """Replay a wire log file with exact timing preservation.

    Loads wire log as a Scenario with a single turn at 0ms, ensuring
    no silence is added. Results are logged and optionally stored in MongoDB.

    Example:
        poetry run prod replay artifacts/websocket_wire/acs_server_UUID.jsonl
    """
    asyncio.run(replay_async(
        wire_log_path=wire_log_path,
        log_level=log_level,
        store=store
    ))


@app.command("export-audio")
def export_audio(
    wire_log_path: Path = typer.Argument(..., help="Path to wire log JSONL file"),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output WAV file path (defaults to wire_log_path.wav)"
    ),
    direction: str = typer.Option(
        "all",
        "--direction",
        "-d",
        help="Audio direction to export: inbound, outbound, or all",
    ),
) -> None:
    """Export wire log audio to WAV file.

    Extracts all inbound and outbound audio from the wire log and merges them
    chronologically into a single WAV file, mixing overlapping audio as it would
    sound in a telephone call.

    Example:
        poetry run prod export-audio logs/server/acs_server_UUID.jsonl
        poetry run prod export-audio logs/server/acs_server_UUID.jsonl -o output.wav
    """
    direction = direction.lower()
    if direction not in {"inbound", "outbound", "all"}:
        raise typer.BadParameter("direction must be one of: inbound, outbound, all")

    if wire_log_path.is_dir():
        asyncio.run(export_audio_batch_async(
            wire_log_dir=wire_log_path,
            output_dir=output,
            direction=direction,
        ))
    else:
        asyncio.run(export_audio_async(
            wire_log_path=wire_log_path,
            output_path=output,
            direction=direction,
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

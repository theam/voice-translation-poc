"""Calibration command for metrics validation."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from production.calibration import (
    CalibrationLoader,
    CalibrationReporter,
    CalibrationRunner,
)
from production.storage.client import MongoDBClient
from production.storage.service import MetricsStorageService
from production.utils.config import load_config


console = Console()


async def calibrate_async(
    file: Optional[str],
    directory: str,
    metric: Optional[str],
    tolerance: float,
    output: Optional[str],
    show_passed: bool,
    show_failed: bool,
    store: bool = False,
):
    """Run metric calibration tests (async implementation).

    Args:
        file: Path to specific calibration YAML file
        directory: Directory containing calibration files
        metric: Filter by metric name
        tolerance: Acceptable score difference
        output: Output report file (.json or .md)
        show_passed: Show passed test cases
        show_failed: Show failed test cases
        store: Store results to MongoDB
    """
    try:
        console.print("\n[bold blue]🔬 Starting Calibration[/bold blue]\n")

        # Initialize components
        loader = CalibrationLoader()
        runner = CalibrationRunner(tolerance=tolerance)
        reporter = CalibrationReporter()

        # Load calibration configs
        if file:
            console.print(f"Loading file: {file}")
            configs = [loader.load_file(Path(file))]
        else:
            console.print(f"Loading directory: {directory}")
            configs = loader.load_directory(Path(directory))

        if not configs:
            console.print("[red]No calibration files found![/red]")
            raise typer.Exit(1)

        # Filter by metric if specified
        if metric:
            configs = [c for c in configs if c.metric == metric or c.metric == "all"]
            if not configs:
                console.print(f"[red]No calibration files found for metric: {metric}[/red]")
                raise typer.Exit(1)
            console.print(f"Filtered to metric: {metric}")

        console.print(f"Found {len(configs)} calibration config(s)\n")

        # Initialize storage if requested
        storage_service = None
        if store:
            console.print("[cyan]📦 MongoDB storage enabled[/cyan]")
            config = load_config()
            mongo_client = MongoDBClient(
                connection_string=config.storage_connection_string,
                database=config.storage_database
            )
            storage_service = MetricsStorageService(mongo_client)

            # Test connection
            if not await mongo_client.ping():
                console.print("[red]❌ MongoDB connection failed![/red]")
                raise typer.Exit(1)
            console.print("[green]✓ MongoDB connected[/green]\n")

        # Get git info for provenance
        git_commit = None
        git_branch = None
        if store:
            try:
                git_commit = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"],
                    stderr=subprocess.DEVNULL
                ).decode().strip()
                git_branch = subprocess.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    stderr=subprocess.DEVNULL
                ).decode().strip()
            except Exception:
                console.print("[yellow]⚠️  Could not get git info[/yellow]")

        # Run calibrations
        all_summaries = []
        all_configs = []
        for config in configs:
            console.print(f"[bold]Running: {config.id}[/bold]")

            # Track timing
            started_at = datetime.utcnow()
            summary = runner.run_calibration(config)
            finished_at = datetime.utcnow()

            all_summaries.append(summary)
            all_configs.append((config, started_at, finished_at))

            # Print results
            reporter.print_summary(summary)
            reporter.print_detailed_results(
                summary,
                show_passed=show_passed,
                show_failed=show_failed
            )

            # Store to MongoDB if enabled
            if storage_service:
                calibration_run = CalibrationRunner.create_calibration_run(
                    summary=summary,
                    config=config,
                    started_at=started_at,
                    finished_at=finished_at,
                    git_commit=git_commit,
                    git_branch=git_branch
                )

                run_id = await storage_service.create_calibration_run(calibration_run)
                console.print(f"[green]💾 Stored to MongoDB (ID: {run_id})[/green]\n")

        # Generate output file if specified
        if output:
            output_path = Path(output)

            # Determine format from extension
            if output_path.suffix == ".json":
                # Save each summary separately or combined
                if len(all_summaries) == 1:
                    reporter.generate_json_report(all_summaries[0], output_path)
                else:
                    # Save combined report
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    combined_data = {
                        "calibrations": [s.to_dict() for s in all_summaries],
                        "total_configs": len(all_summaries),
                        "overall_accuracy": sum(s.accuracy for s in all_summaries) / len(all_summaries)
                    }
                    with open(output_path, "w") as f:
                        json.dump(combined_data, f, indent=2)
                    console.print(f"\n[green]📄 JSON report saved to: {output_path}[/green]")

            elif output_path.suffix in [".md", ".markdown"]:
                # Save markdown report
                if len(all_summaries) == 1:
                    reporter.generate_markdown_report(all_summaries[0], output_path)
                else:
                    # Save combined markdown
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    lines = ["# Calibration Report - Combined Results\n"]
                    for summary in all_summaries:
                        lines.append(f"## {summary.config_id}\n")
                        lines.append(f"**Accuracy:** {summary.accuracy:.1%}\n")
                        lines.append(f"**Passed:** {summary.passed_cases}/{summary.total_cases}\n")
                        lines.append("---\n")
                    with open(output_path, "w") as f:
                        f.write("\n".join(lines))
                    console.print(f"\n[green]📄 Markdown report saved to: {output_path}[/green]")
            else:
                console.print(f"[yellow]⚠️  Unknown output format: {output_path.suffix}[/yellow]")
                console.print("Supported formats: .json, .md")

        # Summary
        console.print("\n[bold green]✅ Calibration Complete![/bold green]\n")

        # Exit with error code if any calibrations failed
        if any(s.accuracy < 1.0 for s in all_summaries):
            console.print("[yellow]⚠️  Some calibration cases failed[/yellow]")
            raise typer.Exit(1)
        else:
            console.print("[green]✓ All calibration cases passed[/green]")

    except Exception as e:
        console.print(f"\n[red]❌ Error: {e}[/red]\n")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


__all__ = ["calibrate_async"]

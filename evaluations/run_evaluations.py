#!/usr/bin/env python3
"""
Unified evaluation script that runs test cases, collects Azure responses,
calculates metrics, and generates PDF reports.

Usage:
    python run_evaluations.py
    python run_evaluations.py --test-cases evaluations/test_cases.yaml
    poetry run run-evaluations
    poetry run run-evaluations --verbose
"""

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    # Load .env from project root (one level up from evaluations/)
    project_root = Path(__file__).parent.parent
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✓ Loaded environment from: {env_path}")
    else:
        print(f"⚠ No .env file found at: {env_path}")
except ImportError:
    print("⚠ python-dotenv not installed, skipping .env loading")

try:
    import websockets
    from websockets.client import connect
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

# Add evaluations directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from audio_handler import DEFAULT_CHUNK_DURATION_MS
from metrics import get_all_metrics
from metrics_calculator import calculate_metrics, calculate_summary, print_summary
from models import TestConfig, TestReport
from report_generator import generate_pdf_report
from test_runner import run_test_case


DEFAULT_TEST_CASES_FILE = "evaluations/test_cases.yaml"


async def run_evaluations(yaml_path: Path, case_id: str = None, verbose: bool = False) -> int:
    """
    Run test cases from YAML configuration.

    Args:
        yaml_path: Path to YAML configuration file
        case_id: Optional test case ID to run exclusively. If provided, only that
                test case will run (regardless of enabled status). If None, all
                enabled test cases will run.
        verbose: Print verbose output including Azure responses

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    if not WEBSOCKETS_AVAILABLE:
        print("Error: websockets library not available")
        print("Install with: poetry install --with evaluations")
        return 1

    print(f"Loading test cases from: {yaml_path}")

    try:
        config = TestConfig.from_yaml(yaml_path)
    except FileNotFoundError:
        print(f"Error: Test cases file not found: {yaml_path}")
        return 1
    except Exception as e:
        print(f"Error loading test cases: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Filter test cases based on case_id or enabled status
    tests_to_run = [tc for tc in config.test_cases if tc.id == case_id]
    if not tests_to_run:
        tests_to_run = [tc for tc in config.test_cases if tc.enabled]
    print(f"\nTests to run: {len(tests_to_run)} case_id:{case_id}")
    if not tests_to_run:
        print("Warning: No test cases to run")
        return 0

    print(f"Server: {config.server['host']}:{config.server['port']}")
    print(f"Defaults: {config.defaults}")

    # Get configuration
    host = config.server.get("host", "localhost")
    port = config.server.get("port", 8080)
    chunk_duration_ms = config.defaults.get("chunk_duration_ms", DEFAULT_CHUNK_DURATION_MS)

    # Build WebSocket URL
    ws_url = f"ws://{host}:{port}"
    print(f"\nConnecting to {ws_url}...")

    try:
        # Track execution time
        start_time = time.time()

        # Create report
        report = TestReport(timestamp=datetime.now())
        report.test_cases = tests_to_run

        # Get all metrics (auto-discovered) for use in individual test calculations
        all_metrics = get_all_metrics()

        # Run all test cases with fresh WebSocket connection for each
        for test_case in tests_to_run:
            print(f"\n{'='*80}")
            print(f"Connecting to WebSocket for test: {test_case.id}")
            print(f"{'='*80}")

            async with connect(ws_url) as websocket:
                print(f"✓ Connected successfully!\n")

                test_result = await run_test_case(
                    test_case,
                    websocket,
                    chunk_duration_ms,
                    verbose=verbose
                )
                report.test_results[test_case.id] = test_result

            print(f"✓ Disconnected after test: {test_case.id}\n")

            # Calculate metrics immediately after each test
            test_metrics = calculate_metrics({test_case.id: test_result})
            report.metric_results.update(test_metrics)

            # Print individual test metrics
            print(f"\n--- Metrics for {test_case.id} ---")
            for metric_name, metric_value in test_metrics.get(test_case.id, {}).items():
                print(f"  {metric_name}: {metric_value}")
            print()

        # Calculate execution time
        execution_time = time.time() - start_time

        # Calculate summary after all tests complete
        report.summary = calculate_summary(report, all_metrics)
        report.summary['execution_time_seconds'] = execution_time

        # Print final summary
        print_summary(report)

        # Generate PDF report
        eval_dir = yaml_path.parent
        project_root = eval_dir.parent
        output_dir = project_root / "reports"
        output_dir.mkdir(exist_ok=True)

        pdf_path = output_dir / f"evaluation_report_{report.timestamp.strftime('%Y%m%d_%H%M%S')}.pdf"

        # Convert TestResult to format expected by report generator
        class LegacyTestCase:
            def __init__(self, test_case, test_result):
                self.id = test_case.id
                self.name = test_case.name
                self.input_audio = test_case.audio_file
                self.expected_text = test_case.expected_text
                self.mock_received_data = {
                    "success": test_result.success,
                    "recognized_text": test_result.recognized_text,
                    "translations": test_result.translations,
                    "response_time_ms": test_result.response_time_ms,
                    "chunks_sent": test_result.chunks_sent,
                    "chunks_received": len(test_result.azure_responses),
                    "error_details": test_result.error_details
                }

        # Create legacy report format
        class LegacyReport:
            def __init__(self):
                self.timestamp = report.timestamp
                self.test_cases = [
                    LegacyTestCase(tc, report.test_results[tc.id])
                    for tc in report.test_cases
                ]
                self.results = report.metric_results
                self.metric_results = report.metric_results
                self.test_results = report.test_results
                self.summary = report.summary

        legacy_report = LegacyReport()
        generate_pdf_report(legacy_report, pdf_path)

        print(f"✓ PDF report generated: {pdf_path}")

        # Determine exit code based on failures
        failed_tests = sum(1 for result in report.test_results.values() if not result.success)
        return 0 if failed_tests == 0 else 1

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Run evaluation tests with Azure translation via WebSocket"
    )
    parser.add_argument(
        "--path",
        type=Path,
        help=f"Path to YAML test cases file (default: {DEFAULT_TEST_CASES_FILE})"
    )
    parser.add_argument(
        "--test-case",
        type=str,
        help="Test case ID to run exclusively (e.g., tc001). If provided, only this test case will run, ignoring enabled status."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print verbose output including Azure responses"
    )

    args = parser.parse_args()

    yaml_path = args.path or Path(DEFAULT_TEST_CASES_FILE)
    return asyncio.run(run_evaluations(yaml_path, args.test_case, verbose=args.verbose))


if __name__ == "__main__":
    sys.exit(main())

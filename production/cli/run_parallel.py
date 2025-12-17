"""Run tests in parallel for simulating multiple users."""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import typer

logger = logging.getLogger(__name__)


class TestResult:
    """Result of a single test execution."""

    def __init__(self, test_path: str, returncode: int, duration: float):
        self.test_path = test_path
        self.returncode = returncode
        self.duration = duration
        self.success = returncode == 0


async def run_single_test(
    test_path: Path,
    log_level: str,
    semaphore: Optional[asyncio.Semaphore] = None
) -> TestResult:
    """Run a single test scenario.

    Args:
        test_path: Path to scenario YAML file
        log_level: Logging level to pass to test
        semaphore: Optional semaphore to limit concurrent executions

    Returns:
        TestResult with execution details
    """
    # Use semaphore context if provided, otherwise run immediately
    if semaphore:
        async with semaphore:
            return await _run_test_impl(test_path, log_level)
    else:
        return await _run_test_impl(test_path, log_level)


async def _run_test_impl(test_path: Path, log_level: str) -> TestResult:
    """Internal implementation of test execution.

    Args:
        test_path: Path to scenario YAML file
        log_level: Logging level to pass to test

    Returns:
        TestResult with execution details
    """
    start_time = datetime.now()

    logger.info(f"Starting test: {test_path}")

    # Run test using poetry run prod run-test
    process = await asyncio.create_subprocess_exec(
        "poetry", "run", "prod", "run-test", str(test_path),
        "--log-level", log_level,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    duration = (datetime.now() - start_time).total_seconds()

    # Log output
    if stdout:
        logger.debug(f"[{test_path.name}] STDOUT:\n{stdout.decode()}")
    if stderr:
        logger.debug(f"[{test_path.name}] STDERR:\n{stderr.decode()}")

    result = TestResult(str(test_path), process.returncode, duration)

    status = "✓" if result.success else "✗"
    logger.info(
        f"{status} Test {test_path.name} completed in {duration:.2f}s "
        f"(exit code: {process.returncode})"
    )

    return result


async def run_single_suite(
    suite_path: Path,
    pattern: str,
    log_level: str,
    semaphore: Optional[asyncio.Semaphore] = None
) -> TestResult:
    """Run a single test suite.

    Args:
        suite_path: Path to suite folder
        pattern: Glob pattern for scenario files
        log_level: Logging level to pass to suite
        semaphore: Optional semaphore to limit concurrent executions

    Returns:
        TestResult with execution details
    """
    # Use semaphore context if provided, otherwise run immediately
    if semaphore:
        async with semaphore:
            return await _run_suite_impl(suite_path, pattern, log_level)
    else:
        return await _run_suite_impl(suite_path, pattern, log_level)


async def _run_suite_impl(suite_path: Path, pattern: str, log_level: str) -> TestResult:
    """Internal implementation of suite execution.

    Args:
        suite_path: Path to suite folder
        pattern: Glob pattern for scenario files
        log_level: Logging level to pass to suite

    Returns:
        TestResult with execution details
    """
    start_time = datetime.now()

    logger.info(f"Starting suite: {suite_path}")

    # Run suite using poetry run prod run-suite
    process = await asyncio.create_subprocess_exec(
        "poetry", "run", "prod", "run-suite", str(suite_path),
        "--pattern", pattern,
        "--log-level", log_level,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    duration = (datetime.now() - start_time).total_seconds()

    # Log output
    if stdout:
        logger.debug(f"[{suite_path.name}] STDOUT:\n{stdout.decode()}")
    if stderr:
        logger.debug(f"[{suite_path.name}] STDERR:\n{stderr.decode()}")

    result = TestResult(str(suite_path), process.returncode, duration)

    status = "✓" if result.success else "✗"
    logger.info(
        f"{status} Suite {suite_path.name} completed in {duration:.2f}s "
        f"(exit code: {process.returncode})"
    )

    return result


def discover_test_files(
    base_path: Path,
    pattern: str = "*.yaml"
) -> List[Path]:
    """Discover test scenario files.

    Args:
        base_path: Base directory to search
        pattern: Glob pattern for test files

    Returns:
        List of test file paths
    """
    if not base_path.exists():
        logger.error(f"Path does not exist: {base_path}")
        return []

    if base_path.is_file():
        return [base_path]

    # Use rglob for recursive search if pattern contains **
    if "**" in pattern:
        files = list(base_path.glob(pattern))
    else:
        files = list(base_path.rglob(pattern))

    files.sort()
    logger.info(f"Discovered {len(files)} test files")
    return files


async def run_parallel_tests_async(
    test_paths: List[Path],
    parallel_jobs: int,
    log_level: str
) -> List[TestResult]:
    """Run multiple tests in parallel.

    Args:
        test_paths: List of test file paths
        parallel_jobs: Number of parallel jobs to run
        log_level: Logging level for tests

    Returns:
        List of TestResults
    """
    if not test_paths:
        logger.warning("No tests to run")
        return []

    logger.info(
        f"Running {len(test_paths)} tests with {parallel_jobs} parallel jobs"
    )

    # Create semaphore to limit concurrency
    semaphore = asyncio.Semaphore(parallel_jobs)

    # Create tasks for all tests
    tasks = [
        run_single_test(test_path, log_level, semaphore)
        for test_path in test_paths
    ]

    # Run all tasks concurrently
    start_time = datetime.now()
    results = await asyncio.gather(*tasks)
    total_duration = (datetime.now() - start_time).total_seconds()

    # Print summary
    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful

    print("\n" + "=" * 80)
    print("PARALLEL TEST RUN SUMMARY")
    print("=" * 80)
    print(f"Total tests:     {len(results)}")
    print(f"Successful:      {successful}")
    print(f"Failed:          {failed}")
    print(f"Parallel jobs:   {parallel_jobs}")
    print(f"Total duration:  {total_duration:.2f}s")
    print(f"Avg per test:    {total_duration / len(results):.2f}s")
    print("=" * 80)

    if failed > 0:
        print("\nFailed tests:")
        for result in results:
            if not result.success:
                print(f"  ✗ {result.test_path} (exit code: {result.returncode})")

    return results


async def run_parallel_suites_async(
    suite_count: int,
    suite_path: Path,
    pattern: str,
    log_level: str
) -> List[TestResult]:
    """Run the same test suite N times in parallel.

    Args:
        suite_count: Number of times to run the suite in parallel
        suite_path: Path to suite folder
        pattern: Glob pattern for scenario files
        log_level: Logging level for suites

    Returns:
        List of TestResults
    """
    logger.info(
        f"Running suite {suite_count} times in parallel"
    )

    # Create semaphore (all suites run in parallel)
    semaphore = asyncio.Semaphore(suite_count)

    # Create tasks for all suite runs
    tasks = [
        run_single_suite(suite_path, pattern, log_level, semaphore)
        for _ in range(suite_count)
    ]

    # Run all tasks concurrently
    start_time = datetime.now()
    results = await asyncio.gather(*tasks)
    total_duration = (datetime.now() - start_time).total_seconds()

    # Print summary
    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful

    print("\n" + "=" * 80)
    print("PARALLEL SUITE RUN SUMMARY")
    print("=" * 80)
    print(f"Suite runs:      {len(results)}")
    print(f"Successful:      {successful}")
    print(f"Failed:          {failed}")
    print(f"Total duration:  {total_duration:.2f}s")
    print(f"Avg per run:     {total_duration / len(results):.2f}s")
    print("=" * 80)

    return results


app = typer.Typer(help="Run tests in parallel to simulate multiple users")


@app.command("tests")
def run_parallel_tests(
    path: Path = typer.Argument(
        ...,
        help="Path to test directory or specific test file"
    ),
    parallel_jobs: int = typer.Option(
        4,
        "--jobs", "-j",
        help="Number of parallel jobs"
    ),
    pattern: str = typer.Option(
        "*.yaml",
        "--pattern", "-p",
        help="Glob pattern for test files"
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        help="Logging level for tests"
    )
) -> None:
    """Run individual tests in parallel.

    Examples:
        # Run all tests in a directory with 4 parallel jobs
        poetry run prod parallel tests production/tests/scenarios/ -j 4

        # Run specific pattern with 8 parallel jobs
        poetry run prod parallel tests production/tests/scenarios/ -p "**/*.yaml" -j 8
    """
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Discover tests
    test_paths = discover_test_files(path, pattern)

    if not test_paths:
        print(f"No tests found at {path} with pattern {pattern}")
        sys.exit(1)

    # Run tests
    results = asyncio.run(run_parallel_tests_async(
        test_paths, parallel_jobs, log_level
    ))

    # Exit with error if any tests failed
    if any(not r.success for r in results):
        sys.exit(1)


@app.command("suites")
def run_parallel_suites(
    path: Path = typer.Argument(
        Path("production/tests/scenarios/"),
        help="Path to suite directory"
    ),
    count: int = typer.Option(
        4,
        "--count", "-n",
        help="Number of times to run the suite in parallel"
    ),
    pattern: str = typer.Option(
        "*.yaml",
        "--pattern", "-p",
        help="Glob pattern for scenario files in suite"
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        help="Logging level for suites"
    )
) -> None:
    """Run the same test suite N times in parallel.

    This simulates N users each running the full test suite concurrently.

    Examples:
        # Run suite 4 times in parallel
        poetry run prod parallel suites production/tests/scenarios/ -n 4

        # Run suite 8 times with custom pattern
        poetry run prod parallel suites production/tests/scenarios/ -n 8 -p "allergy*.yaml"
    """
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    if not path.exists():
        print(f"Suite path does not exist: {path}")
        sys.exit(1)

    # Run suites
    results = asyncio.run(run_parallel_suites_async(
        count, path, pattern, log_level
    ))

    # Exit with error if any suite runs failed
    if any(not r.success for r in results):
        sys.exit(1)


@app.command("simulate-test")
def simulate_concurrent_test(
    test_path: Path = typer.Argument(
        ...,
        help="Path to test scenario file"
    ),
    users: int = typer.Option(
        4,
        "--users", "-u",
        help="Number of concurrent users to simulate"
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        help="Logging level for tests"
    )
) -> None:
    """Simulate N users all running the SAME test simultaneously.

    All users start at exactly the same time to simulate a load spike.
    No concurrency limiting - all N users run in parallel.

    Examples:
        # Simulate 10 users running the same test
        poetry run prod parallel simulate-test production/tests/scenarios/allergy_ceph.yaml -u 10

        # Simulate 20 concurrent users
        poetry run prod parallel simulate-test production/tests/scenarios/allergy_ceph.yaml -u 20
    """
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    if not test_path.exists():
        print(f"Test file does not exist: {test_path}")
        sys.exit(1)

    print(f"\n{'=' * 80}")
    print(f"SIMULATING {users} CONCURRENT USERS")
    print(f"Test: {test_path.name}")
    print(f"All users will start simultaneously (no concurrency limit)")
    print(f"{'=' * 80}\n")

    # Run simulation
    results = asyncio.run(_simulate_test_async(test_path, users, log_level))

    # Exit with error if any tests failed
    if any(not r.success for r in results):
        sys.exit(1)


@app.command("simulate-suite")
def simulate_concurrent_suite(
    suite_path: Path = typer.Argument(
        Path("production/tests/scenarios/"),
        help="Path to suite directory"
    ),
    users: int = typer.Option(
        4,
        "--users", "-u",
        help="Number of concurrent users to simulate"
    ),
    pattern: str = typer.Option(
        "*.yaml",
        "--pattern", "-p",
        help="Glob pattern for scenario files in suite"
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        help="Logging level for suites"
    )
) -> None:
    """Simulate N users all running the SAME suite simultaneously.

    All users start at exactly the same time to simulate a load spike.
    No concurrency limiting - all N users run in parallel.

    Examples:
        # Simulate 5 users running the same suite
        poetry run prod parallel simulate-suite production/tests/scenarios/ -u 5

        # Simulate 10 users with filtered tests
        poetry run prod parallel simulate-suite production/tests/scenarios/ -u 10 -p "allergy*.yaml"
    """
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    if not suite_path.exists():
        print(f"Suite path does not exist: {suite_path}")
        sys.exit(1)

    print(f"\n{'=' * 80}")
    print(f"SIMULATING {users} CONCURRENT USERS")
    print(f"Suite: {suite_path}")
    print(f"Pattern: {pattern}")
    print(f"All users will start simultaneously (no concurrency limit)")
    print(f"{'=' * 80}\n")

    # Run simulation
    results = asyncio.run(_simulate_suite_async(suite_path, users, pattern, log_level))

    # Exit with error if any suite runs failed
    if any(not r.success for r in results):
        sys.exit(1)


async def _simulate_test_async(
    test_path: Path,
    user_count: int,
    log_level: str
) -> List[TestResult]:
    """Simulate multiple users running the same test simultaneously.

    Args:
        test_path: Path to test scenario file
        user_count: Number of concurrent users
        log_level: Logging level for tests

    Returns:
        List of TestResults
    """
    logger.info(f"Simulating {user_count} users running {test_path}")

    # Create tasks for all users - NO SEMAPHORE (all start simultaneously)
    tasks = [
        run_single_test(test_path, log_level, semaphore=None)
        for _ in range(user_count)
    ]

    # Run all tasks concurrently - all start at the same time
    start_time = datetime.now()
    results = await asyncio.gather(*tasks)
    total_duration = (datetime.now() - start_time).total_seconds()

    # Print summary
    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful

    print("\n" + "=" * 80)
    print("CONCURRENT USER SIMULATION SUMMARY")
    print("=" * 80)
    print(f"Test:            {test_path.name}")
    print(f"Concurrent users: {user_count}")
    print(f"Successful:      {successful}")
    print(f"Failed:          {failed}")
    print(f"Total duration:  {total_duration:.2f}s")
    print(f"Avg per user:    {sum(r.duration for r in results) / len(results):.2f}s")
    print(f"Min duration:    {min(r.duration for r in results):.2f}s")
    print(f"Max duration:    {max(r.duration for r in results):.2f}s")
    print("=" * 80)

    if failed > 0:
        print("\n⚠️  Some users experienced failures")

    return results


async def _simulate_suite_async(
    suite_path: Path,
    user_count: int,
    pattern: str,
    log_level: str
) -> List[TestResult]:
    """Simulate multiple users running the same suite simultaneously.

    Args:
        suite_path: Path to suite folder
        user_count: Number of concurrent users
        pattern: Glob pattern for scenario files
        log_level: Logging level for suites

    Returns:
        List of TestResults
    """
    logger.info(f"Simulating {user_count} users running suite at {suite_path}")

    # Create tasks for all users - NO SEMAPHORE (all start simultaneously)
    tasks = [
        run_single_suite(suite_path, pattern, log_level, semaphore=None)
        for _ in range(user_count)
    ]

    # Run all tasks concurrently - all start at the same time
    start_time = datetime.now()
    results = await asyncio.gather(*tasks)
    total_duration = (datetime.now() - start_time).total_seconds()

    # Print summary
    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful

    print("\n" + "=" * 80)
    print("CONCURRENT USER SIMULATION SUMMARY")
    print("=" * 80)
    print(f"Suite:           {suite_path}")
    print(f"Pattern:         {pattern}")
    print(f"Concurrent users: {user_count}")
    print(f"Successful:      {successful}")
    print(f"Failed:          {failed}")
    print(f"Total duration:  {total_duration:.2f}s")
    print(f"Avg per user:    {sum(r.duration for r in results) / len(results):.2f}s")
    print(f"Min duration:    {min(r.duration for r in results):.2f}s")
    print(f"Max duration:    {max(r.duration for r in results):.2f}s")
    print("=" * 80)

    if failed > 0:
        print("\n⚠️  Some users experienced failures")

    return results


if __name__ == "__main__":
    app()


__all__ = ["app", "run_parallel_tests", "run_parallel_suites"]

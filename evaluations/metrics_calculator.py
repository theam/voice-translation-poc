"""Metrics calculation and reporting utilities."""

from typing import Dict, Any

from metrics import MetricResult, get_all_metrics
from models import TestResult, TestReport


def calculate_metrics(test_results: Dict[str, TestResult]) -> Dict[str, Dict[str, MetricResult]]:
    """
    Calculate all metrics for each test result.

    Automatically discovers and loads all metrics from the metrics package.

    Args:
        test_results: Dictionary of test_id -> TestResult

    Returns:
        Dictionary of test_id -> metric_name -> MetricResult
    """
    # Auto-discover all metrics (no manual imports needed)
    all_metrics = get_all_metrics()
    metric_results = {}

    print(f"\n{'='*80}")
    print(f"Calculating metrics...")
    print(f"{'='*80}\n")

    for test_id, test_result in test_results.items():
        print(f"Test: {test_id} - {test_result.test_case.name}")
        metric_results[test_id] = {}

        # Prepare data for metrics (in the format metrics expect)
        received_data = {
            "success": test_result.success,
            "recognized_text": test_result.recognized_text,
            "translations": test_result.translations,
            "response_time_ms": test_result.response_time_ms,
            "chunks_sent": test_result.chunks_sent,
            "chunks_received": len(test_result.azure_responses),
            "error_details": test_result.error_details,
            "latency_ms": test_result.latency_ms
        }

        for metric_name, metric_func in all_metrics.items():
            try:
                result = metric_func(
                    test_result.test_case.audio_file,
                    test_result.test_case.expected_text,
                    received_data
                )
                metric_results[test_id][metric_name] = result

                # Print result
                status = "✓ PASS" if result.passed else "✗ FAIL"
                print(f"  {status} {metric_name:30s} = {result.value:.4f}")

                # Print reasoning if available (for LLM-based metrics)
                if result.details and 'reasoning' in result.details:
                    reasoning = result.details['reasoning']
                    # Wrap long reasoning text
                    if len(reasoning) > 80:
                        reasoning = reasoning[:77] + "..."
                    print(f"      💡 {reasoning}")

                # Print text comparison for text-based metrics
                if result.details:
                    recognized = result.details.get('recognized_text')
                    reference = result.details.get('reference_text')
                    if recognized and reference:
                        # Truncate for console display
                        max_len = 60
                        ref_display = reference if len(reference) <= max_len else reference[:max_len] + "..."
                        rec_display = recognized if len(recognized) <= max_len else recognized[:max_len] + "..."
                        print(f"      📝 Expected: \"{ref_display}\"")
                        print(f"      🎤 Recognized: \"{rec_display}\"")

                # Print method used
                if result.details and 'method' in result.details:
                    method = result.details['method']
                    model = result.details.get('model', '')
                    if model:
                        print(f"      📊 Method: {method} ({model})")
                    else:
                        print(f"      📊 Method: {method}")

            except Exception as e:
                # Handle metric execution errors
                error_result = MetricResult(
                    metric_name=metric_name,
                    value=0.0,
                    passed=False,
                    details={"error": str(e)}
                )
                metric_results[test_id][metric_name] = error_result
                print(f"  ✗ ERROR {metric_name:30s} - {e}")

        print()

    return metric_results


def calculate_summary(report: TestReport, all_metrics: dict) -> Dict[str, Any]:
    """Calculate summary statistics for the report."""
    total_tests = len(report.test_cases)
    total_metrics = len(all_metrics)
    total_evaluations = total_tests * total_metrics

    passed_count = 0
    failed_count = 0
    total_value_sum = 0.0

    # Per-metric statistics
    metric_stats = {}
    for metric_name in all_metrics.keys():
        metric_stats[metric_name] = {
            "passed": 0,
            "failed": 0,
            "average_value": 0.0,
            "values": []
        }

    # Latency statistics
    latencies = []

    # Collect statistics
    for test_id, metrics_results in report.metric_results.items():
        # Collect latency data
        test_result = report.test_results.get(test_id)
        if test_result and test_result.latency_ms is not None:
            latencies.append(test_result.latency_ms)

        for metric_name, result in metrics_results.items():
            if result.passed:
                passed_count += 1
                metric_stats[metric_name]["passed"] += 1
            else:
                failed_count += 1
                metric_stats[metric_name]["failed"] += 1

            total_value_sum += result.value
            metric_stats[metric_name]["values"].append(result.value)

    # Calculate averages
    for metric_name, stats in metric_stats.items():
        if stats["values"]:
            stats["average_value"] = sum(stats["values"]) / len(stats["values"])

    # Calculate latency statistics
    latency_stats = {
        "average_ms": sum(latencies) / len(latencies) if latencies else None,
        "min_ms": min(latencies) if latencies else None,
        "max_ms": max(latencies) if latencies else None,
        "count": len(latencies)
    }

    return {
        "total_tests": total_tests,
        "total_metrics": total_metrics,
        "total_evaluations": total_evaluations,
        "passed": passed_count,
        "failed": failed_count,
        "pass_rate": passed_count / total_evaluations if total_evaluations > 0 else 0.0,
        "average_score": total_value_sum / total_evaluations if total_evaluations > 0 else 0.0,
        "metric_stats": metric_stats,
        "latency_stats": latency_stats
    }


def print_summary(report: TestReport) -> None:
    """Print summary statistics."""
    summary = report.summary

    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Timestamp: {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total Tests: {summary['total_tests']}")
    print(f"Total Metrics: {summary['total_metrics']}")
    print(f"Total Evaluations: {summary['total_evaluations']}")
    print(f"Passed: {summary['passed']} ({summary['pass_rate']*100:.1f}%)")
    print(f"Failed: {summary['failed']}")
    print(f"Average Score: {summary['average_score']:.4f}")

    # Print execution time if available
    if 'execution_time_seconds' in summary:
        exec_time = summary['execution_time_seconds']
        print(f"Total Execution Time: {exec_time:.2f}s")

    # Print latency statistics
    latency_stats = summary.get('latency_stats', {})
    if latency_stats and latency_stats['count'] > 0:
        print(f"\n{'─'*80}")
        print("LATENCY STATISTICS")
        print(f"{'─'*80}")
        print(f"Average Latency: {latency_stats['average_ms']:.2f}ms")
        print(f"Min Latency: {latency_stats['min_ms']:.2f}ms")
        print(f"Max Latency: {latency_stats['max_ms']:.2f}ms")
        print(f"Tests with latency data: {latency_stats['count']}")

    print(f"\n{'='*80}")
    print("PER-METRIC STATISTICS")
    print(f"{'='*80}")

    for metric_name, stats in summary['metric_stats'].items():
        pass_rate = stats['passed'] / (stats['passed'] + stats['failed']) if (stats['passed'] + stats['failed']) > 0 else 0.0
        print(f"{metric_name:30s} - Pass: {stats['passed']:2d}/{stats['passed']+stats['failed']:2d} "
              f"({pass_rate*100:5.1f}%) - Avg: {stats['average_value']:.4f}")

    print(f"{'='*80}\n")

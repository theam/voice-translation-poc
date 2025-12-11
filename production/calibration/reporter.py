"""Calibration reporter for displaying results."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .models import CalibrationResult, CalibrationSummary


class CalibrationReporter:
    """Display and export calibration results.

    Provides console output and file generation for calibration results.

    Example:
        >>> reporter = CalibrationReporter()
        >>> reporter.print_summary(summary)
        >>> reporter.print_detailed_results(summary)
        >>> reporter.generate_json_report(summary, Path("report.json"))
    """

    def print_summary(self, summary: CalibrationSummary) -> None:
        """Print calibration summary to console.

        Args:
            summary: Calibration summary to display
        """
        # Header
        print()
        print("=" * 70)
        print(f"📊 Calibration Results: {summary.config_id}")
        print("=" * 70)
        print()

        # Basic info
        print(f"Description: {summary.config_description}")
        print(f"Metric: {summary.metric_name}")
        if summary.llm_model:
            print(f"LLM Model: {summary.llm_model}")
        print(f"Timestamp: {summary.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Tolerance: ±{summary.tolerance}")
        print()

        # Summary statistics
        accuracy_symbol = "✅" if summary.accuracy >= 0.9 else "⚠️" if summary.accuracy >= 0.7 else "❌"
        print(f"Total Cases: {summary.total_cases}")
        print(f"Passed: {summary.passed_cases} ✓")
        print(f"Failed: {summary.failed_cases} ✗")
        print(f"Accuracy: {summary.accuracy:.1%} {accuracy_symbol}")
        print(f"Avg Score Diff: {summary.avg_score_diff:.3f}")
        print(f"Max Score Diff: {summary.max_score_diff:.3f}")
        print()

    def print_detailed_results(
        self,
        summary: CalibrationSummary,
        show_passed: bool = True,
        show_failed: bool = True
    ) -> None:
        """Print detailed per-case results.

        Args:
            summary: Calibration summary
            show_passed: Whether to show passed cases
            show_failed: Whether to show failed cases
        """
        print("Detailed Results:")
        print("=" * 70)
        print()

        for result in summary.results:
            # Filter by pass/fail
            if result.passed and not show_passed:
                continue
            if not result.passed and not show_failed:
                continue

            self._print_single_result(result)
            print()

    def _print_single_result(self, result: CalibrationResult) -> None:
        """Print single calibration result.

        Args:
            result: Calibration result to display
        """
        # Status symbol
        symbol = "✓" if result.passed else "✗"
        status_color = "\033[92m" if result.passed else "\033[91m"  # Green or Red
        reset_color = "\033[0m"

        # Header
        print(f"{status_color}{symbol} {result.case_id}{reset_color}")
        print(f"   {result.case_description}")
        print()

        # Scores
        print(f"   Expected: {result.expected_score:.3f}")
        print(f"   Actual:   {result.actual_score:.3f}")
        print(f"   Diff:     {result.score_diff:.3f} ({result.score_diff_percentage:.1f}%)")
        print()

        # Text evaluated
        if result.text_evaluated:
            text_preview = result.text_evaluated[:80]
            if len(result.text_evaluated) > 80:
                text_preview += "..."
            print(f"   Text: \"{text_preview}\"")
            print()

        # Reasoning
        if result.actual_reasoning:
            reasoning_preview = result.actual_reasoning[:150]
            if len(result.actual_reasoning) > 150:
                reasoning_preview += "..."
            print(f"   Reasoning: {reasoning_preview}")
            print()

        # Warning for failures
        if not result.passed:
            if result.actual_score > result.expected_score:
                print(f"   ⚠️  Score HIGHER than expected - metric may be too lenient")
            else:
                print(f"   ⚠️  Score LOWER than expected - metric may be too strict")
            print()

    def generate_json_report(
        self,
        summary: CalibrationSummary,
        output_path: Path
    ) -> None:
        """Generate JSON report file.

        Args:
            summary: Calibration summary
            output_path: Path to output JSON file
        """
        report_data = summary.to_dict()

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(report_data, f, indent=2)

        print(f"📄 JSON report saved to: {output_path}")

    def generate_markdown_report(
        self,
        summary: CalibrationSummary,
        output_path: Path
    ) -> None:
        """Generate Markdown report file.

        Args:
            summary: Calibration summary
            output_path: Path to output markdown file
        """
        lines = []

        # Header
        lines.append(f"# Calibration Report: {summary.config_id}")
        lines.append("")
        lines.append(f"**Description:** {summary.config_description}")
        lines.append(f"**Metric:** {summary.metric_name}")
        if summary.llm_model:
            lines.append(f"**LLM Model:** {summary.llm_model}")
        lines.append(f"**Timestamp:** {summary.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Tolerance:** ±{summary.tolerance}")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **Total Cases:** {summary.total_cases}")
        lines.append(f"- **Passed:** {summary.passed_cases} ✓")
        lines.append(f"- **Failed:** {summary.failed_cases} ✗")
        lines.append(f"- **Accuracy:** {summary.accuracy:.1%}")
        lines.append(f"- **Avg Score Diff:** {summary.avg_score_diff:.3f}")
        lines.append(f"- **Max Score Diff:** {summary.max_score_diff:.3f}")
        lines.append("")

        # Detailed results
        lines.append("## Detailed Results")
        lines.append("")

        for result in summary.results:
            status = "✓ PASS" if result.passed else "✗ FAIL"
            lines.append(f"### {status}: {result.case_id}")
            lines.append("")
            lines.append(f"**Description:** {result.case_description}")
            lines.append("")
            lines.append(f"- **Expected Score:** {result.expected_score:.3f}")
            lines.append(f"- **Actual Score:** {result.actual_score:.3f}")
            lines.append(f"- **Difference:** {result.score_diff:.3f} ({result.score_diff_percentage:.1f}%)")
            lines.append("")

            if result.text_evaluated:
                lines.append(f"**Text:** \"{result.text_evaluated}\"")
                lines.append("")

            if result.actual_reasoning:
                lines.append(f"**Reasoning:** {result.actual_reasoning}")
                lines.append("")

            if not result.passed:
                if result.actual_score > result.expected_score:
                    lines.append("⚠️ **Warning:** Score HIGHER than expected - metric may be too lenient")
                else:
                    lines.append("⚠️ **Warning:** Score LOWER than expected - metric may be too strict")
                lines.append("")

            lines.append("---")
            lines.append("")

        # Write file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write("\n".join(lines))

        print(f"📄 Markdown report saved to: {output_path}")


__all__ = ["CalibrationReporter"]

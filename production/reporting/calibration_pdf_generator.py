"""Standalone PDF generator for calibration reports."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from production.calibration import CalibrationResult
from production.storage.models import Turn, TurnMetricData

from .models import EvaluationRunData, TestReportData
from .report_utils import (
    create_standard_table,
    generate_report_filename,
    sanitize_html_for_reportlab,
    score_color_band,
)


class CalibrationReportPdfGenerator:
    """Generate calibration-only PDF reports without sharing logic with other reports."""

    def __init__(self, output_dir: Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[2]
        self.output_dir = output_dir or project_root / "reports"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        evaluation_data: EvaluationRunData,
        test_reports: List[TestReportData],
    ) -> Path:
        """Generate a calibration PDF report."""
        report_name = generate_report_filename("calibration", evaluation_data.evaluation_run_id)
        output_path = self.output_dir / report_name

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=36,
        )

        elements: list = []
        styles = getSampleStyleSheet()

        self._add_calibration_run_header(evaluation_data, test_reports, elements, styles)
        elements.append(PageBreak())

        for test_data in test_reports:
            self._add_test_section(test_data, elements, styles)
            elements.append(PageBreak())

        if elements and isinstance(elements[-1], PageBreak):
            elements.pop()

        doc.build(elements)
        return output_path

    def _add_calibration_run_header(
        self,
        data: EvaluationRunData,
        test_reports: List[TestReportData],
        elements: list,
        styles: Any,
    ) -> None:
        """Render the top-level calibration run metadata and overview tables."""
        title_style = ParagraphStyle(
            "CalibrationTitle",
            parent=styles["Heading1"],
            fontSize=22,
            textColor=colors.HexColor("#1f4788"),
            spaceAfter=24,
            alignment=TA_CENTER,
        )
        normal_style = styles["Normal"]
        heading_style = styles["Heading2"]

        elements.append(Paragraph("Calibration Run Details", title_style))
        elements.append(Spacer(1, 0.2 * inch))

        duration = self._format_duration(data.started_at, data.finished_at)
        meta_lines = [
            f"<b>Evaluation Run ID:</b> {data.evaluation_run_id}",
            f"<b>Started:</b> {data.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"<b>Finished:</b> {data.finished_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"<b>Duration:</b> {duration}",
            "",
            f"<b>Git Branch:</b> {data.git_branch}",
            f"<b>Git Commit:</b> {data.git_commit}",
            f"<b>Environment:</b> {data.environment}",
            f"<b>Target System:</b> {data.target_system}",
            f"<b>System Hash:</b> {data.system_info_hash[:16]}...",
        ]
        if data.experiment_tags:
            meta_lines.append(f"<b>Experiment Tags:</b> {', '.join(data.experiment_tags)}")

        for line in meta_lines:
            elements.append(Paragraph(line, normal_style))
        elements.append(Spacer(1, 0.2 * inch))

        self._add_calibration_summary_table(data, test_reports, elements, styles)
        elements.append(Spacer(1, 0.2 * inch))

        elements.append(Paragraph("Calibration Tests Overview", heading_style))
        elements.append(Spacer(1, 0.05 * inch))
        self._add_calibration_tests_table(test_reports, elements, styles)
        elements.append(Spacer(1, 0.25 * inch))

    def _add_calibration_summary_table(
        self,
        evaluation_data: EvaluationRunData,
        test_reports: List[TestReportData],
        elements: list,
        styles: Any,
    ) -> None:
        """Show high-level pass/fail counts for calibration run."""
        total_tests = len(test_reports)
        passed_tests = sum(
            1
            for test in test_reports
            if test.calibration_summary and test.calibration_summary.overall_passed
        )
        failed_tests = total_tests - passed_tests

        # Use calibration status from evaluation run (already calculated)
        calibration_status = evaluation_data.calibration_status or "failed"
        status_color = colors.lightgreen if calibration_status == "passed" else colors.lightpink

        table_data = [
            ["Calibration Summary", "Tests Passed", "Tests Failed", "Total"],  # Header
            [calibration_status.upper(), str(passed_tests), str(failed_tests), str(total_tests)],  # Data
        ]

        table = Table(table_data, colWidths=[1.75 * inch, 1.75 * inch, 1.75 * inch, 1.75 * inch])
        table_style = [
            # Header row
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4788")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            # Data row colored by status
            ("BACKGROUND", (0, 1), (-1, 1), status_color),
        ]

        table.setStyle(TableStyle(table_style))
        elements.append(table)

    def _add_calibration_tests_table(
        self,
        test_reports: List[TestReportData],
        elements: list,
        styles: Any,
    ) -> None:
        """Table showing per-test calibration status."""
        table_data = [["Test ID", "Status", "Score", "Expected", "Tolerance"]]

        for test in test_reports:
            cal = test.calibration_summary
            if cal:
                has_failures = False
                if cal.expected_score is not None and not cal.score_within_tolerance:
                    has_failures = True
                if any(not r.passed for r in (cal.turns or [])):
                    has_failures = True
                if cal.conversation and not cal.conversation.passed:
                    has_failures = True
                status = "FAIL" if has_failures else "PASS"
                expected = cal.expected_score if cal.expected_score is not None else "—"
                tolerance_value = cal.score_tolerance
                tolerance = f"±{tolerance_value:.1f}" if tolerance_value is not None else "—"
            else:
                status = "N/A"
                expected = "—"
                tolerance = "—"

            table_data.append([
                test.test_id,
                status,
                f"{test.score:.1f}",
                expected if isinstance(expected, str) else f"{expected:.1f}",
                tolerance,
            ])

        table = Table(table_data, colWidths=[2.5 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch, 0.9 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4788")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ]))

        for idx, row in enumerate(table_data[1:], start=1):
            status = row[1]
            if status == "PASS":
                table.setStyle([("BACKGROUND", (1, idx), (1, idx), colors.lightgreen)])
            elif status == "FAIL":
                table.setStyle([("BACKGROUND", (1, idx), (1, idx), colors.lightpink)])

        elements.append(table)

    def _add_test_section(
        self,
        test_data: TestReportData,
        elements: list,
        styles: Any,
    ) -> None:
        """Render a full section for a single calibration test."""
        heading_style = styles["Heading2"]
        normal_style = styles["Normal"]

        elements.append(Paragraph(f"Test: {test_data.test_id}", heading_style))

        description_style = ParagraphStyle(
            "TestDescription",
            parent=normal_style,
            fontSize=10,
            textColor=colors.HexColor("#555555"),
            spaceAfter=6,
        )
        elements.append(Paragraph(test_data.test_name, description_style))
        elements.append(Spacer(1, 0.1 * inch))

        duration_seconds = test_data.duration_ms / 1000.0
        meta_lines = [
            f"<b>Test ID:</b> {test_data.test_id}",
            f"<b>Test Run ID:</b> {test_data.test_run_id}",
            f"<b>Started:</b> {test_data.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"<b>Finished:</b> {test_data.finished_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"<b>Duration:</b> {duration_seconds:.2f}s",
        ]
        if test_data.scenario_metrics:
            meta_lines.append(f"<b>Metrics:</b> {', '.join(test_data.scenario_metrics)}")
        meta_lines.append("")
        meta_lines.append(f"<b>Test Score:</b> {test_data.score:.1f}")
        if test_data.expected_score is not None:
            meta_lines.append(f"<b>Expected Score:</b> {test_data.expected_score:.1f}")
        meta_lines.append(f"<b>Score Method:</b> {test_data.score_method}")

        for line in meta_lines:
            elements.append(Paragraph(line, normal_style))
        elements.append(Spacer(1, 0.2 * inch))

        elements.append(Paragraph("Metrics Summary", heading_style))
        elements.append(Spacer(1, 0.05 * inch))
        self._add_metric_summary_table(test_data, elements, styles)
        elements.append(Spacer(1, 0.2 * inch))

        elements.append(Paragraph("Conversation Details", heading_style))
        elements.append(Spacer(1, 0.05 * inch))
        for turn in sorted(test_data.turns, key=lambda t: t.start_scn_ms):
            self._render_turn_section(turn, elements, normal_style)

        has_conversation_metrics = any(
            getattr(metric, "conversation", None) is not None
            for metric in test_data.metrics.values()
        )
        has_turn_metrics = any(
            getattr(metric, "turns", None) for metric in test_data.metrics.values()
        )

        if has_conversation_metrics:
            elements.append(Spacer(1, 0.12 * inch))
            elements.append(Paragraph("Conversation-Scope Calibration", heading_style))
            elements.append(Spacer(1, 0.05 * inch))
            self._add_conversation_metrics_tables(test_data, elements, styles)

        if has_turn_metrics:
            elements.append(Spacer(1, 0.15 * inch))
            elements.append(Paragraph("Turn-Scope Calibration", heading_style))
            elements.append(Spacer(1, 0.05 * inch))
            self._add_turn_metrics_table(test_data, elements, styles)
            elements.append(Spacer(1, 0.15 * inch))

    def _add_metric_summary_table(
        self,
        test_data: TestReportData,
        elements: list,
        styles: Any,
    ) -> None:
        """Summary table per metric mirroring legacy calibration format."""
        table_data = [["Metric", "Status", "Score", "Expected", "Tolerance"]]

        calibration_by_metric: Dict[str, List[CalibrationResult]] = {}
        if test_data.calibration_summary and test_data.calibration_summary.turns:
            for result in test_data.calibration_summary.turns:
                calibration_by_metric.setdefault(result.metric_name, []).append(result)

        # Check for conversation-level calibration
        conversation_cal = None
        if test_data.calibration_summary and test_data.calibration_summary.conversation:
            conversation_cal = test_data.calibration_summary.conversation

        # Get default tolerance from calibration summary
        default_tolerance = None
        if test_data.calibration_summary and test_data.calibration_summary.score_tolerance is not None:
            default_tolerance = test_data.calibration_summary.score_tolerance

        for metric_name, metric in sorted(test_data.metrics.items()):
            cal_results = calibration_by_metric.get(metric_name, [])

            # Check if this is a conversation-level metric
            is_conversation_metric = conversation_cal and conversation_cal.metric_name == metric_name

            if cal_results:
                # Has turn-level calibration results
                passed = all(r.passed for r in cal_results)
                expected = cal_results[0].expected
                tolerance = f"±{cal_results[0].tolerance:.2f}"
                status = "PASS" if passed else "FAIL"
            elif is_conversation_metric:
                # Has conversation-level calibration result
                passed = conversation_cal.passed
                expected = conversation_cal.expected
                tolerance = f"±{conversation_cal.tolerance:.2f}"
                status = "PASS" if passed else "FAIL"
            else:
                # No calibration result - use metric score and test expected score
                score_value = getattr(metric, "score", None)
                expected = test_data.expected_score if test_data.expected_score is not None else "—"
                tolerance = f"±{default_tolerance:.2f}" if default_tolerance is not None else "—"

                # Determine status based on expected score and tolerance
                if expected != "—" and score_value is not None and default_tolerance is not None:
                    delta = abs(score_value - expected)
                    passed = delta <= default_tolerance
                    status = "PASS" if passed else "FAIL"
                else:
                    # Fallback to simple threshold
                    passed = score_value is not None and score_value >= 70.0
                    status = "PASS" if passed else "FAIL"

            table_data.append([
                metric_name,
                status,
                self._format_value(getattr(metric, "score", None)),
                expected if isinstance(expected, str) else f"{expected:.2f}",
                tolerance,
            ])

        table = Table(
            table_data,
            colWidths=[2.1 * inch, 1.0 * inch, 1.0 * inch, 1.2 * inch, 1.2 * inch],
        )
        table_style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4788")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]

        # Color entire row based on status (like conversation table)
        for idx, row in enumerate(table_data[1:], start=1):
            status = row[1]
            if status == "PASS":
                table_style.append(("BACKGROUND", (0, idx), (-1, idx), colors.lightgreen))
            elif status == "FAIL":
                table_style.append(("BACKGROUND", (0, idx), (-1, idx), colors.lightpink))

        table.setStyle(TableStyle(table_style))
        elements.append(table)

    def _add_conversation_metrics_tables(
        self,
        test_data: TestReportData,
        elements: list,
        styles: Any,
    ) -> None:
        """Render conversation-level metric tables."""
        normal_style = styles["Normal"]
        detail_style = ParagraphStyle(
            "ConversationMetricDetailStyle",
            parent=normal_style,
            fontSize=8,
            leading=10,
        )

        for metric_name, metric in sorted(test_data.metrics.items()):
            conv = getattr(metric, "conversation", None)
            if conv is None:
                continue

            score_value = getattr(conv, "score", None)
            expected_value = getattr(conv, "expected_score", None)
            detail_html = self._turn_metric_details_html(conv)

            table_data = [
                ["Metric", "Status", "Score", "Expected", "Tolerance"],
                [
                    metric_name,
                    "",  # filled via calibration status if available
                    self._format_value(score_value),
                    self._format_value(expected_value),
                    "—",
                ],
                ["Details", "", "", "", ""],
                [Paragraph(detail_html, detail_style), "", "", "", ""],
            ]
            extra_styles = [
                ("SPAN", (0, 2), (4, 2)),
                ("SPAN", (0, 3), (4, 3)),
                ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#e8edf7")),
                ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#1f4788")),
                ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
            ]
            # Color row by status
            status_bg = colors.whitesmoke
            status_text = "N/A"
            cal_result = test_data.calibration_summary.conversation if test_data.calibration_summary else None
            if cal_result and cal_result.metric_name == metric_name:
                status_text = cal_result.status
                if cal_result.status == "PASS":
                    status_bg = colors.lightgreen
                elif cal_result.status in ("FAIL", "MISSING"):
                    status_bg = colors.lightpink
            table_data[1][1] = status_text
            table_data[1][4] = (
                f"±{(test_data.calibration_summary.score_tolerance or 0):.2f}"
                if test_data.calibration_summary and test_data.calibration_summary.score_tolerance is not None
                else "—"
            )
            extra_styles.append(("BACKGROUND", (0, 1), (-1, 1), status_bg))

            table = create_standard_table(
                table_data,
                num_columns=5,
                total_width_inch=6.5,
                extra_styles=extra_styles,
            )
            elements.append(table)
            elements.append(Spacer(1, 0.1 * inch))
        elements.append(Spacer(1, 0.12 * inch))

    def _add_turn_metrics_table(
        self,
        test_data: TestReportData,
        elements: list,
        styles: Any,
    ) -> None:
        """Render per-turn calibration tables matching conversation table format."""
        normal_style = styles["Normal"]
        detail_style = ParagraphStyle(
            "TurnMetricDetailStyle",
            parent=normal_style,
            fontSize=8,
            leading=10,
        )

        cal_by_turn_metric: Dict[Tuple[str, str], CalibrationResult] = {}
        if test_data.calibration_summary and test_data.calibration_summary.turns:
            for result in test_data.calibration_summary.turns:
                cal_by_turn_metric[(result.turn_id, result.metric_name)] = result

        metrics_by_turn: Dict[str, Dict[str, TurnMetricData]] = {}
        for metric_name, metric in test_data.metrics.items():
            for turn_metric in getattr(metric, "turns", []):
                metrics_by_turn.setdefault(turn_metric.turn_id, {})[metric_name] = turn_metric

        turns_sorted = sorted(test_data.turns, key=lambda t: t.start_scn_ms)
        for turn in turns_sorted:
            turn_metrics = metrics_by_turn.get(turn.turn_id, {})
            metric_names = set(turn_metrics.keys())
            metric_names.update(turn.metric_expectations.keys())
            metric_names.update(
                metric_name
                for (turn_id, metric_name), _ in cal_by_turn_metric.items()
                if turn_id == turn.turn_id
            )

            if not metric_names:
                table_data = [
                    ["Turn", "Status", "Score", "Expected", "Tolerance"],
                    [f"Turn {turn.turn_id}", "N/A", "—", "—", "—"],
                    ["Details", "", "", "", ""],
                    [Paragraph("No metric data for this turn", detail_style), "", "", "", ""],
                ]
                extra_styles = [
                    ("SPAN", (0, 2), (4, 2)),
                    ("SPAN", (0, 3), (4, 3)),
                    ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#e8edf7")),
                    ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#1f4788")),
                    ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                ]
                col_widths = [2.6 * inch, 0.975 * inch, 0.975 * inch, 1.0 * inch, 1.0 * inch]
                table = Table(table_data, colWidths=col_widths)
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4788")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ] + list(extra_styles)))
                elements.append(table)
                elements.append(Spacer(1, 0.1 * inch))
                continue

            for metric_name in sorted(metric_names):
                turn_metric = turn_metrics.get(metric_name)
                cal_result = cal_by_turn_metric.get((turn.turn_id, metric_name))
                score_value = None
                if turn_metric:
                    score_value = turn_metric.score
                elif metric_name in test_data.metrics:
                    score_value = getattr(test_data.metrics[metric_name], "score", None)

                expected_value: Any = "—"
                tolerance_display = "—"
                status = "N/A"

                if cal_result:
                    expected_value = cal_result.expected
                    tolerance_display = f"±{cal_result.tolerance:.2f}"
                    status = cal_result.status
                elif turn_metric and turn_metric.expected_score is not None:
                    expected_value = turn_metric.expected_score
                    status = "PASS" if turn_metric.score >= (turn_metric.expected_score or 0) else "FAIL"
                elif metric_name in turn.metric_expectations:
                    expected_value = turn.metric_expectations[metric_name]
                    if score_value is not None:
                        delta = score_value - expected_value
                        status = "PASS" if abs(delta) <= 0.1 else "FAIL"
                    else:
                        status = "MISSING"

                detail_html = self._turn_metric_details_html(turn_metric)

                table_data = [
                    ["Turn", "Status", "Score", "Expected", "Tolerance"],
                    [
                        f"Turn {turn.turn_id}",
                        status,
                        self._format_value(score_value),
                        expected_value if isinstance(expected_value, str) else f"{expected_value:.4f}",
                        tolerance_display,
                    ],
                    ["Details", "", "", "", ""],
                    [Paragraph(detail_html, detail_style), "", "", "", ""],
                ]
                extra_styles = [
                    ("SPAN", (0, 2), (4, 2)),
                    ("SPAN", (0, 3), (4, 3)),
                    ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#e8edf7")),
                    ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#1f4788")),
                    ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                ]
                status_bg = colors.whitesmoke
                if status == "PASS":
                    status_bg = colors.lightgreen
                elif status in ("FAIL", "MISSING"):
                    status_bg = colors.lightpink
                extra_styles.append(("BACKGROUND", (0, 1), (-1, 1), status_bg))

                col_widths = [2.6 * inch, 0.975 * inch, 0.975 * inch, 1.0 * inch, 1.0 * inch]
                table = Table(table_data, colWidths=col_widths)
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4788")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ] + list(extra_styles)))
                elements.append(table)
                elements.append(Spacer(1, 0.1 * inch))

    def _turn_metric_details_html(self, turn_metric: Any | None) -> str:
        """Return detail HTML for a turn or conversation metric."""
        if not turn_metric or not getattr(turn_metric, "details", None):
            return "No details available"

        details = turn_metric.details
        segments: list[str] = []
        reasoning = details.get("reasoning") if isinstance(details, dict) else None
        if reasoning:
            segments.append(f"<b>Reasoning:</b> {self._sanitize_html(str(reasoning))}")

        if isinstance(details, dict):
            for key, value in details.items():
                if key == "reasoning" or value is None:
                    continue
                rendered_value = self._render_detail_value(value)
                segments.append(f"<b>{self._sanitize_html(key)}:</b> {self._sanitize_html(rendered_value)}")
        else:
            segments.append(self._sanitize_html(str(details)))

        full_text = "<br/>".join(segments) if segments else "No details available"

        # Ensure tag balance for safety
        open_b = full_text.count("<b>")
        close_b = full_text.count("</b>")
        if open_b > close_b:
            full_text += "</b>" * (open_b - close_b)
        open_i = full_text.count("<i>")
        close_i = full_text.count("</i>")
        if open_i > close_i:
            full_text += "</i>" * (open_i - close_i)

        return full_text

    def _render_turn_section(
        self,
        turn: Turn,
        elements: list,
        normal_style: ParagraphStyle,
    ) -> None:
        """Render a 4-row turn block mirroring legacy layout."""
        turn_text_style = ParagraphStyle(
            "TurnTextStyle",
            parent=normal_style,
            fontSize=9,
            leading=11,
        )

        lang_info = ""
        if turn.source_language or turn.expected_language:
            lang_info = f" ({turn.source_language or 'unknown'} → {turn.expected_language or 'unknown'})"

        turn_rows = [
            [f"Turn {turn.turn_id} at {turn.start_scn_ms}ms{lang_info}"],
            [Paragraph(
                f"<b>Source Text:</b> {self._sanitize_html(turn.source_text or '—')}",
                turn_text_style,
            )],
            [Paragraph(
                f"<b>Translated Text:</b> {self._sanitize_html(turn.translated_text or '—')}",
                turn_text_style,
            )],
            [Paragraph(
                f"<b>Expected Text:</b> {self._sanitize_html(turn.expected_text or '—')}",
                turn_text_style,
            )],
        ]

        table = Table(turn_rows, colWidths=[6.5 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#4a6fa5")),
            ("TEXTCOLOR", (0, 0), (0, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (0, 0), 10),
            ("ALIGN", (0, 0), (0, 0), "LEFT"),
            ("LEFTPADDING", (0, 0), (0, 0), 6),
            ("TOPPADDING", (0, 0), (0, 0), 6),
            ("BOTTOMPADDING", (0, 0), (0, 0), 6),
            ("BACKGROUND", (0, 1), (0, 3), colors.beige),
            ("ALIGN", (0, 1), (0, 3), "LEFT"),
            ("LEFTPADDING", (0, 1), (0, 3), 6),
            ("TOPPADDING", (0, 1), (0, 3), 6),
            ("BOTTOMPADDING", (0, 1), (0, 3), 6),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.12 * inch))

    @staticmethod
    def _format_duration(started_at, finished_at) -> str:
        duration = finished_at - started_at
        total_seconds = int(duration.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"

    @staticmethod
    def _format_value(value: Any) -> str:
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value)

    @staticmethod
    def _render_detail_value(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.4f}"
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        if isinstance(value, dict):
            return "; ".join(f"{k}: {v}" for k, v in value.items())
        return str(value)

    def _format_turn_metric_details(
        self,
        turn_metric: TurnMetricData | None,
        normal_style: ParagraphStyle,
    ) -> Paragraph:
        detail_html = self._turn_metric_details_html(turn_metric)
        return Paragraph(detail_html, normal_style)

    @staticmethod
    def _sanitize_html(text: str) -> str:
        """Escape angle brackets while preserving basic bold/italic/br tags."""
        return sanitize_html_for_reportlab(text)


__all__ = ["CalibrationReportPdfGenerator"]

"""Standalone PDF generator for evaluation (non-calibration) reports."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from production.storage.models import MetricData, Turn, TurnMetricData

from .models import EvaluationRunData, TestReportData
from .report_utils import (
    create_standard_table,
    generate_report_filename,
    sanitize_html_for_reportlab,
    score_color_band,
)


class EvaluationReportPdfGenerator:
    """Generate PDF reports for standard evaluation runs."""

    def __init__(self, output_dir: Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[2]
        self.output_dir = output_dir or project_root / "reports"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        evaluation_data: EvaluationRunData,
        test_reports: List[TestReportData],
    ) -> Path:
        """Generate an evaluation PDF report."""
        report_name = generate_report_filename("evaluation", evaluation_data.evaluation_run_id)
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

        self._add_evaluation_run_header(evaluation_data, test_reports, elements, styles)
        elements.append(PageBreak())

        for test_data in test_reports:
            self._add_test_section(test_data, elements, styles)
            elements.append(PageBreak())

        if elements and isinstance(elements[-1], PageBreak):
            elements.pop()

        doc.build(elements)
        return output_path

    def _add_evaluation_run_header(
        self,
        data: EvaluationRunData,
        test_reports: List[TestReportData],
        elements: list,
        styles: Any,
    ) -> None:
        """Render evaluation run metadata and overview tables."""
        title_style = ParagraphStyle(
            "EvaluationTitle",
            parent=styles["Heading1"],
            fontSize=22,
            textColor=colors.HexColor("#1f4788"),
            spaceAfter=24,
            alignment=TA_CENTER,
        )
        normal_style = styles["Normal"]
        heading_style = styles["Heading3"]

        elements.append(Paragraph("Evaluation Run Summary", title_style))
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

        self._add_overall_results_table(data, elements, styles)
        elements.append(Spacer(1, 0.15 * inch))

        if data.aggregated_metrics:
            elements.append(Paragraph("Metrics Summary", heading_style))
            elements.append(Spacer(1, 0.05 * inch))
            self._add_aggregated_metrics_table(data, elements, styles)
            elements.append(Spacer(1, 0.15 * inch))

        # Tests summary table
        elements.append(Paragraph("Tests Summary", heading_style))
        elements.append(Spacer(1, 0.05 * inch))
        self._add_tests_summary_table(test_reports, elements, styles)
        elements.append(Spacer(1, 0.15 * inch))

        elements.append(Paragraph("Test Details", styles["Heading1"]))
        elements.append(Spacer(1, 0.1 * inch))

    def _add_overall_results_table(
        self,
        data: EvaluationRunData,
        elements: list,
        styles: Any,
    ) -> None:
        total_tests = data.num_tests
        table_data = [
            ["Tests Run", "Score", "Score Calculation Method"],
            [
                str(total_tests),
                f"{data.score:.1f}",
                data.score_method if hasattr(data, "score_method") and data.score_method else "average",
            ],
        ]

        score_bg = score_color_band(data.score or 0)
        table = create_standard_table(
            table_data,
            num_columns=3,
            extra_styles=[("BACKGROUND", (0, 1), (-1, 1), score_bg)],
        )
        elements.append(table)

    def _add_aggregated_metrics_table(
        self,
        data: EvaluationRunData,
        elements: list,
        styles: Any,
    ) -> None:
        table_data: list[list[Any]] = [["Metric", "Score", "Score Calculation Method"]]
        for metric_name, avg_value in sorted(data.aggregated_metrics.items()):
            score_value = avg_value if avg_value is not None else 0.0
            method = "average across tests"
            table_data.append([metric_name, f"{score_value:.2f}", method])

        extra_styles: list[Tuple] = []
        for idx in range(1, len(table_data)):
            score_str = table_data[idx][1]
            try:
                score_val = float(score_str)
            except ValueError:
                score_val = 0.0
            bg_color = score_color_band(score_val)
            extra_styles.append(("BACKGROUND", (0, idx), (-1, idx), bg_color))

        table = create_standard_table(
            table_data,
            num_columns=3,
            extra_styles=extra_styles,
        )
        elements.append(table)

    def _add_tests_summary_table(
        self,
        test_reports: List[TestReportData],
        elements: list,
        styles: Any,
    ) -> None:
        """Table summarizing each test's score and calculation method."""
        table_data = [["Test", "Score", "Score Calculation Method"]]
        for test in test_reports:
            table_data.append([
                test.test_id,
                f"{test.score:.1f}",
                test.score_method,
            ])

        extra_styles = []
        for idx in range(1, len(table_data)):
            score_str = table_data[idx][1]
            try:
                score_val = float(score_str)
            except ValueError:
                score_val = 0.0
            bg_color = score_color_band(score_val)
            extra_styles.append(("BACKGROUND", (0, idx), (-1, idx), bg_color))

        table = create_standard_table(
            table_data,
            num_columns=3,
            extra_styles=extra_styles,
        )
        elements.append(table)

    def _section_heading(self, text: str, styles: Any) -> Paragraph:
        """Consistent section heading."""
        return Paragraph(text, styles["Heading2"])

    def _add_test_section(
        self,
        test_data: TestReportData,
        elements: list,
        styles: Any,
    ) -> None:
        """Render a test section without calibration expectations."""
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
        meta_lines.append(f"<b>Score Method:</b> {test_data.score_method}")

        for line in meta_lines:
            elements.append(Paragraph(line, normal_style))
        elements.append(Spacer(1, 0.2 * inch))

        elements.append(Paragraph("Metrics", heading_style))
        elements.append(Spacer(1, 0.05 * inch))
        self._add_metric_summary_table(test_data, elements, styles)
        elements.append(Spacer(1, 0.15 * inch))

        elements.append(self._section_heading("Conversation Details", styles))
        elements.append(Spacer(1, 0.05 * inch))
        for turn in sorted(test_data.turns, key=lambda t: t.start_scn_ms):
            self._render_turn_section(turn, elements, normal_style)

        elements.append(Spacer(1, 0.12 * inch))
        elements.append(self._section_heading("Conversation-Scope Metrics", styles))
        elements.append(Paragraph(
            "Metrics whose computation requires the full conversation context.",
            styles["Normal"],
        ))
        elements.append(Spacer(1, 0.05 * inch))
        self._add_conversation_metrics_tables(test_data, elements, styles)
        elements.append(Spacer(1, 0.12 * inch))

        elements.append(Spacer(1, 0.12 * inch))
        elements.append(self._section_heading("Turn-Scope Metrics", styles))
        elements.append(Paragraph(
            "Metrics computed independently for each conversational turn; the per-turn scores are then aggregated to derive the overall conversation-level score for that metric.",
            styles["Normal"],
        ))
        elements.append(Spacer(1, 0.05 * inch))
        self._add_turn_metrics_table(test_data, elements, styles)
        elements.append(Spacer(1, 0.2 * inch))

    def _add_metric_summary_table(
        self,
        test_data: TestReportData,
        elements: list,
        styles: Any,
    ) -> None:
        """Summary table per metric (no calibration expectations)."""
        table_data = [["Metric", "Score"]]
        for metric_name, metric in sorted(test_data.metrics.items()):
            score_value = getattr(metric, "score", None)
            table_data.append([
                metric_name,
                self._format_value(score_value),
            ])

        extra_styles = []
        for idx, row in enumerate(table_data[1:], start=1):
            try:
                score_val = float(row[1])
            except ValueError:
                score_val = 0.0
            bg_color = score_color_band(score_val)
            extra_styles.append(("BACKGROUND", (0, idx), (-1, idx), bg_color))

        table = create_standard_table(
            table_data,
            num_columns=2,
            extra_styles=extra_styles,
        )
        elements.append(table)

    def _add_turn_metrics_table(
        self,
        test_data: TestReportData,
        elements: list,
        styles: Any,
    ) -> None:
        """Show per-turn metric breakdown without expectations."""
        normal_style = styles["Normal"]
        detail_style = ParagraphStyle(
            "TurnMetricDetailStyle",
            parent=normal_style,
            fontSize=8,
            leading=10,
        )

        metrics_by_turn: Dict[str, Dict[str, TurnMetricData]] = {}
        for metric_name, metric in test_data.metrics.items():
            for turn_metric in getattr(metric, "turns", []):
                metrics_by_turn.setdefault(turn_metric.turn_id, {})[metric_name] = turn_metric

        turns_sorted = sorted(test_data.turns, key=lambda t: t.start_scn_ms)
        for idx, turn in enumerate(turns_sorted, start=1):
            elements.append(self._section_heading(f"Turn {idx}", styles))
            elements.append(Spacer(1, 0.05 * inch))

            turn_metrics = metrics_by_turn.get(turn.turn_id, {})
            metric_names = sorted(turn_metrics.keys())

            if not metric_names:
                table_data = [["Turn", "Metric", "Score"], [f"Turn {turn.turn_id}", "—", "—"]]
                table_data.append(["Details", "", ""])
                table_data.append(["No metric data for this turn", "", ""])
                spans = [((0, 2), (2, 2)), ((0, 3), (2, 3))]
                table = create_standard_table(
                    table_data,
                    num_columns=3,
                    extra_styles=[
                        ("SPAN", (0, 2), (2, 2)),
                        ("SPAN", (0, 3), (2, 3)),
                        ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#e8edf7")),
                        ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#1f4788")),
                        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                    ],
                )
                elements.append(table)
                elements.append(Spacer(1, 0.1 * inch))
                continue

            for metric_name in metric_names:
                turn_metric = turn_metrics.get(metric_name)
                score_value = turn_metric.score if turn_metric else None
                detail_html = self._turn_metric_details_html(turn_metric)

                # Color by score band for the data row
                data_row_idx = 1  # after header
                try:
                    data_score_val = float(self._format_value(score_value))
                except ValueError:
                    data_score_val = 0.0
                data_bg = score_color_band(data_score_val)

                table_data = [
                    ["Turn", "Metric", "Score"],
                    [f"Turn {turn.turn_id}", metric_name, self._format_value(score_value)],
                    ["Details", "", ""],
                    [Paragraph(detail_html, detail_style), "", ""],
                ]
                extra_styles = [
                    ("SPAN", (0, 2), (2, 2)),
                    ("SPAN", (0, 3), (2, 3)),
                    ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#e8edf7")),
                    ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#1f4788")),
                    ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                    ("BACKGROUND", (0, data_row_idx), (-1, data_row_idx), data_bg),
                ]

                table = create_standard_table(
                    table_data,
                    num_columns=3,
                    extra_styles=extra_styles,
                )
                elements.append(table)
                elements.append(Spacer(1, 0.1 * inch))

    def _render_turn_section(
        self,
        turn: Turn,
        elements: list,
        normal_style: ParagraphStyle,
    ) -> None:
        """Render a 4-row turn block."""
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
            detail_html = self._turn_metric_details_html(conv)

            table_data = [
                ["Metric", "Score"],
                [metric_name, self._format_value(score_value)],
                ["Details", ""],
                [Paragraph(detail_html, detail_style), ""],
            ]
            extra_styles = [
                ("SPAN", (0, 2), (1, 2)),
                ("SPAN", (0, 3), (1, 3)),
                ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#e8edf7")),
                ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#1f4788")),
                ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
            ]
            try:
                score_val = float(self._format_value(score_value))
            except ValueError:
                score_val = 0.0
            data_bg = score_color_band(score_val)
            extra_styles.append(("BACKGROUND", (0, 1), (-1, 1), data_bg))

            table = create_standard_table(
                table_data,
                num_columns=2,
                extra_styles=extra_styles,
            )
            elements.append(table)
            elements.append(Spacer(1, 0.1 * inch))
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
            return f"{value:.2f}"
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

    def _turn_metric_details_html(self, turn_metric: TurnMetricData | None) -> str:
        """Return detail HTML for a turn metric."""
        if not turn_metric or not turn_metric.details:
            return "No details available"

        segments: list[str] = []
        reasoning = turn_metric.details.get("reasoning") if isinstance(turn_metric.details, dict) else None
        if reasoning:
            segments.append(f"<b>Reasoning:</b> {self._sanitize_html(str(reasoning))}")

        if isinstance(turn_metric.details, dict):
            for key, value in turn_metric.details.items():
                if key == "reasoning" or value is None:
                    continue
                rendered_value = self._render_detail_value(value)
                segments.append(f"<b>{self._sanitize_html(key)}:</b> {self._sanitize_html(rendered_value)}")
        else:
            segments.append(self._sanitize_html(str(turn_metric.details)))

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

    @staticmethod
    def _sanitize_html(text: str) -> str:
        """Escape angle brackets while preserving basic bold/italic/br tags."""
        return sanitize_html_for_reportlab(text)


__all__ = ["EvaluationReportPdfGenerator"]

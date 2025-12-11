"""PDF report generator for metrics evaluation."""

import re
from pathlib import Path
from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    PageBreak,
    Image,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

if TYPE_CHECKING:
    from run_metrics import TestReport


def sanitize_html_for_reportlab(text: str) -> str:
    """
    Sanitize HTML-like text for ReportLab Paragraph while preserving valid formatting.
    
    This function:
    1. Escapes < and > characters in content that aren't part of valid tags
    2. Ensures all formatting tags (<b>, <i>, <br/>) are properly closed
    3. Removes any invalid or unclosed tags
    
    Args:
        text: HTML-like string that may contain formatting tags and content
        
    Returns:
        Sanitized string safe for ReportLab Paragraph parser
    """
    # Protect valid tags by replacing them with placeholders
    tag_placeholders = {}
    placeholder_counter = 0
    
    # Find and protect valid tags: <b>, </b>, <i>, </i>, <br/>, <br>
    def replace_tag(match):
        nonlocal placeholder_counter
        tag = match.group(0)
        placeholder = f"__TAG_{placeholder_counter}__"
        placeholder_counter += 1
        tag_placeholders[placeholder] = tag
        return placeholder
    
    # Protect valid tags
    protected_text = re.sub(
        r'</?(?:b|i|br\s*/?)>',
        replace_tag,
        text,
        flags=re.IGNORECASE
    )
    
    # Escape any remaining < and > in content (these are not valid tags)
    sanitized = protected_text.replace('<', '&lt;').replace('>', '&gt;')
    
    # Restore protected tags
    for placeholder, tag in tag_placeholders.items():
        sanitized = sanitized.replace(placeholder, tag)
    
    # Normalize <br> variations to <br/>
    sanitized = re.sub(r'<br\s*/?>', '<br/>', sanitized, flags=re.IGNORECASE)
    
    # Ensure all <b> and <i> tags are properly closed
    open_b = len(re.findall(r'<b>', sanitized, re.IGNORECASE))
    close_b = len(re.findall(r'</b>', sanitized, re.IGNORECASE))
    open_i = len(re.findall(r'<i>', sanitized, re.IGNORECASE))
    close_i = len(re.findall(r'</i>', sanitized, re.IGNORECASE))
    
    # Close any unclosed tags at the end
    if open_b > close_b:
        sanitized += '</b>' * (open_b - close_b)
    if open_i > close_i:
        sanitized += '</i>' * (open_i - close_i)
    
    return sanitized


def generate_pdf_report(report: "TestReport", output_path: Path) -> None:
    """Generate a PDF report from test results."""
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=18,
    )

    # Container for the 'Flowable' objects
    elements = []

    # Define styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1f4788'),
        spaceAfter=30,
        alignment=TA_CENTER,
    )
    heading_style = styles['Heading2']
    normal_style = styles['Normal']

    # Title
    title = Paragraph("Translation Metrics Evaluation Report", title_style)
    elements.append(title)
    elements.append(Spacer(1, 0.2*inch))

    # Metadata
    timestamp_text = f"<b>Report Generated:</b> {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
    elements.append(Paragraph(timestamp_text, normal_style))
    elements.append(Spacer(1, 0.3*inch))

    # Summary Section
    elements.append(Paragraph("Executive Summary", heading_style))
    elements.append(Spacer(1, 0.1*inch))

    summary = report.summary
    summary_data = [
        ['Metric', 'Value'],
        ['Total Test Cases', str(summary['total_tests'])],
        ['Total Metrics', str(summary['total_metrics'])],
        ['Total Evaluations', str(summary['total_evaluations'])],
        ['Passed Evaluations', f"{summary['passed']} ({summary['pass_rate']*100:.1f}%)"],
        ['Failed Evaluations', str(summary['failed'])],
        ['Average Score', f"{summary['average_score']:.4f}"],
    ]

    # Add latency statistics if available
    latency_stats = summary.get('latency_stats', {})
    if latency_stats and latency_stats.get('count', 0) > 0:
        summary_data.append(['Average Latency', f"{latency_stats['average_ms']:.2f}ms"])
        summary_data.append(['Min Latency', f"{latency_stats['min_ms']:.2f}ms"])
        summary_data.append(['Max Latency', f"{latency_stats['max_ms']:.2f}ms"])

    summary_table = Table(summary_data, colWidths=[3*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4788')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
    ]))

    elements.append(summary_table)
    elements.append(Spacer(1, 0.3*inch))

    # Per-Metric Statistics
    elements.append(Paragraph("Metrics Performance", heading_style))
    elements.append(Spacer(1, 0.1*inch))

    metrics_data = [['Metric Name', 'Passed', 'Failed', 'Pass Rate', 'Avg Score']]

    for metric_name, stats in summary['metric_stats'].items():
        total = stats['passed'] + stats['failed']
        pass_rate = stats['passed'] / total if total > 0 else 0.0

        metrics_data.append([
            metric_name,
            str(stats['passed']),
            str(stats['failed']),
            f"{pass_rate*100:.1f}%",
            f"{stats['average_value']:.4f}"
        ])

    metrics_table = Table(metrics_data, colWidths=[2.5*inch, 0.8*inch, 0.8*inch, 0.9*inch, 1*inch])
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4788')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.lightgrey),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))

    elements.append(metrics_table)
    elements.append(PageBreak())

    # Detailed Test Results
    elements.append(Paragraph("Detailed Test Results", heading_style))
    elements.append(Spacer(1, 0.2*inch))

    for test_case in report.test_cases:
        # Test case header
        test_header = f"<b>Test {test_case.id}:</b> {test_case.name}"
        elements.append(Paragraph(test_header, normal_style))
        elements.append(Spacer(1, 0.05*inch))

        # Expected text
        expected = f"<i>Expected:</i> {test_case.expected_text}"
        elements.append(Paragraph(expected, normal_style))

        test_result = report.test_results.get(test_case.id)

        # Add Recognized text if available on any of the test_results
        recognized_text = None
        if test_result:
            if test_result.recognized_text:
                recognized_text = test_result.recognized_text
        if recognized_text:
            recognized = f"<br/><i>Recognized:</i> {recognized_text}"
            elements.append(Paragraph(recognized, normal_style))

        # Add latency info if available
        if test_result and test_result.latency_ms is not None:
            latency_info = f"<br/><i>Latency:</i> {test_result.latency_ms:.2f}ms"
            elements.append(Paragraph(latency_info, normal_style))

        elements.append(Spacer(1, 0.1*inch))

        # Results table for this test
        test_results = report.metric_results.get(test_case.id, {})

        if test_results:
            results_data = [['Metric', 'Value', 'Status', 'Details']]

            for metric_name, result in test_results.items():
                status = '✓ PASS' if result.passed else '✗ FAIL'
                status_color = colors.green if result.passed else colors.red

                # Format details as Paragraph for text wrapping
                details_str = ""
                if result.details:
                    # Prioritize reasoning field if present (for LLM-based metrics)
                    reasoning = result.details.get('reasoning')
                    if reasoning:
                        details_str = f"<b>Reasoning:</b> {reasoning}<br/>"

                    # Add other details (excluding verbose fields)
                    exclude_keys = {'error', 'reasoning', 'expected_text', 'recognized_text',
                                   'reference_text', 'raw_response', 'key_differences'}
                    other_details = [
                        f"<b>{k}:</b> {v}"
                        for k, v in result.details.items()
                        if k not in exclude_keys and v is not None
                    ]

                    # Add key_differences if present
                    key_diffs = result.details.get('key_differences')
                    if key_diffs and len(key_diffs) > 0:
                        diffs_formatted = ", ".join(key_diffs)
                        other_details.append(f"<b>Differences:</b> {diffs_formatted}")

                    if other_details:
                        if details_str:
                            details_str += "<br/>"
                        details_str += "<br/>".join(other_details)

                # Create Paragraphs for cells that need wrapping
                # Guard against extremely long or malformed "HTML-like" content
                # that can make a single table row taller than the available
                # page height or cause ReportLab parsing errors.
                if details_str:
                    # First, truncate very verbose content to keep row height
                    # reasonable. We truncate on raw text, which may include
                    # simple <b> / <br/> tags, and then render a safe fallback
                    # if the Paragraph parser fails.
                    max_detail_chars = 1200
                    if len(details_str) > max_detail_chars:
                        details_str = details_str[:max_detail_chars] + "... [truncated]"

                    try:
                        # Try rendering with basic inline tags preserved.
                        detail_paragraph = Paragraph(details_str, normal_style)
                    except Exception:
                        # Fallback: sanitize HTML while preserving valid formatting tags
                        # This escapes content that might contain < or >, fixes unclosed tags,
                        # and preserves <b>, <i>, and <br/> formatting
                        sanitized_details = sanitize_html_for_reportlab(details_str)
                        detail_paragraph = Paragraph(sanitized_details, normal_style)
                else:
                    detail_paragraph = ""

                results_data.append([
                    metric_name,
                    f"{result.value:.4f}",
                    status,
                    detail_paragraph
                ])

            # Use None for column width to allow auto-sizing based on content
            results_table = Table(results_data, colWidths=[1.5*inch, 0.8*inch, 0.8*inch, 3.9*inch])

            # Build table style with conditional coloring
            table_style = [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a6fa5')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]

            # Add row-specific styling based on pass/fail
            for idx, (metric_name, result) in enumerate(test_results.items(), start=1):
                if result.passed:
                    table_style.append(('BACKGROUND', (0, idx), (-1, idx), colors.lightgreen))
                    table_style.append(('TEXTCOLOR', (2, idx), (2, idx), colors.darkgreen))
                else:
                    table_style.append(('BACKGROUND', (0, idx), (-1, idx), colors.lightpink))
                    table_style.append(('TEXTCOLOR', (2, idx), (2, idx), colors.darkred))

            results_table.setStyle(TableStyle(table_style))
            elements.append(results_table)

        elements.append(Spacer(1, 0.3*inch))

    # Build PDF
    doc.build(elements)


if __name__ == "__main__":
    print("This module should be imported and used by run_metrics.py")

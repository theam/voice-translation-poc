"""Shared helpers for reporting layouts."""
from __future__ import annotations

from typing import Any, Iterable, List, Tuple

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import Table, TableStyle


def score_color_band(score: float | None) -> colors.Color:
    """Map a 0-100 score to a color band (red→orange→yellow→green).

    Args:
        score: Score value in [0, 1]; None yields neutral gray.

    Returns:
        reportlab color instance
    """
    if score is None:
        return colors.HexColor("#f2f2f2")
    if score < 25:
        return colors.HexColor("#f8a5a5")  # red-ish
    if score < 50:
        return colors.HexColor("#f5c16c")  # orange
    if score < 75:
        return colors.HexColor("#ffe28a")  # yellow
    return colors.HexColor("#a8e6a1")      # green


def create_standard_table(
    table_data: List[List[Any]],
    num_columns: int,
    total_width_inch: float = 6.0,
    header_color: colors.Color = colors.HexColor("#1f4788"),
    extra_styles: Iterable[Tuple] | None = None,
) -> Table:
    """Create a table with shared styling and evenly divided widths."""
    col_width = (total_width_inch * inch) / num_columns
    table = Table(table_data, colWidths=[col_width] * num_columns)

    base_style: List[Tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if extra_styles:
        base_style.extend(list(extra_styles))

    table.setStyle(TableStyle(base_style))
    return table


def sanitize_html_for_reportlab(text: str) -> str:
    """Escape angle brackets while preserving simple formatting tags."""
    import re

    tag_placeholders = {}
    placeholder_counter = 0

    def replace_tag(match: Any) -> str:
        nonlocal placeholder_counter
        tag = match.group(0)
        placeholder = f"__TAG_{placeholder_counter}__"
        placeholder_counter += 1
        tag_placeholders[placeholder] = tag
        return placeholder

    protected_text = re.sub(r"</?(?:b|i|br\s*/?)>", replace_tag, text, flags=re.IGNORECASE)
    sanitized = protected_text.replace("<", "&lt;").replace(">", "&gt;")

    for placeholder, tag in tag_placeholders.items():
        sanitized = sanitized.replace(placeholder, tag)

    sanitized = re.sub(r"<br\s*/?>", "<br/>", sanitized, flags=re.IGNORECASE)

    open_b = len(re.findall(r"<b>", sanitized, re.IGNORECASE))
    close_b = len(re.findall(r"</b>", sanitized, re.IGNORECASE))
    open_i = len(re.findall(r"<i>", sanitized, re.IGNORECASE))
    close_i = len(re.findall(r"</i>", sanitized, re.IGNORECASE))

    if open_b > close_b:
        sanitized += "</b>" * (open_b - close_b)
    if open_i > close_i:
        sanitized += "</i>" * (open_i - close_i)

    return sanitized


__all__ = ["score_color_band", "sanitize_html_for_reportlab", "create_standard_table"]

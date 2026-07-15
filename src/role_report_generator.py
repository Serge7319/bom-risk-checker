"""Cadivor Milestone 12.1 — Role-based professional report exports."""
from __future__ import annotations

from io import BytesIO
from typing import Iterable

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def build_role_report_pdf(
    *,
    title: str,
    subtitle: str,
    project_name: str,
    dataframe: pd.DataFrame,
    summary_lines: Iterable[str] | None = None,
) -> bytes:
    """Create a compact customer-facing PDF for a role-specific report."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=30,
        leftMargin=30,
        topMargin=28,
        bottomMargin=28,
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="CadivorRoleTitle",
            parent=styles["Title"],
            fontSize=20,
            leading=24,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#0F172A"),
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CadivorRoleSub",
            parent=styles["BodyText"],
            fontSize=9,
            leading=13,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#52647A"),
            spaceAfter=14,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CadivorRoleBody",
            parent=styles["BodyText"],
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#334155"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="CadivorRoleCell",
            parent=styles["BodyText"],
            fontSize=6.5,
            leading=8,
            textColor=colors.HexColor("#1E293B"),
        )
    )

    story = [
        Paragraph(title, styles["CadivorRoleTitle"]),
        Paragraph(
            f"<b>Project:</b> {project_name}<br/>{subtitle}",
            styles["CadivorRoleSub"],
        ),
    ]

    for line in summary_lines or []:
        story.append(Paragraph(str(line), styles["CadivorRoleBody"]))
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 8))

    frame = dataframe.copy() if isinstance(dataframe, pd.DataFrame) else pd.DataFrame()
    if frame.empty:
        story.append(
            Paragraph("No records are available for this report.", styles["CadivorRoleBody"])
        )
    else:
        visible = frame.head(30).fillna("—").astype(str)
        headers = [
            Paragraph(f"<b>{column}</b>", styles["CadivorRoleCell"])
            for column in visible.columns
        ]
        rows = [
            [Paragraph(value, styles["CadivorRoleCell"]) for value in row]
            for row in visible.values.tolist()
        ]

        usable_width = 720
        count = max(1, len(headers))
        widths = [usable_width / count] * count
        table = Table([headers] + rows, colWidths=widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF2FF")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                        colors.white,
                        colors.HexColor("#F8FAFC"),
                    ]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(table)

    doc.build(story)
    return buffer.getvalue()

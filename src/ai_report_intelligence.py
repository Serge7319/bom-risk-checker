"""Milestone 12.0C — AI Executive & Procurement Report Intelligence."""
from __future__ import annotations

from io import BytesIO
from typing import Any, Dict

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

from src.engineering_decision_engine import format_decision_brief_for_report


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except Exception:
        return default


def _text(value: Any, default: str = "—") -> str:
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def _column(df: pd.DataFrame, *names: str):
    for name in names:
        if name in df.columns:
            return df[name]
    return pd.Series(dtype="object")


def build_ai_report_intelligence(
    analysis: Dict[str, Any],
    parts_df: pd.DataFrame,
) -> Dict[str, Any]:
    parts_df = parts_df.copy() if isinstance(parts_df, pd.DataFrame) else pd.DataFrame()

    project = _text(analysis.get("project_name") or analysis.get("name"), "Saved BOM")
    health = int(_num(analysis.get("health_score"), 0))
    high = int(_num(analysis.get("high_risk_count") or analysis.get("high_risk_parts"), 0))
    medium = int(_num(analysis.get("medium_risk_count") or analysis.get("medium_risk_parts"), 0))
    part_count = int(
        _num(
            analysis.get("part_count")
            or analysis.get("total_parts")
            or analysis.get("parts_count"),
            len(parts_df),
        )
    )

    lifecycle = _column(parts_df, "lifecycle_status", "Lifecycle Status").astype(str).str.lower()
    risk = _column(parts_df, "risk_level", "Risk Level").astype(str).str.lower()
    stock = pd.to_numeric(
        _column(parts_df, "stock_available", "Stock Available", "stock"),
        errors="coerce",
    ).fillna(0)
    suppliers = pd.to_numeric(
        _column(parts_df, "supplier_count", "Supplier Count"),
        errors="coerce",
    ).fillna(0)
    lead = pd.to_numeric(
        _column(parts_df, "lead_time_weeks", "Lead Time Weeks", "lead_time"),
        errors="coerce",
    ).fillna(0)

    lifecycle_concerns = int(
        lifecycle.str.contains(
            "obsolete|eol|end of life|replacement|nrnd|not recommended",
            regex=True,
            na=False,
        ).sum()
    )
    no_stock = int((stock <= 0).sum()) if len(stock) else 0
    limited_sources = int((suppliers <= 1).sum()) if len(suppliers) else 0
    long_lead = int((lead >= 12).sum()) if len(lead) else 0

    blockers = no_stock + int((risk == "high").sum())
    readiness = (
        "Blocked for production"
        if blockers >= 2
        else "Production approval required"
        if blockers or lifecycle_concerns
        else "Production ready with monitoring"
    )

    engineering_hours = high * 5 + medium * 2 + lifecycle_concerns * 3
    procurement_hours = no_stock * 2 + limited_sources * 1 + long_lead * 1
    projected_health = min(
        100,
        health
        + min(12, high * 4 + medium * 2 + lifecycle_concerns * 2 + no_stock * 2),
    )

    executive_summary = (
        f"{project} contains {part_count} components and currently scores {health}/100. "
        f"The BOM is classified as {readiness.lower()}. "
        f"Cadivor identified {high} high-risk, {medium} medium-risk, "
        f"{lifecycle_concerns} lifecycle-exposed, {no_stock} no-stock, and "
        f"{limited_sources} limited-source components. "
        f"Completing the priority engineering and sourcing actions is projected to improve "
        f"BOM health to approximately {projected_health}/100."
    )

    executive_decision = (
        "Do not authorize unrestricted production purchasing until the listed blockers are resolved."
        if blockers
        else "Authorize the next build with controlled lifecycle and supplier monitoring."
    )

    procurement_summary = (
        f"Procurement should prioritize {no_stock} immediate availability issue(s), "
        f"{limited_sources} limited-source component(s), and {long_lead} long-lead component(s). "
        f"Estimated procurement review effort is approximately {procurement_hours} hour(s)."
    )

    procurement_actions = []
    if no_stock:
        procurement_actions.append(
            f"Secure inventory or an approved substitute for {no_stock} no-stock component(s)."
        )
    if limited_sources:
        procurement_actions.append(
            f"Approve secondary sourcing coverage for {limited_sources} limited-source component(s)."
        )
    if long_lead:
        procurement_actions.append(
            f"Align purchasing dates and buffer strategy for {long_lead} long-lead component(s)."
        )
    if lifecycle_concerns:
        procurement_actions.append(
            f"Avoid new long-term commitments on {lifecycle_concerns} lifecycle-exposed component(s)."
        )
    if not procurement_actions:
        procurement_actions.append("Continue routine supplier and stock monitoring.")

    return {
        "project": project,
        "health": health,
        "projected_health": projected_health,
        "part_count": part_count,
        "high": high,
        "medium": medium,
        "readiness": readiness,
        "executive_summary": executive_summary,
        "executive_decision": executive_decision,
        "procurement_summary": procurement_summary,
        "procurement_actions": procurement_actions,
        "engineering_hours": engineering_hours,
        "procurement_hours": procurement_hours,
        "lifecycle_concerns": lifecycle_concerns,
        "no_stock": no_stock,
        "limited_sources": limited_sources,
        "long_lead": long_lead,
    }


def _base_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="CadivorTitle",
            parent=styles["Title"],
            fontSize=22,
            leading=27,
            textColor=colors.HexColor("#0F172A"),
            alignment=TA_CENTER,
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CadivorSection",
            parent=styles["Heading2"],
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#1D4ED8"),
            spaceBefore=12,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CadivorBody",
            parent=styles["BodyText"],
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#334155"),
        )
    )
    return styles


def _metric_table(report: Dict[str, Any]) -> Table:
    data = [
        ["Health", "Projected Health", "High Risk", "Medium Risk"],
        [
            f"{report['health']}/100",
            f"{report['projected_health']}/100",
            str(report["high"]),
            str(report["medium"]),
        ],
    ]
    table = Table(data, colWidths=[115, 115, 115, 115])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF2FF")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return table


def _decision_brief_pdf_sections(decision_brief: Dict[str, Any], styles) -> list:
    """Append Sprint 67 decision brief sections to a ReportLab story."""
    sections = format_decision_brief_for_report(decision_brief)
    blocks = [
        ("Executive Engineering Summary", sections["executive_summary"]),
        ("Production Readiness", sections["production_readiness"]),
        ("Critical Findings", sections["critical_findings"]),
        ("Recommended Actions", sections["recommended_actions"]),
        ("Business Impact", sections["business_impact"]),
        ("Engineering Confidence", sections["confidence"]),
        ("Supporting Evidence", sections["supporting_evidence"]),
    ]
    story = []
    for title, body in blocks:
        story.append(Paragraph(title, styles["CadivorSection"]))
        story.append(Paragraph(body.replace("\n", "<br/>"), styles["CadivorBody"]))
        story.append(Spacer(1, 10))
    return story


def build_ai_executive_pdf(
    report: Dict[str, Any],
    decision_brief: Dict[str, Any] | None = None,
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=42,
        leftMargin=42,
        topMargin=42,
        bottomMargin=42,
    )
    styles = _base_styles()
    story = [
        Paragraph("Cadivor AI Executive BOM Brief", styles["CadivorTitle"]),
        Paragraph(f"<b>Project:</b> {report['project']}", styles["CadivorBody"]),
        Spacer(1, 10),
        _metric_table(report),
        Spacer(1, 16),
    ]
    if decision_brief:
        story.extend(_decision_brief_pdf_sections(decision_brief, styles))
    else:
        story.extend(
            [
                Paragraph("Production Readiness", styles["CadivorSection"]),
                Paragraph(report["readiness"], styles["CadivorBody"]),
                Paragraph("Executive Assessment", styles["CadivorSection"]),
                Paragraph(report["executive_summary"], styles["CadivorBody"]),
                Paragraph("Recommended Management Decision", styles["CadivorSection"]),
                Paragraph(report["executive_decision"], styles["CadivorBody"]),
                Paragraph("Estimated Resolution Effort", styles["CadivorSection"]),
                Paragraph(
                    f"Engineering: approximately {report['engineering_hours']} hours. "
                    f"Procurement: approximately {report['procurement_hours']} hours.",
                    styles["CadivorBody"],
                ),
            ]
        )
    doc.build(story)
    return buffer.getvalue()


def build_ai_procurement_pdf(report: Dict[str, Any]) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=42,
        leftMargin=42,
        topMargin=42,
        bottomMargin=42,
    )
    styles = _base_styles()
    action_rows = [["Priority Procurement Actions"]]
    for action in report["procurement_actions"]:
        action_rows.append([f"• {action}"])

    action_table = Table(action_rows, colWidths=[475])
    action_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF2FF")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )

    story = [
        Paragraph("Cadivor AI Procurement Brief", styles["CadivorTitle"]),
        Paragraph(f"<b>Project:</b> {report['project']}", styles["CadivorBody"]),
        Spacer(1, 10),
        _metric_table(report),
        Spacer(1, 16),
        Paragraph("Procurement Assessment", styles["CadivorSection"]),
        Paragraph(report["procurement_summary"], styles["CadivorBody"]),
        Spacer(1, 12),
        action_table,
        Paragraph("Exposure Summary", styles["CadivorSection"]),
        Paragraph(
            f"No-stock components: {report['no_stock']}<br/>"
            f"Limited-source components: {report['limited_sources']}<br/>"
            f"Long-lead components: {report['long_lead']}<br/>"
            f"Lifecycle-exposed components: {report['lifecycle_concerns']}",
            styles["CadivorBody"],
        ),
    ]
    doc.build(story)
    return buffer.getvalue()

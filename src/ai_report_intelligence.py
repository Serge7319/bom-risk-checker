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
    """Create a report from the current per-field supplier evidence.

    Saved aggregate labels are not evidence. Recompute risk and health from
    component records, and leave projections, effort and release approval
    unscored because the inputs needed to support them are not available here.
    """
    from apps.api.evidence_contract import EVIDENCE_LIVE, classify_part_evidence
    from integrations.stock_coercion import parse_stock_total
    from src.health_score import calculate_bom_health_score
    from src.risk_engine import _coverage_complete, calculate_risk

    parts_df = parts_df.copy() if isinstance(parts_df, pd.DataFrame) else pd.DataFrame()

    project = _text(analysis.get("project_name") or analysis.get("name"), "Saved BOM")
    records = parts_df.to_dict("records") if not parts_df.empty else []
    part_count = len(records)
    assessments = []
    lifecycle_concerns = no_stock = limited_sources = long_lead = needs_verification = 0
    procurement_actions: list[str] = []
    for part in records:
        assessment = calculate_risk(part)
        assessments.append(assessment)
        fields = classify_part_evidence(part).get("fields") or {}
        lifecycle = fields.get("lifecycle") if isinstance(fields.get("lifecycle"), dict) else {}
        stock = fields.get("stock") if isinstance(fields.get("stock"), dict) else {}
        identity = fields.get("identity") if isinstance(fields.get("identity"), dict) else {}
        lead = fields.get("lead_time") if isinstance(fields.get("lead_time"), dict) else {}
        coverage_complete, _ = _coverage_complete(part)
        if assessment.get("risk_level") == "Needs verification":
            needs_verification += 1
        lifecycle_value = str(part.get("Lifecycle") or part.get("lifecycle_status") or part.get("Lifecycle Status") or "").casefold()
        if lifecycle.get("evidence_class") == EVIDENCE_LIVE and any(
            token in lifecycle_value for token in ("obsolete", "end of life", "eol", "discontinued", "nrnd", "not recommended")
        ):
            lifecycle_concerns += 1
        stock_total = parse_stock_total(stock.get("observed_total", stock.get("reported_value")))
        if stock.get("evidence_class") == EVIDENCE_LIVE and stock.get("complete") and stock_total == 0:
            no_stock += 1
        supplier_count = _num(part.get("Supplier Count", part.get("supplier_count")), float("nan"))
        if identity.get("evidence_class") == EVIDENCE_LIVE and coverage_complete and pd.notna(supplier_count) and supplier_count <= 1:
            limited_sources += 1
        lead_value = _num(part.get("Lead Time Weeks", part.get("lead_time_weeks")), float("nan"))
        if lead.get("evidence_class") == EVIDENCE_LIVE and pd.notna(lead_value) and lead_value >= 12:
            long_lead += 1

    risk_levels = [assessment.get("risk_level") for assessment in assessments]
    high = sum(level == "High" for level in risk_levels)
    medium = sum(level == "Medium" for level in risk_levels)
    health_result = calculate_bom_health_score(parts_df) if not parts_df.empty else {"health_score": None}
    health = health_result.get("health_score")
    readiness = (
        "Supplier evidence requires verification"
        if needs_verification
        else "Supplier checks complete; engineering release review required"
    )

    executive_summary = (
        f"{project} contains {part_count} component(s). BOM health is "
        f"{f'{health}/100' if health is not None else 'not scored'} because it is calculated only when evidence coverage is complete. "
        f"Current verified supplier signals include {high} high-risk, {medium} medium-risk, "
        f"{lifecycle_concerns} lifecycle concerns, {no_stock} complete checks reporting zero inventory, "
        f"and {limited_sources} single-source or unmatched parts after completed checks. "
        f"{needs_verification} component(s) need evidence verification. This report does not approve design fit or production release."
    )

    executive_decision = (
        "Review the exact source records, resolve evidence gaps, and complete your organization’s engineering, quality, and procurement release approvals. "
        "A supplier catalog match is not checkout confirmation or design qualification."
    )

    procurement_summary = (
        f"Verified supplier signals: {no_stock} complete checks reported zero inventory, "
        f"{limited_sources} components had at most one exact source after complete checks, "
        f"and {long_lead} components had verified lead time of at least 12 weeks. "
        f"{needs_verification} component(s) need supplier evidence verification. Procurement effort is not estimated."
    )

    procurement_actions = []
    if needs_verification:
        procurement_actions.append(
            f"Refresh exact-part supplier checks and verify source coverage and field timestamps for {needs_verification} component(s)."
        )
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
        procurement_actions.append("Review supplier source records before making a purchase commitment.")

    return {
        "project": project,
        "health": health,
        "projected_health": None,
        "part_count": part_count,
        "high": high,
        "medium": medium,
        "readiness": readiness,
        "executive_summary": executive_summary,
        "executive_decision": executive_decision,
        "procurement_summary": procurement_summary,
        "procurement_actions": procurement_actions,
        "engineering_hours": None,
        "procurement_hours": None,
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
            f"{report['health']}/100" if report.get("health") is not None else "Not scored",
            "Not estimated",
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
                Paragraph("Resolution Effort", styles["CadivorSection"]),
                Paragraph(
                    "Effort has not been estimated. Assign engineering and procurement owners "
                    "to size the work for the specific component and release plan.",
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
            f"Verified zero-stock components: {report['no_stock']}<br/>"
            f"Limited-source components: {report['limited_sources']}<br/>"
            f"Long-lead components: {report['long_lead']}<br/>"
            f"Lifecycle-exposed components: {report['lifecycle_concerns']}",
            styles["CadivorBody"],
        ),
    ]
    doc.build(story)
    return buffer.getvalue()

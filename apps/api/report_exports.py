"""Authenticated BOM report exports for the Next.js workspace app."""
from __future__ import annotations

import csv
import re
from io import BytesIO, StringIO
from typing import Any
from xml.sax.saxutils import escape


COMPONENT_COLUMNS = (
    "MPN",
    "Manufacturer",
    "Description",
    "Parent MPN",
    "Line Type",
    "Quantity per Parent",
    "Effective Quantity",
    "Lifecycle",
    "Risk Level",
    "Risk Score",
    "Risk Reasons",
    "Stock",
    "Unit Price",
    "Currency",
    "Evidence Class",
    "Evidence Source",
    "Supplier Product URL",
    "Datasheet URL",
)


def _first(row: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return default


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return str(value)
    return str(value)


def _safe_spreadsheet_value(value: Any) -> Any:
    """Keep untrusted BOM text from being evaluated as a spreadsheet formula."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _component_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for source in report.get("parts") or []:
        if not isinstance(source, dict):
            continue
        row = dict(source)
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        output.append(
            {
                "MPN": _first(row, "MPN", "mpn", "manufacturer_part_number", "part_number"),
                "Manufacturer": _first(row, "Manufacturer", "manufacturer"),
                "Description": _first(row, "Description", "description", "part_description"),
                "Parent MPN": _first(row, "Parent MPN", "parent_mpn"),
                "Line Type": _first(row, "Line Type", "line_type"),
                "Quantity per Parent": _first(row, "quantity_per_parent", "Quantity per parent", "Quantity", "quantity", "qty"),
                "Effective Quantity": _first(row, "effective_quantity", "Effective Quantity", "Quantity", "quantity", "qty"),
                "Lifecycle": _first(row, "Lifecycle", "lifecycle_status", "Lifecycle Status"),
                "Risk Level": _first(row, "Risk Level", "risk_level"),
                "Risk Score": _first(row, "Risk Score", "risk_score"),
                "Risk Reasons": _first(row, "Risk Reasons", "risk_reasons", "reasons"),
                "Stock": _first(row, "Stock", "stock_available", "stock"),
                "Unit Price": _first(row, "Unit Price", "unit_price"),
                "Currency": _first(row, "unit_price_currency", "currency"),
                "Evidence Class": _first(evidence, "evidence_class", default=_first(row, "evidence_source", "source", "price_source", default="not recorded")),
                "Evidence Source": _first(evidence, "source", default=_first(row, "evidence_source", "source", "price_source")),
                "Supplier Product URL": _first(row, "product_url", "source_url", "Supplier Product URL"),
                "Datasheet URL": _first(row, "datasheet_url", "Datasheet URL"),
            }
        )
    return output


def _metadata(report: dict[str, Any]) -> dict[str, str]:
    return {
        "Project": _text(_first(report, "project_name", default="Saved BOM")),
        "BOM": _text(_first(report, "bom_name", "filename", default="Saved BOM")),
        "Revision": _text(_first(report, "revision", default="—")),
        "Analyzed At": _text(_first(report, "created_at", default="—")),
    }


def _synthetic_disclaimer(report: dict[str, Any]) -> str:
    if str(report.get("mode") or "").casefold() == "synthetic-preview":
        return (
            "This report uses synthetic preview analysis. Stock, price, and lifecycle "
            "values are not live supplier verification; confirm primary-source evidence "
            "before making a sourcing or release decision."
        )
    summary = report.get("evidence_summary") or {}
    if isinstance(summary, dict):
        return (
            f"Evidence labels: {summary.get('live_count', 0)} live-authorized, "
            f"{summary.get('synthetic_count', 0)} synthetic, "
            f"{summary.get('missing_count', 0)} missing. Review the source and retrieval "
            "date for each component before acting."
        )
    return "Review each component's evidence source and retrieval date before acting."


def build_csv(report: dict[str, Any]) -> bytes:
    """Build an evidence-labeled, spreadsheet-safe component audit CSV."""
    fields = (*_metadata(report).keys(), *COMPONENT_COLUMNS)
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    metadata = _metadata(report)
    for component in _component_rows(report):
        writer.writerow(
            {
                **{key: _safe_spreadsheet_value(value) for key, value in metadata.items()},
                **{
                    key: _safe_spreadsheet_value(_text(value))
                    for key, value in component.items()
                },
            }
        )
    return output.getvalue().encode("utf-8-sig")


def _needs_verification_count(report: dict[str, Any]) -> int:
    known = report.get("needs_verification_count")
    if known is not None and str(known).strip() != "":
        try:
            return int(known)
        except (TypeError, ValueError):
            pass
    count = 0
    for part in report.get("parts") or []:
        if not isinstance(part, dict):
            continue
        level = str(part.get("Risk Level") or part.get("risk_level") or "").casefold()
        verified = bool(part.get("Supplier Data Verified") if "Supplier Data Verified" in part else part.get("supplier_data_verified"))
        if "verif" in level or not verified:
            count += 1
    return count


def _risk_priority(level: str) -> int:
    folded = str(level or "").casefold()
    if "high" in folded or "critical" in folded:
        return 0
    if "medium" in folded or folded == "med":
        return 1
    if "verif" in folded or "unassess" in folded or "not assess" in folded:
        return 2
    if "low" in folded or "healthy" in folded:
        return 4
    return 3


def _prioritized_review_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """High/medium scored risks first, then Needs verification — never treat blank scores as Low."""
    selected = [
        row
        for row in rows
        if _risk_priority(_text(row.get("Risk Level"))) <= 2
    ]
    return sorted(
        selected,
        key=lambda row: (
            _risk_priority(_text(row.get("Risk Level"))),
            -float(row.get("Risk Score") or 0),
            _text(row.get("MPN")),
        ),
    )


def _recommended_action(row: dict[str, Any]) -> str:
    level = _text(row.get("Risk Level")).casefold()
    evidence = _text(row.get("Evidence Class")).casefold()
    if "verif" in level or evidence in {"missing", "not recorded", ""}:
        return (
            "Recommended action: confirm the full manufacturer part number against "
            "authorized-distributor evidence, then re-run analysis before scoring risk."
        )
    if "high" in level:
        return (
            "Recommended action: prioritize lifecycle/stock mitigation and evaluate "
            "approved alternatives before release."
        )
    if "medium" in level:
        return (
            "Recommended action: review supplier coverage and lead-time evidence; "
            "plan dual-source or buffer stock if quantity coverage is thin."
        )
    return ""


def build_xlsx(report: dict[str, Any]) -> bytes:
    """Build the mature Cadivor risk workbook used by Streamlit, plus Next.js evidence labels.

    Reuses ``detailed_risk_excel_bytes`` so exports keep prioritized risks, lifecycle /
    supplier findings, cost exposure, and alternative-candidate sheets instead of a
    thin Summary+Components-only workbook.
    """
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from src.ui.detailed_risk_export import detailed_risk_excel_bytes

    meta = _metadata(report)
    project = meta.get("Project") or ""
    bom = meta.get("BOM") or "Saved BOM"
    bom_name = f"{project} — {bom}" if project and project != bom else bom
    workbook_bytes = detailed_risk_excel_bytes(
        list(report.get("parts") or []),
        bom_name=bom_name,
        source_filename=_text(report.get("filename") or bom),
        analyzed_on=report.get("created_at") or "",
    )
    workbook = load_workbook(BytesIO(workbook_bytes))
    summary = workbook["Summary"]
    # Preserve the Streamlit summary metrics, then append Next.js evidence / health
    # facts so unscored BOMs are not mistaken for zero-risk.
    summary["A2"] = _synthetic_disclaimer(report)
    summary["A2"].font = Font(name="Aptos", size=10, color="8A4B08", italic=True)
    summary["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    summary.row_dimensions[2].height = max(int(summary.row_dimensions[2].height or 0), 48)

    needs_verification = _needs_verification_count(report)
    health_score = report.get("health_score")
    health_display = (
        health_score
        if health_score is not None and str(health_score).strip() != ""
        else "Not scored — supplier evidence incomplete"
    )
    extras = [
        ("Evidence mode", report.get("mode") or "Not reported"),
        ("Health score", health_display),
        ("Health status", report.get("health_status") or "Not reported"),
        (
            "Needs verification",
            (
                f"{needs_verification} of {len(report.get('parts') or [])} "
                "(unscored parts are not low risk)"
            ),
        ),
        (
            "Scored risk counts (High / Medium / Low)",
            (
                f"{int(report.get('high_risk_count') or 0)} / "
                f"{int(report.get('medium_risk_count') or 0)} / "
                f"{int(report.get('low_risk_count') or 0)}"
            ),
        ),
    ]
    start_row = int(summary.max_row or 1) + 2
    summary.cell(start_row - 1, 1, "Workspace analysis evidence")
    summary.cell(start_row - 1, 1).font = Font(name="Aptos", size=11, bold=True, color="17324D")
    summary.merge_cells(start_row=start_row - 1, start_column=1, end_row=start_row - 1, end_column=2)
    for offset, (label, value) in enumerate(extras):
        row_index = start_row + offset
        summary.cell(row_index, 1, label)
        summary.cell(row_index, 2, _safe_spreadsheet_value(_text(value)))
        summary.cell(row_index, 1).font = Font(name="Aptos", size=10, bold=True, color="17324D")
        summary.cell(row_index, 2).font = Font(name="Aptos", size=10, color="334155")
        summary.cell(row_index, 2).alignment = Alignment(wrap_text=True, vertical="top")
        if "Needs verification" in label and needs_verification:
            summary.cell(row_index, 1).fill = PatternFill("solid", fgColor="FFF7ED")
            summary.cell(row_index, 2).fill = PatternFill("solid", fgColor="FFF7ED")

    # Keep a thin Components sheet for callers/tests that still look for it, while
    # the mature Component Details / High Risk / Alternatives sheets remain primary.
    if "Components" not in workbook.sheetnames:
        components = workbook.create_sheet("Components")
        components.sheet_view.showGridLines = False
        for column, name in enumerate(COMPONENT_COLUMNS, start=1):
            cell = components.cell(1, column, name)
            cell.font = Font(name="Aptos", size=10, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="17324D")
        for row_index, component in enumerate(_component_rows(report), start=2):
            for column, name in enumerate(COMPONENT_COLUMNS, start=1):
                components.cell(
                    row_index,
                    column,
                    _safe_spreadsheet_value(_text(component.get(name))),
                )

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_pdf(report: dict[str, Any]) -> bytes:
    """Build a multi-page PDF summary and component risk table."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

    rows = _component_rows(report)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(letter), leftMargin=28, rightMargin=28,
        topMargin=34, bottomMargin=34,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CadivorExportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=colors.HexColor("#17324D"), alignment=TA_LEFT, spaceAfter=6))
    styles.add(ParagraphStyle(name="CadivorExportBody", parent=styles["BodyText"], fontSize=8.5, leading=11, textColor=colors.HexColor("#334155"), spaceAfter=4))
    styles.add(ParagraphStyle(name="CadivorExportSmall", parent=styles["BodyText"], fontSize=7, leading=9, textColor=colors.HexColor("#334155")))
    styles.add(ParagraphStyle(name="CadivorExportHead", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7, leading=8, textColor=colors.white))

    metadata = _metadata(report)
    story = [
        Paragraph("Cadivor BOM Risk Report", styles["CadivorExportTitle"]),
        Paragraph(
            "<b>Project:</b> " + escape(metadata["Project"]) +
            " &nbsp;&nbsp; <b>BOM:</b> " + escape(metadata["BOM"]) +
            " &nbsp;&nbsp; <b>Revision:</b> " + escape(metadata["Revision"]),
            styles["CadivorExportBody"],
        ),
        Paragraph(
            "<b>Health:</b> "
            + escape(
                _text(
                    report.get("health_score")
                    if report.get("health_score") is not None
                    else "Not scored — evidence incomplete"
                )
            )
            + " &nbsp;&nbsp; <b>Status:</b> "
            + escape(_text(report.get("health_status") or "Not reported"))
            + " &nbsp;&nbsp; <b>Components:</b> "
            + str(len(rows))
            + " &nbsp;&nbsp; <b>Needs verification:</b> "
            + escape(_text(_needs_verification_count(report)))
            + " &nbsp;&nbsp; <b>Scored High / Medium / Low:</b> "
            + " / ".join(
                escape(_text(report.get(key, 0)))
                for key in ("high_risk_count", "medium_risk_count", "low_risk_count")
            )
            + " (zeros mean no scored parts when verification is outstanding)",
            styles["CadivorExportBody"],
        ),
        Paragraph(escape(_synthetic_disclaimer(report)), styles["CadivorExportBody"]),
        Spacer(1, 8),
    ]

    prioritized = _prioritized_review_rows(rows)
    if prioritized:
        story.append(
            Paragraph(
                "<b>Prioritized review</b> — high / medium risk first, then parts that still need supplier verification.",
                styles["CadivorExportBody"],
            )
        )
        priority_headers = ("Priority", "MPN", "Risk", "Lifecycle", "Evidence", "Why / recommended action")
        priority_data: list[list[Any]] = [
            [Paragraph(escape(name), styles["CadivorExportHead"]) for name in priority_headers]
        ]
        for index, row in enumerate(prioritized, start=1):
            action = _recommended_action(row)
            why = _text(row.get("Risk Reasons")) or "No risk explanation was saved for this component."
            priority_data.append(
                [
                    Paragraph(escape(str(index)), styles["CadivorExportSmall"]),
                    Paragraph(escape(_text(row["MPN"])), styles["CadivorExportSmall"]),
                    Paragraph(escape(_text(row["Risk Level"])), styles["CadivorExportSmall"]),
                    Paragraph(escape(_text(row["Lifecycle"])), styles["CadivorExportSmall"]),
                    Paragraph(escape(_text(row["Evidence Class"])), styles["CadivorExportSmall"]),
                    Paragraph(escape(f"{why} {action}".strip()), styles["CadivorExportSmall"]),
                ]
            )
        priority_table = LongTable(
            priority_data,
            colWidths=[0.55 * inch, 1.1 * inch, 0.85 * inch, 0.85 * inch, 0.95 * inch, 4.0 * inch],
            repeatRows=1,
            hAlign="LEFT",
            splitByRow=1,
        )
        priority_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7C2D12")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#FDBA74")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#FFF7ED"), colors.white]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(priority_table)
        story.append(Spacer(1, 10))

    headers = ("MPN", "Manufacturer / description", "Parent", "Qty", "Lifecycle", "Risk", "Evidence", "Risk reasons")
    data: list[list[Any]] = [[Paragraph(escape(name), styles["CadivorExportHead"]) for name in headers]]
    for row in rows:
        data.append(
            [
                Paragraph(escape(_text(row["MPN"])), styles["CadivorExportSmall"]),
                Paragraph(escape(" · ".join(filter(None, (_text(row["Manufacturer"]), _text(row["Description"]))))), styles["CadivorExportSmall"]),
                Paragraph(escape(_text(row["Parent MPN"])), styles["CadivorExportSmall"]),
                Paragraph(escape(_text(row["Effective Quantity"])), styles["CadivorExportSmall"]),
                Paragraph(escape(_text(row["Lifecycle"])), styles["CadivorExportSmall"]),
                Paragraph(escape(_text(row["Risk Level"])), styles["CadivorExportSmall"]),
                Paragraph(escape(_text(row["Evidence Class"])), styles["CadivorExportSmall"]),
                Paragraph(escape(_text(row["Risk Reasons"])), styles["CadivorExportSmall"]),
            ]
        )
    if len(data) == 1:
        data.append([Paragraph("No component rows are present in this report.", styles["CadivorExportSmall"])] + [""] * (len(headers) - 1))
    widths = [0.95 * inch, 1.8 * inch, 0.78 * inch, 0.48 * inch, 0.78 * inch, 0.52 * inch, 0.88 * inch, 2.05 * inch]
    table = LongTable(data, colWidths=widths, repeatRows=1, hAlign="LEFT", splitByRow=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9E2EC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)

    def footer(canvas: Any, page: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(28, 18, "Cadivor · Evidence-linked engineering review")
        canvas.drawRightString(landscape(letter)[0] - 28, 18, f"Page {page.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def build_report_export(report: dict[str, Any], file_format: str) -> tuple[bytes, str, str]:
    normalized = file_format.strip().lower()
    builders = {
        "csv": (build_csv, "text/csv; charset=utf-8", "csv"),
        "xlsx": (build_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
        "pdf": (build_pdf, "application/pdf", "pdf"),
    }
    if normalized not in builders:
        raise ValueError("Choose one of the supported export formats: PDF, Excel, or CSV.")
    builder, media_type, extension = builders[normalized]
    return builder(report), media_type, extension


def safe_download_stem(report: dict[str, Any]) -> str:
    raw = _text(_first(report, "bom_name", "filename", "project_name", default="cadivor-report"))
    leaf = raw.rsplit("/", 1)[-1]
    leaf = re.sub(r"\.(?:csv|xlsx|xls)$", "", leaf, flags=re.IGNORECASE)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", leaf).strip(".-_")
    return (stem[:80] or "cadivor-report") + "-risk-report"

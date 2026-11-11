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
    "Identity Source",
    "Identity Retrieved At",
    "Lifecycle Source",
    "Lifecycle Retrieved At",
    "Stock Source",
    "Stock Retrieved At",
    "Price Source",
    "Price Type",
    "Price Retrieved At",
    "Supplier Product URL",
    "Datasheet URL",
)

ASSEMBLY_COLUMNS = (
    "Assembly MPN",
    "Description",
    "Parent MPN",
    "Line Type",
    "Quantity per Parent",
    "Effective Quantity",
    "Rolled Risk",
    "Leaf Count",
    "High-Risk Leaves",
    "Medium-Risk Leaves",
    "Needs Verification Leaves",
    "Top Contributors",
    "Contributor Evidence",
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


def _export_line_type(row: dict[str, Any]) -> str:
    """Keep Line Type only when the BOM supplied/mapped a non-default value."""
    raw = _first(row, "Line Type", "line_type", default="")
    text = _text(raw).strip()
    if not text or text.casefold() == "part":
        return ""
    return text


def _export_risk_level(row: dict[str, Any]) -> str:
    """Never present an unscored part as low risk."""
    level = _text(_first(row, "Risk Level", "risk_level", default="")).strip()
    score = _first(row, "Risk Score", "risk_score", default=None)
    scored = score not in (None, "", "None", "Not assessed", "not assessed", "Not scored")
    if not scored:
        if not level or level.casefold() in {"low", "healthy", "unknown", "none"}:
            return "Not assessed"
        return level
    return level or "Not assessed"


def _export_risk_score(row: dict[str, Any]) -> str:
    score = _first(row, "Risk Score", "risk_score", default=None)
    if score in (None, "", "None"):
        return "Not assessed"
    return _text(score)


def _field_from_evidence(evidence: dict[str, Any], field: str, key: str, default: Any = "") -> Any:
    fields = evidence.get("fields") if isinstance(evidence.get("fields"), dict) else {}
    envelope = fields.get(field) if isinstance(fields.get(field), dict) else {}
    return envelope.get(key, default)


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
                "Parent MPN": _first(row, "Parent MPN", "parent_mpn_display", "parent_mpn"),
                "Line Type": _export_line_type(row),
                "Quantity per Parent": _first(row, "quantity_per_parent", "Quantity per parent", "Quantity", "quantity", "qty"),
                "Effective Quantity": _first(row, "effective_quantity", "Effective Quantity", "Quantity", "quantity", "qty"),
                "Lifecycle": _first(row, "Lifecycle", "lifecycle_status", "Lifecycle Status"),
                "Risk Level": _export_risk_level(row),
                "Risk Score": _export_risk_score(row),
                "Risk Reasons": _first(row, "Risk Reasons", "risk_reasons", "reasons"),
                "Stock": _first(row, "Stock", "stock_available", "stock"),
                "Unit Price": _first(row, "Unit Price", "unit_price"),
                "Currency": _first(row, "unit_price_currency", "currency"),
                "Evidence Class": _first(evidence, "evidence_class", default=_first(row, "evidence_source", "source", default="not recorded")),
                "Evidence Source": _first(evidence, "source", default=_first(row, "identity_source", "evidence_source", "source")),
                "Identity Source": (
                    _field_from_evidence(evidence, "identity", "source")
                    or _first(row, "identity_source", "evidence_source", "source")
                ),
                "Identity Retrieved At": (
                    _field_from_evidence(evidence, "identity", "retrieved_at")
                    or _first(row, "identity_retrieved_at", "retrieved_at")
                ),
                "Lifecycle Source": (
                    _field_from_evidence(evidence, "lifecycle", "source")
                    or _first(row, "lifecycle_source")
                ),
                "Lifecycle Retrieved At": (
                    _field_from_evidence(evidence, "lifecycle", "retrieved_at")
                    or _first(row, "lifecycle_retrieved_at")
                ),
                "Stock Source": (
                    _field_from_evidence(evidence, "stock", "source")
                    or _first(row, "stock_source")
                ),
                "Stock Retrieved At": (
                    _field_from_evidence(evidence, "stock", "retrieved_at")
                    or _first(row, "stock_retrieved_at")
                ),
                "Price Source": (
                    _field_from_evidence(evidence, "price", "source")
                    or _first(row, "price_source")
                ),
                "Price Type": (
                    _field_from_evidence(evidence, "price", "price_type")
                    or _first(row, "price_type", default="not-recorded")
                ),
                "Price Retrieved At": (
                    _field_from_evidence(evidence, "price", "retrieved_at")
                    or _first(row, "price_retrieved_at")
                ),
                "Supplier Product URL": _first(row, "product_url", "source_url", "Supplier Product URL"),
                "Datasheet URL": _first(row, "datasheet_url", "Datasheet URL"),
            }
        )
    return output


def _assembly_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    hierarchy = report.get("hierarchy") if isinstance(report.get("hierarchy"), dict) else {}
    assemblies = hierarchy.get("assemblies") if isinstance(hierarchy.get("assemblies"), list) else []
    output = []
    for assembly in assemblies:
        if not isinstance(assembly, dict):
            continue
        contributors = assembly.get("contributors") if isinstance(assembly.get("contributors"), list) else []
        contributor_labels = []
        evidence_labels = []
        for contributor in contributors[:8]:
            if not isinstance(contributor, dict):
                continue
            mpn = _text(contributor.get("mpn"))
            level = _text(contributor.get("risk_level"))
            if mpn:
                contributor_labels.append(f"{mpn} ({level})" if level else mpn)
            evidence = _text(contributor.get("evidence_source"))
            if evidence:
                evidence_labels.append(f"{mpn}: {evidence}" if mpn else evidence)
        output.append(
            {
                "Assembly MPN": _first(assembly, "mpn", "MPN"),
                "Description": _first(assembly, "description", "Description"),
                "Parent MPN": _first(assembly, "parent_mpn", "Parent MPN"),
                "Line Type": _first(assembly, "line_type", default="assembly"),
                "Quantity per Parent": assembly.get("quantity_per_parent"),
                "Effective Quantity": assembly.get("effective_quantity"),
                "Rolled Risk": _first(assembly, "rolled_risk_level", default="Unknown"),
                "Leaf Count": assembly.get("leaf_count"),
                "High-Risk Leaves": assembly.get("high_risk_leaves"),
                "Medium-Risk Leaves": assembly.get("medium_risk_leaves"),
                "Needs Verification Leaves": assembly.get("needs_verification_leaves"),
                "Top Contributors": "; ".join(contributor_labels),
                "Contributor Evidence": "; ".join(evidence_labels),
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


def _add_xlsx_sheet(
    wb: Any,
    *,
    title: str,
    columns: tuple[str, ...],
    rows: list[dict[str, Any]],
    table_name: str,
    empty_note: str | None = None,
) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    sheet = wb.create_sheet(title)
    sheet.sheet_view.showGridLines = False
    for column, name in enumerate(columns, start=1):
        cell = sheet.cell(1, column, name)
        cell.font = Font(name="Aptos", size=10, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17324D")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    sheet.row_dimensions[1].height = 32
    if not rows and empty_note:
        sheet.cell(2, 1, empty_note)
        sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(1, len(columns)))
        sheet.cell(2, 1).font = Font(name="Aptos", size=10, italic=True, color="8A4B08")
        sheet.cell(2, 1).alignment = Alignment(wrap_text=True, vertical="top")
    for row_index, component in enumerate(rows, start=2):
        for column, name in enumerate(columns, start=1):
            value = _safe_spreadsheet_value(_text(component.get(name)))
            cell = sheet.cell(row_index, column, value)
            cell.font = Font(name="Aptos", size=10, color="334155")
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    if rows:
        last_col = get_column_letter(len(columns))
        table = Table(
            displayName=table_name,
            ref=f"A1:{last_col}{len(rows) + 1}",
        )
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        sheet.add_table(table)
        sheet.auto_filter.ref = f"A1:{last_col}{len(rows) + 1}"
    sheet.freeze_panes = "A2"
    for index in range(1, len(columns) + 1):
        sheet.column_dimensions[get_column_letter(index)].width = 18


def build_xlsx(report: dict[str, Any]) -> bytes:
    """Build a detailed workbook: Summary, Components, Component Details, High Risk Parts."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill, Side, Border

    rows = _component_rows(report)

    def _is_unscored(row: dict[str, Any]) -> bool:
        score = str(row.get("Risk Score") or "").strip().casefold()
        level = str(row.get("Risk Level") or "").strip().casefold()
        return score in {"", "none", "not assessed"} or level == "not assessed"

    not_assessed = [row for row in rows if _is_unscored(row)]
    high_rows = [
        row
        for row in rows
        if str(row.get("Risk Level") or "").casefold() in {"high", "critical"}
        and not _is_unscored(row)
    ]
    wb = Workbook()
    wb.properties.title = "Cadivor BOM Risk Report"
    wb.properties.creator = "Cadivor"
    summary = wb.active
    summary.title = "Summary"
    summary.sheet_view.showGridLines = False
    summary.merge_cells("A1:B1")
    summary["A1"] = "Cadivor BOM Risk Report"
    summary["A1"].font = Font(name="Aptos Display", size=18, bold=True, color="FFFFFF")
    summary["A1"].fill = PatternFill("solid", fgColor="17324D")
    summary.row_dimensions[1].height = 32
    summary.merge_cells("A2:B2")
    summary["A2"] = _synthetic_disclaimer(report)
    summary["A2"].font = Font(name="Aptos", size=10, color="8A4B08", italic=True)
    summary["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    summary.row_dimensions[2].height = 42

    meta = _metadata(report)
    assessed = len(rows) - len(not_assessed)
    facts = [
        *meta.items(),
        ("Health score", report.get("health_score", "Not scored")),
        ("Health status", report.get("health_status", "Not reported")),
        ("Total components", len(rows)),
        ("Risk assessed", assessed),
        ("Risk not assessed", len(not_assessed)),
        ("High risk", report.get("high_risk_count", len(high_rows))),
        ("Medium risk", report.get("medium_risk_count", 0)),
        ("Low risk", report.get("low_risk_count", 0)),
        (
            "Unscored parts",
            f"{len(not_assessed)} of {len(rows)} part(s) were not assessed — not proof of low risk"
            if not_assessed
            else "All listed parts include a recorded risk assessment",
        ),
        ("Evidence mode", report.get("mode", "Not reported")),
    ]
    for index, (label, value) in enumerate(facts, start=4):
        summary.cell(index, 1, label)
        summary.cell(index, 2, _safe_spreadsheet_value(_text(value)))
        summary.cell(index, 1).font = Font(name="Aptos", size=10, bold=True, color="17324D")
        summary.cell(index, 2).font = Font(name="Aptos", size=10, color="334155")
        summary.cell(index, 1).border = Border(bottom=Side(style="thin", color="D9E2EC"))
        summary.cell(index, 2).border = Border(bottom=Side(style="thin", color="D9E2EC"))
        summary.cell(index, 2).alignment = Alignment(wrap_text=True, vertical="top")
    summary.column_dimensions["A"].width = 25
    summary.column_dimensions["B"].width = 88

    _add_xlsx_sheet(
        wb,
        title="Components",
        columns=COMPONENT_COLUMNS,
        rows=rows,
        table_name="CadivorComponents",
    )
    detail_columns = (
        "MPN",
        "Description",
        "Manufacturer",
        "Effective Quantity",
        "Lifecycle",
        "Risk Level",
        "Risk Score",
        "Risk Reasons",
        "Evidence Class",
        "Evidence Source",
        "Stock",
        "Unit Price",
        "Currency",
        "Supplier Product URL",
        "Datasheet URL",
        "Parent MPN",
        "Line Type",
    )
    _add_xlsx_sheet(
        wb,
        title="Component Details",
        columns=detail_columns,
        rows=rows,
        table_name="CadivorComponentDetails",
    )
    _add_xlsx_sheet(
        wb,
        title="High Risk Parts",
        columns=detail_columns,
        rows=high_rows,
        table_name="CadivorHighRiskParts",
        empty_note=(
            f"{len(not_assessed)} of {len(rows)} part(s) were not assessed — not proof of low risk."
            if not_assessed and not high_rows
            else "No high-risk parts were recorded for this BOM."
        ),
    )
    assembly_rows = _assembly_rows(report)
    _add_xlsx_sheet(
        wb,
        title="Assemblies",
        columns=ASSEMBLY_COLUMNS,
        rows=assembly_rows,
        table_name="CadivorAssemblies",
        empty_note="No assembly roll-up was recorded for this BOM. Flat BOMs export components only.",
    )

    buffer = BytesIO()
    wb.save(buffer)
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
    health_score = report.get("health_score")
    health_label = (
        "Not scored"
        if health_score is None or str(health_score).strip().casefold() in {"", "not scored", "unknown", "none"}
        else _text(health_score)
    )
    story = [
        Paragraph("Cadivor BOM Risk Report", styles["CadivorExportTitle"]),
        Paragraph(
            "<b>Project:</b> " + escape(metadata["Project"]) +
            " &nbsp;&nbsp; <b>BOM:</b> " + escape(metadata["BOM"]) +
            " &nbsp;&nbsp; <b>Revision:</b> " + escape(metadata["Revision"]),
            styles["CadivorExportBody"],
        ),
        Paragraph(
            "<b>Health:</b> " + escape(health_label) +
            (" / 100" if health_label not in {"Not scored"} else "") +
            " &nbsp;&nbsp; <b>Status:</b> " + escape(_text(report.get("health_status") or "Not reported")) +
            " &nbsp;&nbsp; <b>Components:</b> " + str(len(rows)) +
            " &nbsp;&nbsp; <b>High / medium / low:</b> " +
            " / ".join(escape(_text(report.get(key, 0))) for key in ("high_risk_count", "medium_risk_count", "low_risk_count")),
            styles["CadivorExportBody"],
        ),
        Paragraph(escape(_synthetic_disclaimer(report)), styles["CadivorExportBody"]),
        Spacer(1, 8),
    ]

    assembly_rows = _assembly_rows(report)
    if assembly_rows:
        story.append(Paragraph("Assembly risk roll-up", styles["CadivorExportBody"]))
        assembly_headers = ("Assembly", "Parent", "Rolled risk", "Leaves", "Top contributors / evidence")
        assembly_data: list[list[Any]] = [
            [Paragraph(escape(name), styles["CadivorExportHead"]) for name in assembly_headers]
        ]
        for row in assembly_rows[:40]:
            assembly_data.append(
                [
                    Paragraph(escape(_text(row["Assembly MPN"])), styles["CadivorExportSmall"]),
                    Paragraph(escape(_text(row["Parent MPN"])), styles["CadivorExportSmall"]),
                    Paragraph(escape(_text(row["Rolled Risk"])), styles["CadivorExportSmall"]),
                    Paragraph(
                        escape(
                            f"{_text(row['Leaf Count'])} total · "
                            f"H {_text(row['High-Risk Leaves'])} / "
                            f"M {_text(row['Medium-Risk Leaves'])} / "
                            f"NV {_text(row['Needs Verification Leaves'])}"
                        ),
                        styles["CadivorExportSmall"],
                    ),
                    Paragraph(
                        escape(
                            " · ".join(
                                filter(
                                    None,
                                    (_text(row["Top Contributors"]), _text(row["Contributor Evidence"])),
                                )
                            )
                        ),
                        styles["CadivorExportSmall"],
                    ),
                ]
            )
        assembly_table = LongTable(
            assembly_data,
            colWidths=[1.2 * inch, 0.9 * inch, 0.8 * inch, 1.5 * inch, 3.8 * inch],
            repeatRows=1,
            hAlign="LEFT",
            splitByRow=1,
        )
        assembly_table.setStyle(
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
        story.append(assembly_table)
        story.append(Spacer(1, 10))

    headers = ("MPN", "Manufacturer / description", "Parent", "Qty", "Lifecycle", "Risk", "Provenance", "Risk reasons")
    data: list[list[Any]] = [[Paragraph(escape(name), styles["CadivorExportHead"]) for name in headers]]
    for row in rows:
        provenance = " · ".join(
            filter(
                None,
                [
                    f"id {_text(row.get('Identity Source'))}" if row.get("Identity Source") else "",
                    f"price {_text(row.get('Price Source'))}" if row.get("Price Source") else "",
                    f"type {_text(row.get('Price Type'))}" if row.get("Price Type") else "",
                    f"at {_text(row.get('Price Retrieved At') or row.get('Identity Retrieved At'))}"
                    if (row.get("Price Retrieved At") or row.get("Identity Retrieved At"))
                    else "",
                ],
            )
        ) or _text(row.get("Evidence Class"))
        data.append(
            [
                Paragraph(escape(_text(row["MPN"])), styles["CadivorExportSmall"]),
                Paragraph(escape(" · ".join(filter(None, (_text(row["Manufacturer"]), _text(row["Description"]))))), styles["CadivorExportSmall"]),
                Paragraph(escape(_text(row["Parent MPN"])), styles["CadivorExportSmall"]),
                Paragraph(escape(_text(row["Effective Quantity"])), styles["CadivorExportSmall"]),
                Paragraph(escape(_text(row["Lifecycle"])), styles["CadivorExportSmall"]),
                Paragraph(escape(_text(row["Risk Level"])), styles["CadivorExportSmall"]),
                Paragraph(escape(provenance), styles["CadivorExportSmall"]),
                Paragraph(escape(_text(row["Risk Reasons"])), styles["CadivorExportSmall"]),
            ]
        )
    if len(data) == 1:
        data.append([Paragraph("No component rows are present in this report.", styles["CadivorExportSmall"])] + [""] * (len(headers) - 1))
    widths = [0.95 * inch, 1.8 * inch, 0.78 * inch, 0.48 * inch, 0.78 * inch, 0.52 * inch, 1.2 * inch, 1.73 * inch]
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

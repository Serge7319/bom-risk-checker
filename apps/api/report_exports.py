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
    "BOM Manufacturer",
    "Supplier Manufacturer",
    "Manufacturer Source",
    "Manufacturer Identity Status",
    "Parent MPN",
    "Line Type",
    "Quantity per Parent",
    "Effective Quantity",
    "Lifecycle",
    "Lifecycle Evidence Status",
    "Lifecycle Evidence Note",
    "Risk Level",
    "Risk Score",
    "Risk Reasons",
    "Stock",
    "Stock Evidence Status",
    "Stock Evidence Note",
    "Unit Price",
    "Currency",
    "Price Evidence Status",
    "Price Evidence Note",
    "Price Break Quantity",
    "Price Quantity Applicability",
    "Evidence Class",
    "Evidence Source",
    "Supplier Sources Checked",
    "Supplier Coverage Complete",
    "Supplier Coverage",
    "Identity Source",
    "Identity Retrieved At",
    "Lifecycle Source",
    "Lifecycle Retrieved At",
    "Last Time Buy Date",
    "End of Life Date",
    "Estimated EOL Years",
    "PCN Number",
    "PCN Date",
    "PCN Status",
    "PCN Source URL",
    "RoHS Status",
    "RoHS Evidence Source",
    "RoHS Source URL",
    "RoHS Evidence Details",
    "REACH Status",
    "REACH Evidence Source",
    "REACH Source URL",
    "REACH Evidence Details",
    "PFAS Status",
    "PFAS Evidence Source",
    "PFAS Source URL",
    "PFAS Evidence Details",
    "Stock Source",
    "Stock Retrieved At",
    "Stock Aggregation",
    "Stock Evidence",
    "Price Source",
    "Price Type",
    "Price Retrieved At",
    "Lead Time Weeks",
    "Lead Time Source",
    "Lead Time Retrieved At",
    "Lead Time Evidence",
    "Supplier Offers",
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


_OPAQUE_IDENTIFIER = re.compile(
    r"\b[0-9a-f]{8}-(?:[a-z0-9]{2,12}-){1,}[a-z0-9]{0,16}(?:\.{3,})?(?=$|[^\w])",
    re.IGNORECASE,
)


def _user_text(value: Any) -> str:
    """Keep UUID-like internal record references out of report content."""
    return _OPAQUE_IDENTIFIER.sub("record reference", _text(value)).strip()


def _user_label(value: Any, fallback: str) -> str:
    raw = _text(value).strip()
    if not raw or _OPAQUE_IDENTIFIER.fullmatch(raw):
        return fallback
    return _user_text(raw) or fallback


def _safe_spreadsheet_value(value: Any) -> Any:
    """Keep untrusted BOM text from being evaluated as a spreadsheet formula."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


_XLSX_NUMERIC_FIELDS = {
    "Quantity per Parent",
    "Effective Quantity",
    "Risk Score",
    "Estimated EOL Years",
    "Stock",
    "Unit Price",
    "Lead Time Weeks",
    "Leaf Count",
    "High-Risk Leaves",
    "Medium-Risk Leaves",
    "Needs Verification Leaves",
    "Health score",
    "Total components",
    "Risk assessed",
    "Risk not assessed",
    "High risk",
    "Medium risk",
    "Low risk",
}

_XLSX_NUMBER_FORMATS = {
    "Quantity per Parent": "#,##0.###",
    "Effective Quantity": "#,##0.###",
    "Risk Score": "0",
    "Estimated EOL Years": "0.0",
    "Stock": "#,##0",
    "Unit Price": "#,##0.00##",
    "Lead Time Weeks": "0.##",
    "Leaf Count": "#,##0",
    "High-Risk Leaves": "#,##0",
    "Medium-Risk Leaves": "#,##0",
    "Needs Verification Leaves": "#,##0",
    "Health score": "0",
    "Total components": "#,##0",
    "Risk assessed": "#,##0",
    "Risk not assessed": "#,##0",
    "High risk": "#,##0",
    "Medium risk": "#,##0",
    "Low risk": "#,##0",
}


def _xlsx_value(field: str, value: Any) -> Any:
    """Keep quantities, counts, prices, and scores numeric in Excel."""
    if value is None or value == "":
        return None
    if field in _XLSX_NUMERIC_FIELDS and not isinstance(value, bool):
        try:
            from decimal import Decimal, InvalidOperation

            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            number = None
        if number is not None and number.is_finite():
            if number == number.to_integral_value():
                return int(number)
            return float(number)
    return _safe_spreadsheet_value(_text(value))


def _export_line_type(row: dict[str, Any]) -> str:
    """Keep Line Type only when the BOM supplied/mapped a non-default value."""
    raw = _first(row, "Line Type", "line_type", default="")
    text = _text(raw).strip()
    if not text or text.casefold() == "part":
        return ""
    return text


def _export_risk_level(row: dict[str, Any]) -> str:
    """Calculate risk from field evidence instead of trusting a saved label."""
    from src.risk_engine import calculate_risk

    return str(calculate_risk(row).get("risk_level") or "Needs verification")


def _export_risk_score(row: dict[str, Any]) -> str:
    from src.risk_engine import calculate_risk

    score = calculate_risk(row).get("risk_score")
    return _text(score) if score is not None else "Not assessed"


def _export_risk_reasons(row: dict[str, Any]) -> str:
    from src.risk_engine import calculate_risk

    reasons = calculate_risk(row).get("risk_reasons") or []
    return "; ".join(str(item).strip() for item in reasons if str(item).strip())


def _field_from_evidence(evidence: dict[str, Any], field: str, key: str, default: Any = "") -> Any:
    fields = evidence.get("fields") if isinstance(evidence.get("fields"), dict) else {}
    envelope = fields.get(field) if isinstance(fields.get(field), dict) else {}
    return envelope.get(key, default)


def _evidence_summary(value: Any, *, value_key: str, unit: str = "") -> str:
    """Render per-source readings as compact, auditable export text."""
    if isinstance(value, dict):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = [item for item in value if isinstance(item, dict)]
    else:
        return _text(value)
    lines = []
    for item in items:
        source = _text(item.get("source") or item.get("distributor") or item.get("supplier"))
        reading = item.get(value_key)
        if reading in (None, ""):
            continue
        label = f"{source}: " if source else ""
        label += f"{reading}{(' ' + unit) if unit else ''}"
        if item.get("currency") and value_key == "unit_price":
            label += f" {item['currency']}"
        if item.get("price_break_quantity") not in (None, ""):
            label += f" at qty {item['price_break_quantity']}"
        if item.get("retrieved_at"):
            label += f" (retrieved {item['retrieved_at']})"
        lines.append(label)
    return "; ".join(lines)


def _compliance_value(row: dict[str, Any], kind: str) -> tuple[str, str]:
    root = row.get("compliance_evidence") if isinstance(row.get("compliance_evidence"), dict) else {}
    node = root.get(kind) if isinstance(root.get(kind), dict) else {}
    value = _first(
        node,
        "reported_value",
        "status",
        default=_first(row, f"{kind}_status", f"{kind.upper()} status", default=""),
    )
    source = _first(
        node,
        "source",
        default=_first(row, f"{kind}_source", f"{kind}_evidence_source", default=""),
    )
    return (_text(value) or "Not retrieved", _text(source) or "Not recorded")


def _compliance_source_details(row: dict[str, Any], kind: str) -> str:
    root = row.get("compliance_evidence") if isinstance(row.get("compliance_evidence"), dict) else {}
    node = root.get(kind) if isinstance(root.get(kind), dict) else {}
    readings = node.get("sources") if isinstance(node.get("sources"), list) else []
    if not readings and node:
        readings = [node]
    details = []
    for item in readings:
        if not isinstance(item, dict):
            continue
        pieces = [
            _text(item.get("source")) or "Supplier",
            _text(item.get("reported_value") or item.get("status")) or "No value",
        ]
        if item.get("retrieved_at"):
            pieces.append(f"retrieved {item['retrieved_at']}")
        if item.get("source_url") or item.get("url"):
            pieces.append(_text(item.get("source_url") or item.get("url")))
        details.append(" · ".join(pieces))
    return "; ".join(details)


def _component_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    from src.bom_intake import clean_text
    from apps.api.evidence_contract import classify_part_evidence

    output = []
    for source in report.get("parts") or []:
        if not isinstance(source, dict):
            continue
        row = dict(source)
        # Rebuild from the saved raw supplier records. Older evidence envelopes
        # may have been created before exact-MPN/provenance checks were strict.
        evidence = classify_part_evidence(row)
        rohs_value, rohs_source = _compliance_value(row, "rohs")
        reach_value, reach_source = _compliance_value(row, "reach")
        pfas_value, pfas_source = _compliance_value(row, "pfas")
        lead_time_evidence = row.get("lead_time_evidence") or row.get("Lead Time Evidence") or []
        stock_evidence = row.get("stock_evidence") or row.get("Stock Evidence") or []
        stock_evidence = _field_from_evidence(
            evidence, "stock", "sources", default=stock_evidence
        ) or stock_evidence
        supplier_offers = row.get("supplier_offers") or row.get("Supplier Offers") or []
        component = {
            "MPN": clean_text(_first(row, "MPN", "mpn", "manufacturer_part_number", "part_number")),
            "Manufacturer": clean_text(_first(row, "Manufacturer", "manufacturer")),
            "BOM Manufacturer": _first(row, "BOM Manufacturer", "bom_manufacturer", "requested_manufacturer"),
            "Supplier Manufacturer": _first(row, "Supplier Manufacturer", "supplier_manufacturer"),
            "Manufacturer Source": _first(row, "Manufacturer Source", "manufacturer_source", default="Not recorded"),
            "Manufacturer Identity Status": _first(row, "Manufacturer Identity Status", "identity_status", default="Not recorded"),
            "Description": clean_text(_first(row, "Description", "description", "part_description")),
            "Parent MPN": _first(row, "Parent MPN", "parent_mpn_display", "parent_mpn"),
            "Line Type": _export_line_type(row),
            "Quantity per Parent": _first(row, "quantity_per_parent", "Quantity per parent", "Quantity", "quantity", "qty"),
            "Effective Quantity": _first(row, "effective_quantity", "Effective Quantity", "Quantity", "quantity", "qty"),
            "Lifecycle": _first(row, "Lifecycle", "lifecycle_status", "Lifecycle Status"),
            "Lifecycle Evidence Status": _field_from_evidence(evidence, "lifecycle", "evidence_class", default="missing"),
            "Lifecycle Evidence Note": _field_from_evidence(evidence, "lifecycle", "gap", default=""),
            "Risk Level": _export_risk_level(row),
            "Risk Score": _export_risk_score(row),
            "Risk Reasons": _export_risk_reasons(row),
            "Stock": _first(row, "Stock", "stock_available", "stock"),
            "Stock Evidence Status": _field_from_evidence(evidence, "stock", "evidence_class", default="missing"),
            "Stock Evidence Note": _field_from_evidence(evidence, "stock", "gap", default=""),
            "Unit Price": _first(row, "Unit Price", "unit_price"),
            "Currency": _first(row, "unit_price_currency", "currency"),
            "Price Evidence Status": _field_from_evidence(evidence, "price", "evidence_class", default="missing"),
            "Price Evidence Note": _field_from_evidence(evidence, "price", "gap", default=""),
            "Price Break Quantity": _field_from_evidence(evidence, "price", "price_break_quantity", default=""),
            "Price Quantity Applicability": (
                "Applies"
                if _field_from_evidence(evidence, "price", "quantity_break_applies") is True
                else "Not established"
            ),
            "Evidence Class": _first(evidence, "evidence_class", default=_first(row, "evidence_source", "source", default="not recorded")),
            "Evidence Source": _first(evidence, "source", default=_first(row, "identity_source", "evidence_source", "source")),
            "Supplier Sources Checked": _first(
                row, "Supplier Sources Checked", "supplier_sources_checked", default="Not recorded"
            ),
            "Supplier Coverage Complete": _first(
                row, "Supplier Coverage Complete", "supplier_coverage_complete", default="Not recorded"
            ),
            "Supplier Coverage": _first(
                row, "Supplier Coverage", "supplier_coverage", default="Not recorded"
            ),
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
            "Last Time Buy Date": _first(row, "last_time_buy_date", "Last Time Buy Date"),
            "End of Life Date": _first(row, "end_of_life_date", "eol_date", "End Of Life Date"),
            "Estimated EOL Years": _first(row, "estimated_eol_years", "Estimated EOL Years"),
            "PCN Number": _first(row, "pcn_number", "pcn_id", "PCN Number"),
            "PCN Date": _first(row, "pcn_date", "PCN Date"),
            "PCN Status": _first(row, "pcn_status", "PCN Status", default="Not retrieved"),
            "PCN Source URL": _first(row, "pcn_url", "PCN URL"),
            "RoHS Status": rohs_value,
            "RoHS Evidence Source": rohs_source,
            "RoHS Source URL": _first(row, "rohs_source_url", "rohs_evidence_url"),
            "RoHS Evidence Details": _compliance_source_details(row, "rohs"),
            "REACH Status": reach_value,
            "REACH Evidence Source": reach_source,
            "REACH Source URL": _first(row, "reach_source_url", "reach_evidence_url"),
            "REACH Evidence Details": _compliance_source_details(row, "reach"),
            "PFAS Status": pfas_value,
            "PFAS Evidence Source": pfas_source,
            "PFAS Source URL": _first(row, "pfas_source_url", "pfas_evidence_url"),
            "PFAS Evidence Details": _compliance_source_details(row, "pfas"),
            "Stock Source": (
                _field_from_evidence(evidence, "stock", "source")
                or _first(row, "stock_source")
            ),
            "Stock Retrieved At": (
                _field_from_evidence(evidence, "stock", "retrieved_at")
                or _first(row, "stock_retrieved_at")
            ),
            "Stock Aggregation": _first(row, "Stock Aggregation", "stock_aggregation", default="Not reported"),
            "Stock Evidence": _evidence_summary(stock_evidence, value_key="stock", unit="units"),
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
            "Lead Time Weeks": _first(row, "Lead Time Weeks", "lead_time_weeks", "Lead Time (Weeks)", default="Not reported"),
            "Lead Time Source": (
                _field_from_evidence(evidence, "lead_time", "source")
                or _first(row, "Lead Time Source", "lead_time_source", default="Not recorded")
            ),
            "Lead Time Retrieved At": (
                _field_from_evidence(evidence, "lead_time", "retrieved_at")
                or _first(row, "Lead Time Retrieved At", "lead_time_retrieved_at")
            ),
            "Lead Time Evidence": _evidence_summary(lead_time_evidence, value_key="weeks", unit="weeks"),
            "Supplier Offers": _evidence_summary(supplier_offers, value_key="unit_price"),
            "Supplier Product URL": _first(row, "product_url", "source_url", "Supplier Product URL"),
            "Datasheet URL": _first(row, "datasheet_url", "Datasheet URL"),
        }
        for field, value in component.items():
            if isinstance(value, (str, list, tuple, dict)) and field not in {"Supplier Product URL", "Datasheet URL"}:
                component[field] = _user_text(value)
        output.append(component)
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
        assembly_row = {
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
        for field, value in assembly_row.items():
            if isinstance(value, (str, list, tuple, dict)):
                assembly_row[field] = _user_text(value)
        output.append(assembly_row)
    return output


def _metadata(report: dict[str, Any]) -> dict[str, str]:
    return {
        "Project": _user_label(_first(report, "project_name", default=""), "Engineering workspace"),
        "BOM": _user_label(_first(report, "bom_name", "filename", default=""), "Saved BOM"),
        "Revision": _user_label(_first(report, "revision", default=""), "—"),
        "Analyzed At": _user_text(_first(report, "created_at", default="—")),
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
            f"{summary.get('unverified_count', 0)} unverified, "
            f"{summary.get('missing_count', 0)} missing. Review the source and retrieval "
            "date for each component before acting. Supplier API readings are point-in-time snapshots, not authenticated checkout inventory, reservations, or purchase quotes."
        )
    return "Review each component's evidence source and retrieval date before acting."


def _risk_distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0, "unassessed": 0}
    for row in rows:
        level = str(row.get("Risk Level") or "").strip().casefold()
        if level in {"high", "critical"}:
            counts["high"] += 1
        elif level == "medium":
            counts["medium"] += 1
        elif level in {"low", "healthy"}:
            counts["low"] += 1
        else:
            counts["unassessed"] += 1
    return counts


def _risk_summary_counts(
    report: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, int]:
    """Prefer visible row ratings; use saved aggregates only when rows are absent."""
    if rows:
        return _risk_distribution(rows)
    counts: dict[str, int] = {}
    for key in ("high", "medium", "low"):
        try:
            value = int(report.get(f"{key}_risk_count") or 0)
        except (TypeError, ValueError):
            value = 0
        counts[key] = max(0, value)
    try:
        total_parts = int(report.get("total_parts") or 0)
    except (TypeError, ValueError):
        total_parts = 0
    counts["unassessed"] = max(
        0, total_parts - counts["high"] - counts["medium"] - counts["low"]
    )
    return counts


def _executive_summary(report: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    saved_summary = _user_text(report.get("summary_message"))
    if saved_summary:
        return saved_summary
    counts = _risk_distribution(rows)
    total = len(rows)
    if not total:
        return "No component rows are present in this report."
    summary = (
        f"Saved analysis contains {total} component(s): {counts['high']} high risk, "
        f"{counts['medium']} medium risk, {counts['low']} low risk, and "
        f"{counts['unassessed']} needing verification."
    )
    if counts["unassessed"]:
        summary += " Unassessed components are not evidence of low risk."
    return summary


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


def build_interchange_csv(report: dict[str, Any]) -> bytes:
    """Export BOM structure in a neutral PLM/ERP-friendly column contract.

    This is a file interchange format, not a live connector. Only BOM fields
    supplied in the source report are copied; Cadivor never invents item IDs,
    units, references, or hierarchy.
    """
    columns = (
        "Item Number",
        "Manufacturer Part Number",
        "Manufacturer",
        "Description",
        "Quantity",
        "Unit",
        "Reference Designators",
        "Parent Item Number",
        "Line Type",
        "Footprint",
        "Lifecycle Status",
        "Last Time Buy Date",
        "End of Life Date",
        "Estimated EOL Years",
        "PCN Number",
        "PCN Date",
        "PCN Status",
        "PCN Source URL",
    )
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for source in report.get("parts") or []:
        if not isinstance(source, dict):
            continue
        values = {
            "Item Number": _first(source, "Item Number", "item_number", "internal_part_number", default=""),
            "Manufacturer Part Number": _first(source, "Manufacturer Part Number", "MPN", "mpn", "manufacturer_part_number"),
            "Manufacturer": _first(source, "Manufacturer", "manufacturer"),
            "Description": _first(source, "Description", "description", "part_description"),
            "Quantity": _first(source, "Effective Quantity", "effective_quantity", "Quantity", "quantity", "qty"),
            # Leave UOM blank when the BOM did not specify one. A default
            # would silently invent a unit and could corrupt a PLM import.
            "Unit": _first(source, "Unit", "UOM", "unit", "uom", default=""),
            "Reference Designators": _first(source, "Reference Designators", "reference_designators", "Designator", "designator", "Ref Des", "ref_des"),
            "Parent Item Number": _first(source, "Parent Item Number", "parent_item_number", "Parent MPN", "parent_mpn"),
            "Line Type": _first(source, "Line Type", "line_type"),
            "Footprint": _first(source, "Footprint", "footprint", "Package", "package"),
            "Lifecycle Status": _first(source, "Lifecycle Status", "Lifecycle", "lifecycle_status"),
            "Last Time Buy Date": _first(source, "last_time_buy_date", "Last Time Buy Date"),
            "End of Life Date": _first(source, "end_of_life_date", "eol_date", "End Of Life Date"),
            "Estimated EOL Years": _first(source, "estimated_eol_years", "Estimated EOL Years"),
            "PCN Number": _first(source, "pcn_number", "pcn_id", "PCN Number"),
            "PCN Date": _first(source, "pcn_date", "PCN Date"),
            "PCN Status": _first(source, "pcn_status", "PCN Status"),
            "PCN Source URL": _first(source, "pcn_url", "PCN URL"),
        }
        writer.writerow({key: _safe_spreadsheet_value(_user_text(value)) for key, value in values.items()})
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
            value = _xlsx_value(name, component.get(name))
            cell = sheet.cell(row_index, column, value)
            cell.font = Font(name="Aptos", size=10, color="334155")
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if name in _XLSX_NUMBER_FORMATS and cell.data_type == "n":
                cell.number_format = _XLSX_NUMBER_FORMATS[name]
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
    widths = {
        "MPN": 24,
        "Assembly MPN": 24,
        "Manufacturer": 26,
        "BOM Manufacturer": 26,
        "Supplier Manufacturer": 26,
        "Manufacturer Source": 24,
        "Manufacturer Identity Status": 23,
        "Description": 44,
        "Parent MPN": 22,
        "Line Type": 16,
        "Quantity per Parent": 18,
        "Effective Quantity": 18,
        "Lifecycle": 24,
        "Risk Level": 18,
        "Risk Score": 13,
        "Risk Reasons": 58,
        "Stock": 15,
        "Unit Price": 15,
        "Currency": 10,
        "Evidence Class": 26,
        "Evidence Source": 22,
        "Identity Source": 22,
        "Identity Retrieved At": 26,
        "Lifecycle Source": 22,
        "Lifecycle Retrieved At": 26,
        "Stock Source": 22,
        "Stock Retrieved At": 26,
        "Stock Aggregation": 48,
        "Stock Evidence": 52,
        "Price Source": 22,
        "Price Type": 22,
        "Price Retrieved At": 26,
        "Lead Time Weeks": 18,
        "Lead Time Source": 22,
        "Lead Time Retrieved At": 26,
        "Lead Time Evidence": 52,
        "Supplier Offers": 58,
        "Supplier Product URL": 52,
        "Datasheet URL": 52,
        "Rolled Risk": 18,
        "Leaf Count": 14,
        "High-Risk Leaves": 18,
        "Medium-Risk Leaves": 19,
        "Needs Verification Leaves": 25,
        "Top Contributors": 44,
        "Contributor Evidence": 44,
    }
    for index, name in enumerate(columns, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = widths.get(name, 18)


def build_xlsx(report: dict[str, Any]) -> bytes:
    """Build a detailed workbook: Summary, Components, Component Details, High Risk Parts."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill, Side, Border

    rows = _component_rows(report)

    def _is_unscored(row: dict[str, Any]) -> bool:
        score = str(row.get("Risk Score") or "").strip().casefold()
        level = str(row.get("Risk Level") or "").strip().casefold()
        unscored = score in {"", "none", "not assessed"}
        if level in {"", "unknown", "not assessed", "needs verification"}:
            return True
        return unscored and level in {"low", "healthy"}

    not_assessed = [row for row in rows if _is_unscored(row)]
    risk_counts = _risk_summary_counts(report, rows)
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
        ("Health status", _user_label(report.get("health_status"), "Not reported")),
        ("Total components", len(rows)),
        ("Risk assessed", assessed),
        ("Risk not assessed", len(not_assessed)),
        ("High risk", risk_counts["high"]),
        ("Medium risk", risk_counts["medium"]),
        ("Low risk", risk_counts["low"]),
        (
            "Unscored parts",
            f"{len(not_assessed)} of {len(rows)} part(s) were not assessed — not proof of low risk"
            if not_assessed
            else "All listed parts include a recorded risk assessment",
        ),
        ("Evidence mode", _user_label(report.get("mode"), "Not reported")),
        ("Executive summary", _executive_summary(report, rows)),
    ]
    for index, (label, value) in enumerate(facts, start=4):
        summary.cell(index, 1, label)
        summary.cell(index, 2, _xlsx_value(label, value))
        summary.cell(index, 1).font = Font(name="Aptos", size=10, bold=True, color="17324D")
        summary.cell(index, 2).font = Font(name="Aptos", size=10, color="334155")
        summary.cell(index, 1).border = Border(bottom=Side(style="thin", color="D9E2EC"))
        summary.cell(index, 2).border = Border(bottom=Side(style="thin", color="D9E2EC"))
        summary.cell(index, 2).alignment = Alignment(wrap_text=True, vertical="top")
        if label == "Executive summary":
            summary.row_dimensions[index].height = 42
        if label in _XLSX_NUMBER_FORMATS and summary.cell(index, 2).data_type == "n":
            summary.cell(index, 2).number_format = _XLSX_NUMBER_FORMATS[label]
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
        "BOM Manufacturer",
        "Supplier Manufacturer",
        "Manufacturer Source",
        "Manufacturer Identity Status",
        "Effective Quantity",
        "Lifecycle",
        "Risk Level",
        "Risk Score",
        "Risk Reasons",
        "Evidence Class",
        "Evidence Source",
        "Stock",
        "Stock Source",
        "Stock Aggregation",
        "Stock Evidence",
        "Unit Price",
        "Currency",
        "Price Source",
        "Lead Time Weeks",
        "Lead Time Source",
        "Lead Time Retrieved At",
        "Lead Time Evidence",
        "Supplier Offers",
        "RoHS Status",
        "REACH Status",
        "PFAS Status",
        "PCN Status",
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
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
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
    styles.add(ParagraphStyle(name="CadivorExportSmall", parent=styles["BodyText"], fontSize=6.5, leading=7.5, textColor=colors.HexColor("#334155")))
    styles.add(ParagraphStyle(name="CadivorExportHead", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=6.5, leading=7.5, textColor=colors.white))
    styles.add(ParagraphStyle(name="CadivorExportSubhead", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.HexColor("#17324D"), spaceBefore=5, spaceAfter=3))

    cjk_font = "HeiseiKakuGo-W5"
    if cjk_font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(cjk_font))
    cjk_pattern = re.compile(r"[\u2E80-\u2FFF\u3040-\u30FF\u31F0-\u31FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uAC00-\uD7AF]")
    for name in ("CadivorExportTitle", "CadivorExportBody", "CadivorExportSmall", "CadivorExportHead", "CadivorExportSubhead"):
        styles.add(
            ParagraphStyle(
                name=f"{name}CJK",
                parent=styles[name],
                fontName=cjk_font,
            )
        )

    def paragraph(value: Any, style_name: str, *, markup: bool = False) -> Paragraph:
        text = _text(value)
        style = styles[f"{style_name}CJK"] if cjk_pattern.search(text) else styles[style_name]
        return Paragraph(text if markup else escape(text), style)

    metadata = _metadata(report)
    health_score = report.get("health_score")
    health_label = (
        "Not scored"
        if health_score is None or str(health_score).strip().casefold() in {"", "not scored", "unknown", "none"}
        else _text(health_score)
    )
    risk_counts = _risk_summary_counts(report, rows)
    story = [
        paragraph("Cadivor BOM Risk Report", "CadivorExportTitle"),
        paragraph(
            "<b>Project:</b> " + escape(metadata["Project"]) +
            " &nbsp;&nbsp; <b>BOM:</b> " + escape(metadata["BOM"]) +
            " &nbsp;&nbsp; <b>Revision:</b> " + escape(metadata["Revision"]),
            "CadivorExportBody",
            markup=True,
        ),
        paragraph(
            "<b>Health:</b> " + escape(health_label) +
            (" / 100" if health_label not in {"Not scored"} else "") +
            " &nbsp;&nbsp; <b>Status:</b> " + escape(_user_label(report.get("health_status"), "Not reported")) +
            " &nbsp;&nbsp; <b>Components:</b> " + str(len(rows)) +
            " &nbsp;&nbsp; <b>High / medium / low:</b> " +
            " / ".join(str(risk_counts[key]) for key in ("high", "medium", "low")),
            "CadivorExportBody",
            markup=True,
        ),
        paragraph(_synthetic_disclaimer(report), "CadivorExportBody"),
        paragraph("Executive summary", "CadivorExportSubhead"),
        paragraph(_executive_summary(report, rows), "CadivorExportBody"),
        paragraph(
            "Risk distribution: "
            f"{risk_counts['high']} high · {risk_counts['medium']} medium · "
            f"{risk_counts['low']} low · {risk_counts['unassessed']} needs verification",
            "CadivorExportBody",
        ),
        Spacer(1, 8),
    ]

    assembly_rows = _assembly_rows(report)
    if assembly_rows:
        story.append(Paragraph("Assembly risk roll-up", styles["CadivorExportBody"]))
        assembly_headers = ("Assembly", "Parent", "Rolled risk", "Leaves", "Top contributors / evidence")
        assembly_data: list[list[Any]] = [
            [paragraph(name, "CadivorExportHead") for name in assembly_headers]
        ]
        for row in assembly_rows[:40]:
            assembly_data.append(
                [
                    paragraph(row["Assembly MPN"], "CadivorExportSmall"),
                    paragraph(row["Parent MPN"], "CadivorExportSmall"),
                    paragraph(row["Rolled Risk"], "CadivorExportSmall"),
                    paragraph(
                        f"{_text(row['Leaf Count'])} total · "
                        f"H {_text(row['High-Risk Leaves'])} / "
                        f"M {_text(row['Medium-Risk Leaves'])} / "
                        f"NV {_text(row['Needs Verification Leaves'])}",
                        "CadivorExportSmall",
                    ),
                    paragraph(
                        " · ".join(
                            filter(
                                None,
                                (_text(row["Top Contributors"]), _text(row["Contributor Evidence"])),
                            )
                        ),
                        "CadivorExportSmall",
                    ),
                ]
            )
        available_width = landscape(letter)[0] - doc.leftMargin - doc.rightMargin
        assembly_table = LongTable(
            assembly_data,
            colWidths=[available_width * part for part in (0.14, 0.11, 0.10, 0.16, 0.49)],
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
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ]
            )
        )
        story.append(assembly_table)
        story.append(Spacer(1, 10))

    headers = ("MPN", "Manufacturer / description", "Parent", "Qty", "Lifecycle", "Risk", "Provenance", "Risk reasons")
    data: list[list[Any]] = [[paragraph(name, "CadivorExportHead") for name in headers]]
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
                paragraph(row["MPN"], "CadivorExportSmall"),
                paragraph(" · ".join(filter(None, (_text(row["Manufacturer"]), _text(row["Description"])))), "CadivorExportSmall"),
                paragraph(row["Parent MPN"], "CadivorExportSmall"),
                paragraph(row["Effective Quantity"], "CadivorExportSmall"),
                paragraph(row["Lifecycle"], "CadivorExportSmall"),
                paragraph(row["Risk Level"], "CadivorExportSmall"),
                paragraph(provenance, "CadivorExportSmall"),
                paragraph(row["Risk Reasons"], "CadivorExportSmall"),
            ]
        )
    if len(data) == 1:
        data.append([paragraph("No component rows are present in this report.", "CadivorExportSmall")] + [""] * (len(headers) - 1))
    available_width = landscape(letter)[0] - doc.leftMargin - doc.rightMargin
    widths = [available_width * part for part in (0.12, 0.22, 0.09, 0.055, 0.10, 0.095, 0.15, 0.17)]
    table = LongTable(data, colWidths=widths, repeatRows=1, hAlign="LEFT", splitByRow=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9E2EC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
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
        "plm-csv": (build_interchange_csv, "text/csv; charset=utf-8", "csv"),
        "xlsx": (build_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
        "pdf": (build_pdf, "application/pdf", "pdf"),
    }
    if normalized not in builders:
        raise ValueError("Choose one of the supported export formats: PDF, Excel, or CSV.")
    builder, media_type, extension = builders[normalized]
    return builder(report), media_type, extension


def safe_download_stem(report: dict[str, Any]) -> str:
    raw = _text(_first(report, "bom_name", "filename", "project_name", default="cadivor-report")).strip()
    if _OPAQUE_IDENTIFIER.fullmatch(raw):
        raw = "cadivor-report"
    else:
        raw = _user_text(raw)
    leaf = raw.rsplit("/", 1)[-1]
    leaf = re.sub(r"\.(?:csv|xlsx|xls)$", "", leaf, flags=re.IGNORECASE)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", leaf).strip(".-_")
    return (stem[:80] or "cadivor-report") + "-risk-report"

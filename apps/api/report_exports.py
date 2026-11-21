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
    "BOM Manufacturer",
    "Supplier Manufacturer",
    "Manufacturer Source",
    "Manufacturer Identity Status",
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
    output = []
    for source in report.get("parts") or []:
        if not isinstance(source, dict):
            continue
        row = dict(source)
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        rohs_value, rohs_source = _compliance_value(row, "rohs")
        reach_value, reach_source = _compliance_value(row, "reach")
        pfas_value, pfas_source = _compliance_value(row, "pfas")
        lead_time_evidence = row.get("lead_time_evidence") or row.get("Lead Time Evidence") or []
        stock_evidence = row.get("stock_evidence") or row.get("Stock Evidence") or []
        supplier_offers = row.get("supplier_offers") or row.get("Supplier Offers") or []
        component = {
            "MPN": _first(row, "MPN", "mpn", "manufacturer_part_number", "part_number"),
            "Manufacturer": _first(row, "Manufacturer", "manufacturer"),
            "BOM Manufacturer": _first(row, "BOM Manufacturer", "bom_manufacturer", "requested_manufacturer"),
            "Supplier Manufacturer": _first(row, "Supplier Manufacturer", "supplier_manufacturer"),
            "Manufacturer Source": _first(row, "Manufacturer Source", "manufacturer_source", default="Not recorded"),
            "Manufacturer Identity Status": _first(row, "Manufacturer Identity Status", "identity_status", default="Not recorded"),
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


def _assembly_rows(report: dict[str, Any]) -> list[dic
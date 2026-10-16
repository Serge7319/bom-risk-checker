"""Customer-facing CSV and Excel exports for an authenticated BOM risk report."""

from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime
from io import BytesIO, StringIO
from typing import Any


CSV_COLUMNS = (
    "MPN",
    "Qty",
    "Lifecycle",
    "Stock",
    "Lead time (weeks)",
    "Suppliers",
    "Evidence source",
    "Approved alternatives",
    "Risk",
    "Why",
    "Unit price",
    "Unit price currency",
    "Extended cost",
    "Description-mentioned alternatives",
)

DETAIL_COLUMNS = (
    "MPN",
    "Description",
    "Manufacturer",
    "Qty",
    "Lifecycle",
    "Stock",
    "Evidence source",
    "Recorded supplier",
    "Stock coverage",
    "Lead time (weeks)",
    "Lead-time source",
    "Supplier count",
    "Supplier coverage",
    "Risk",
    "Risk score",
    "Why",
    "Lifecycle evidence",
    "Lifecycle conflict",
    "Alternate search status",
    "Approved alternatives",
    "Unit price",
    "Unit price currency",
    "Extended cost",
    "Description-mentioned alternatives",
)

_MISSING = {"", "nan", "none", "null", "nat", "not recorded"}


def _first(record: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key not in record:
            continue
        value = record.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.strip().casefold() in _MISSING:
            continue
        return value
    return default


def _number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _text(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    if isinstance(value, (dict, list, tuple)):
        value = _joined(value)
    text = str(value).strip()
    return fallback if text.casefold() in _MISSING else text


def _joined(value: Any) -> str:
    value = _json_value(value)
    if isinstance(value, dict):
        source = _first(value, "supplier", "source", "distributor", "vendor", "name")
        status = _first(value, "status", "lifecycle_status", "result")
        retrieved = _first(value, "retrieved_at", "checked_at", "updated_at")
        pieces = [str(item).strip() for item in (source, status) if item not in (None, "")]
        label = ": ".join(pieces)
        if retrieved:
            label = f"{label} (retrieved {retrieved})" if label else str(retrieved)
        if label:
            return label
        return "; ".join(f"{key}: {_text(item, '')}" for key, item in value.items() if item not in (None, ""))
    if isinstance(value, (list, tuple, set)):
        items = [_joined(item) if isinstance(item, dict) else _text(item, "") for item in value]
        return "; ".join(item for item in items if item)
    return str(value or "").strip()


def _sources(record: dict[str, Any]) -> str:
    value = record.get("stock_data_sources")
    names = _joined(value) if value not in (None, "", []) else ""
    if names:
        return names
    # Older/public analysis records may store the evidence-source list under
    # the public stress-test field name. Do not substitute the preferred price
    # supplier: it does not prove that supplier returned an inventory count.
    return _text(record.get("sources"))


def _flag(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    folded = str(value).strip().casefold()
    if folded in {"true", "yes", "1", "complete", "completed"}:
        return True
    if folded in {"false", "no", "0", "incomplete", "partial"}:
        return False
    return None


def _lifecycle_evidence(value: Any) -> str:
    value = _json_value(value)
    if value in (None, "", [], {}):
        return "—"
    if isinstance(value, (list, tuple)):
        parts = [_joined(item) for item in value]
        return "; ".join(item for item in parts if item) or "—"
    return _joined(value) or "—"


def _reasons(record: dict[str, Any]) -> str:
    if _risk(record)[0] == "Not assessed" and not _has_supplier_match(record):
        return (
            "No configured distributor returned a matching record for this MPN. "
            "Verify the full manufacturer part number and rerun; stock, lifecycle, "
            "and lead-time risk remain unknown."
        )
    value = _first(record, "risk_reasons", "Risk Reasons", "risk_reason", "Why", default="")
    value = _json_value(value)
    if isinstance(value, (list, tuple, set)):
        reasons = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, dict):
        reasons = [_joined(value)]
    else:
        reasons = [item.strip() for item in str(value or "").split(";") if item.strip()]
    if _stock(record) == "Not reported":
        reasons = [
            "Inventory status needs confirmation; source-backed stock evidence was not saved."
            if re.search(r"\b(no stock|no inventory|zero stock|out of stock|inventory unavailable)\b", reason, re.IGNORECASE)
            else reason
            for reason in reasons
        ]
    return "; ".join(reasons) or "No risk explanation was saved for this component."


def _has_supplier_match(record: dict[str, Any]) -> bool:
    supplier_count = _number(_first(record, "supplier_count", "Supplier count", "Suppliers"))
    if supplier_count is not None and supplier_count > 0:
        return True
    return any(
        value not in {"—", "Unavailable", ""}
        for value in (
            _sources(record),
            _text(_first(record, "primary_supplier", "best_source", "supplier", "distributor"), ""),
            _text(record.get("lead_time_source"), ""),
            _lifecycle_evidence(record.get("lifecycle_evidence")),
        )
    )


def _risk(record: dict[str, Any]) -> tuple[str, int | float | None]:
    score = _number(_first(record, "risk_score", "Risk Score", "score"))
    raw = str(_first(record, "risk_level", "Risk Level", "risk", "Risk", default="") or "").strip()
    folded = raw.casefold()
    if any(token in folded for token in ("verif", "unassess", "not assess", "not rated", "unknown", "unrated")):
        return "Not assessed", None
    if "critical" in folded or "high" in folded:
        return "High", score
    if "medium" in folded or folded == "med":
        return "Medium", score
    if "low" in folded:
        return "Low", score
    if score is None:
        return "Not assessed", None
    if score == 0 and not _has_supplier_match(record):
        return "Not assessed", None
    if score >= 70:
        return "High", score
    if score >= 40:
        return "Medium", score
    return "Low", score


def _stock(record: dict[str, Any]) -> int | float | str:
    value = _number(_first(record, "stock_available", "Stock Available", "stock", "Stock"))
    if value is None:
        return "Not reported"
    # Before source provenance was stored, zero was also used as an empty
    # default. Only present zero when a distributor explicitly returned stock.
    if value == 0 and _sources(record) == "—":
        return "Not reported"
    return value


def _lead_time(record: dict[str, Any]) -> int | float | str:
    value = _first(record, "lead_time_weeks", "Lead Time Weeks", "lead_time", "Lead time (weeks)")
    number = _number(value)
    if number is not None:
        return number if number > 0 else "—"
    return _text(value)


def _supplier_count(record: dict[str, Any]) -> int | float | str:
    value = _number(_first(record, "supplier_count", "Supplier Count", "Suppliers"))
    if value is None:
        return "—"
    if value == 0 and _text(record.get("supplier_coverage"), "") == "":
        return "—"
    return value


def _price_currency(record: dict[str, Any], *, mpn: str, supplier: str, price: int | float | None) -> str:
    from src.saved_bom_cost import normalize_currency_code

    explicit = normalize_currency_code(
        _first(record, "unit_price_currency", "currency", "Currency")
    )
    if explicit:
        return explicit
    if price is None or not supplier:
        return ""
    offers = _json_value(record.get("supplier_offers"))
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return ""
    wanted_mpn = re.sub(r"[^A-Z0-9]", "", mpn.upper())
    wanted_supplier = supplier.strip().casefold()
    currencies = set()
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        offer_mpn = str(offer.get("mpn") or "").strip()
        normalized_offer_mpn = re.sub(r"[^A-Z0-9]", "", offer_mpn.upper())
        offer_supplier = str(
            offer.get("distributor") or offer.get("supplier") or offer.get("source") or ""
        ).strip().casefold()
        offer_price = _number(offer.get("unit_price"))
        currency = normalize_currency_code(offer.get("currency"))
        if (
            normalized_offer_mpn == wanted_mpn
            and offer_supplier == wanted_supplier
            and offer_price is not None
            and math.isclose(float(offer_price), float(price), rel_tol=1e-8, abs_tol=1e-8)
            and currency
        ):
            currencies.add(currency)
    return next(iter(currencies)) if len(currencies) == 1 else ""


def _currency_totals(rows: list[dict[str, Any]], *, predicate=None) -> str:
    totals: dict[str, float] = {}
    for row in rows:
        if predicate is not None and not predicate(row):
            continue
        amount = row.get("Extended cost")
        currency = str(row.get("Unit price currency") or "").strip()
        if (
            not isinstance(amount, (int, float))
            or not currency
            or currency.casefold() in {"—", "not reported", "unknown"}
        ):
            continue
        totals[currency] = totals.get(currency, 0.0) + float(amount)
    return "; ".join(
        f"{currency} {amount:,.2f}" for currency, amount in sorted(totals.items())
    ) or "Not available from recorded currency data"


def _longest_reported_lead(rows: list[dict[str, Any]]) -> str:
    candidates = [
        row for row in rows
        if isinstance(row.get("Lead time (weeks)"), (int, float))
        and row["Lead time (weeks)"] > 0
    ]
    if not candidates:
        return "Not reported"
    row = max(candidates, key=lambda item: float(item["Lead time (weeks)"]))
    source = row.get("Lead-time source")
    source_note = f" ({source})" if source and source != "—" else ""
    return f"{row['Lead time (weeks)']:g} weeks — {row['MPN']}{source_note}"


def _is_high_or_lifecycle_risk(row: dict[str, Any]) -> bool:
    lifecycle = str(row.get("Lifecycle") or "").casefold()
    return row.get("Risk") == "High" or any(
        token in lifecycle for token in ("obsolete", "eol", "end of life", "nrnd")
    )


def report_exposure_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize quoted BOM cost and lead-time evidence without projecting spend or delay."""
    high_rows = [row for row in rows if _is_high_or_lifecycle_risk(row)]
    return {
        "priced_component_count": sum(
            isinstance(row.get("Extended cost"), (int, float)) for row in rows
        ),
        "priced_missing_currency_count": sum(
            isinstance(row.get("Extended cost"), (int, float))
            and row.get("Unit price currency") == "Not reported"
            for row in rows
        ),
        "extended_amount_by_currency": _currency_totals(rows),
        "high_risk_amount_by_currency": _currency_totals(
            rows, predicate=_is_high_or_lifecycle_risk
        ),
        "high_risk_without_extended_cost_count": sum(
            not isinstance(row.get("Extended cost"), (int, float))
            for row in high_rows
        ),
        "high_risk_missing_currency_count": sum(
            isinstance(row.get("Extended cost"), (int, float))
            and row.get("Unit price currency") == "Not reported"
            for row in high_rows
        ),
        "longest_reported_lead_time": _longest_reported_lead(rows),
        "components_with_lead_time_count": sum(
            isinstance(row.get("Lead time (weeks)"), (int, float)) for row in rows
        ),
    }


def _safe_cell(value: Any) -> Any:
    """Prevent user or supplier text from becoming an Excel/CSV formula."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def component_rows(
    parts: list[dict[str, Any]] | None,
    approved_alternatives: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Convert stored component records to an explicitly whitelisted report schema."""
    from src.ui.ei_bom_report import _description_text
    from src.approved_alternatives import approved_mpn_map, part_key
    from src.alternate_reference_parser import extract_description_alternates
    from src.saved_bom_cost import extended_cost

    approved_by_part = approved_mpn_map(approved_alternatives)
    output = []
    for record in parts or []:
        if not isinstance(record, dict):
            continue
        risk, score = _risk(record)
        lifecycle = _text(_first(record, "lifecycle_status", "Lifecycle Status", "lifecycle"), "Unknown")
        stock_sources = _sources(record)
        complete = _flag(record.get("stock_data_complete"))
        supplier_count_value = _number(_first(record, "supplier_count", "Supplier Count", "Suppliers"))
        has_supplier_evidence = stock_sources != "—" or (supplier_count_value or 0) > 0
        coverage = (
            "Complete"
            if complete is True
            else "Incomplete"
            if complete is False and has_supplier_evidence
            else "Unavailable"
        )
        conflict = _flag(record.get("lifecycle_conflict"))
        evidence_conflict = (
            "Conflict detected" if conflict is True
            else "No conflict recorded" if conflict is False
            else "Unavailable"
        )
        price = _number(_first(record, "unit_price", "Unit Price", "price"))
        mpn = _text(_first(record, "mpn", "MPN", "part_number", "manufacturer_part_number"))
        supplier = _text(_first(record, "primary_supplier", "best_source", "supplier", "distributor"), "")
        quantity = _number(_first(record, "quantity", "Quantity", "qty"))
        extended = extended_cost(price, quantity)
        price_currency = _price_currency(
            record, mpn=mpn, supplier=supplier, price=price
        )
        description = _first(record, "description", "Description", "part_description")
        description_alternates = extract_description_alternates(description)
        output.append({
            "MPN": mpn,
            "Description": _text(
                _description_text(description)
            ),
            "Manufacturer": _text(_first(record, "manufacturer", "Manufacturer")),
            "Qty": quantity
            if quantity is not None
            else _text(_first(record, "quantity", "Quantity", "qty")),
            "Lifecycle": lifecycle,
            "Stock": _stock(record),
            "Evidence source": stock_sources,
            "Approved alternatives": ", ".join(
                str(item.get("alternative_part") or "").strip()
                for item in approved_by_part.get(
                    part_key(_first(record, "mpn", "MPN", "part_number", "manufacturer_part_number")), []
                )
                if str(item.get("alternative_part") or "").strip()
            ) or "—",
            "Recorded supplier": supplier or "—",
            "Stock coverage": coverage,
            "Lead time (weeks)": _lead_time(record),
            "Lead-time source": _text(record.get("lead_time_source")),
            "Supplier count": _supplier_count(record),
            "Supplier coverage": _text(record.get("supplier_coverage")),
            "Risk": risk,
            "Risk score": score if score is not None else ("Not assessed" if risk == "Not assessed" else "Not recorded"),
            "Why": _reasons(record),
            "Lifecycle evidence": _lifecycle_evidence(record.get("lifecycle_evidence")),
            "Lifecycle conflict": evidence_conflict,
            "Alternate search status": _text(record.get("alternate_search_status")),
            "Unit price": price if price is not None and price > 0 else "—",
            "Unit price currency": price_currency or "Not reported",
            "Extended cost": extended if extended is not None else "—",
            "Description-mentioned alternatives": ", ".join(description_alternates) or "—",
        })
    return output


def detailed_risk_csv_bytes(
    parts: list[dict[str, Any]] | None,
    approved_alternatives: list[dict[str, Any]] | None = None,
) -> bytes:
    """CSV export with the same user-facing columns as the Stress Free audit."""
    rows = [
        {
            "MPN": row["MPN"],
            "Qty": row["Qty"],
            "Lifecycle": row["Lifecycle"],
            "Stock": row["Stock"],
            "Lead time (weeks)": row["Lead time (weeks)"],
            "Suppliers": row["Supplier count"],
            "Evidence source": row["Evidence source"],
            "Approved alternatives": row["Approved alternatives"],
            "Risk": row["Risk"],
            "Why": row["Why"],
            "Unit price": row["Unit price"],
            "Unit price currency": row["Unit price currency"],
            "Extended cost": row["Extended cost"],
            "Description-mentioned alternatives": row["Description-mentioned alternatives"],
        }
        for row in component_rows(parts, approved_alternatives)
    ]
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows({key: _safe_cell(row[key]) for key in CSV_COLUMNS} for row in rows)
    return buffer.getvalue().encode("utf-8-sig")


def _report_date(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "—"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone().strftime("%b %d, %Y %H:%M %Z")
        return parsed.strftime("%b %d, %Y %H:%M")
    except (TypeError, ValueError):
        return raw[:10] if len(raw) >= 10 else raw


def detailed_risk_excel_bytes(
    parts: list[dict[str, Any]] | None,
    *,
    bom_name: str,
    source_filename: str = "",
    analyzed_on: Any = "",
    approved_alternatives: list[dict[str, Any]] | None = None,
) -> bytes:
    """Build a branded, evidence-aware workbook without database identifiers."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    rows = component_rows(parts, approved_alternatives)
    high_rows = [row for row in rows if row["Risk"] == "High"]
    workbook = Workbook()
    workbook.properties.title = "Cadivor BOM Risk Report"
    workbook.properties.subject = "Saved BOM risk and supplier evidence"
    workbook.properties.creator = "Cadivor"

    navy = "17324D"
    blue = "2563EB"
    pale_blue = "EFF6FF"
    grid = "D9E2EC"
    white = "FFFFFF"
    risk_fills = {
        "High": "FEE2E2",
        "Medium": "FEF3C7",
        "Low": "DCFCE7",
        "Not assessed": "E2E8F0",
    }
    border = Border(bottom=Side(style="thin", color=grid))

    summary = workbook.active
    summary.title = "Summary"
    summary.sheet_view.showGridLines = False
    summary.merge_cells("A1:B1")
    summary["A1"] = "Cadivor BOM Risk Report"
    summary["A1"].font = Font(name="Aptos Display", size=20, bold=True, color=white)
    summary["A1"].fill = PatternFill("solid", fgColor=navy)
    summary["A1"].alignment = Alignment(vertical="center")
    summary.row_dimensions[1].height = 36
    summary.merge_cells("A2:B2")
    summary["A2"] = "Engineering risk and supplier evidence for the saved BOM analysis"
    summary["A2"].font = Font(name="Aptos", size=10, color="52647A", italic=True)
    summary["A2"].alignment = Alignment(wrap_text=True, vertical="center")
    summary.row_dimensions[2].height = 25

    meta = [
        ("Project / BOM", _safe_cell(_text(bom_name, "Saved BOM"))),
        ("Source file", _safe_cell(_text(source_filename))),
        ("Analyzed on", _safe_cell(_report_date(analyzed_on))),
    ]
    for row_index, (label, value) in enumerate(meta, start=4):
        summary.cell(row_index, 1, label)
        summary.cell(row_index, 2, value)

    counts = {level: sum(row["Risk"] == level for row in rows) for level in ("High", "Medium", "Low", "Not assessed")}
    eol_count = sum(any(token in row["Lifecycle"].casefold() for token in ("obsolete", "eol", "end of life", "nrnd")) for row in rows)
    unknown_lifecycle = sum(row["Lifecycle"].casefold() in {"unknown", "not recorded", "—"} for row in rows)
    unreported_stock = sum(row["Stock"] == "Not reported" for row in rows)
    stock_coverage_counts = {
        state: sum(row["Stock coverage"] == state for row in rows)
        for state in ("Complete", "Incomplete", "Unavailable")
    }
    exposure = report_exposure_summary(rows)
    risk_assessed_count = counts["High"] + counts["Medium"] + counts["Low"]
    risk_coverage = risk_assessed_count / len(rows) if rows else 0
    supplier_match_count = sum(_has_supplier_match(part) for part in parts or [] if isinstance(part, dict))
    metrics = [
        ("Total components", len(rows)),
        ("Parts with matched supplier evidence", supplier_match_count),
        ("Risk assessed", risk_assessed_count),
        ("Risk coverage", f"{risk_coverage:.0%}"),
        ("High risk", counts["High"]),
        ("Medium risk", counts["Medium"]),
        ("Low risk", counts["Low"]),
        ("Risk not assessed", counts["Not assessed"]),
        ("Obsolete / EOL / NRND lifecycle", eol_count),
        ("Unknown lifecycle", unknown_lifecycle),
        ("Stock not reported", unreported_stock),
        ("Stock coverage complete", stock_coverage_counts["Complete"]),
        ("Stock coverage incomplete", stock_coverage_counts["Incomplete"]),
        ("Stock coverage unavailable", stock_coverage_counts["Unavailable"]),
        ("Components with approved alternatives", sum(row["Approved alternatives"] != "—" for row in rows)),
        ("Priced components with BOM quantity", exposure["priced_component_count"]),
        ("Priced components missing currency", exposure["priced_missing_currency_count"]),
        ("Extended BOM amount by recorded currency", exposure["extended_amount_by_currency"]),
        ("Priced high-risk / lifecycle extended cost by currency", exposure["high_risk_amount_by_currency"]),
        ("High-risk / lifecycle rows without extended cost", exposure["high_risk_without_extended_cost_count"]),
        ("Priced high-risk rows missing currency", exposure["high_risk_missing_currency_count"]),
        ("Longest reported part lead time", exposure["longest_reported_lead_time"]),
        ("Components with lead-time data", exposure["components_with_lead_time_count"]),
        ("Description-mentioned replacement candidates", sum(row["Description-mentioned alternatives"] != "—" for row in rows)),
    ]
    unassessed_count = counts["Not assessed"]
    if not rows:
        coverage_note = "No component records were available to assess in this report."
    elif unassessed_count or supplier_match_count < len(rows):
        unmatched_count = len(rows) - supplier_match_count
        coverage_note = (
            f"Risk was assessed for {risk_assessed_count} of {len(rows)} parts "
            f"({risk_coverage:.0%}). {unassessed_count} part(s) remain unassessed; "
            f"{unmatched_count} part(s) have no matched supplier evidence. These counts "
            "can refer to the same part. An unassessed result is not evidence of low risk; "
            "verify the manufacturer part number and rerun."
        )
    else:
        coverage_note = (
            f"Risk ratings are recorded for all {len(rows)} parts, with matched "
            "supplier evidence present. Values reflect the analysis date shown above."
        )
    summary.merge_cells("A7:B7")
    summary["A7"] = _safe_cell(coverage_note)
    summary["A7"].font = Font(name="Aptos", size=10, bold=True, color="7C2D12")
    summary["A7"].fill = PatternFill("solid", fgColor="FFF7ED")
    summary["A7"].alignment = Alignment(wrap_text=True, vertical="center")
    summary.row_dimensions[7].height = 42

    summary.merge_cells("A8:B8")
    summary["A8"] = "Analysis summary"
    summary["A8"].font = Font(name="Aptos", size=12, bold=True, color=white)
    summary["A8"].fill = PatternFill("solid", fgColor=blue)
    for column, value in enumerate(("Metric", "Value"), start=1):
        cell = summary.cell(9, column, value)
        cell.font = Font(name="Aptos", bold=True, color=navy)
        cell.fill = PatternFill("solid", fgColor=pale_blue)
        cell.border = border
    for row_index, (label, value) in enumerate(metrics, start=10):
        summary.cell(row_index, 1, label)
        summary.cell(row_index, 2, value)
    note_row = 10 + len(metrics) + 2
    summary.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=2)
    summary.cell(note_row, 1, "Reading the report")
    summary.cell(note_row, 1).font = Font(name="Aptos", size=12, bold=True, color=navy)
    notes = (
        "Stock is shown as Not reported when the saved record has no usable count. A zero is shown only when stock-source evidence is recorded.",
        "A dash (—) means the saved analysis did not include that optional value. Re-run the analysis to refresh supplier evidence.",
        "Approved alternatives are user-recorded decisions. They do not independently verify electrical or mechanical compatibility.",
        "A replacement mentioned in a supplier description is an unverified search lead, not a confirmed or approved cross.",
        "Extended cost is recorded unit price × BOM quantity. Totals include only rows with an explicitly recorded currency and are grouped by currency. They are not inventory valuation or committed spend.",
        "The priced high-risk / lifecycle amount is only the subset with a usable unit price, BOM quantity, and currency. Rows without extended cost or currency are counted separately; this amount is not total exposure.",
        "The longest reported component lead time is a possible sourcing bottleneck, not a forecast of project delay.",
        "Risk ratings and reasons reflect the saved analysis. Re-run the analysis to refresh distributor data.",
    )
    for offset, note in enumerate(notes, start=1):
        cell = summary.cell(note_row + offset, 1, _safe_cell(note))
        summary.merge_cells(start_row=note_row + offset, start_column=1, end_row=note_row + offset, end_column=2)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        cell.font = Font(name="Aptos", size=10, color="52647A")
        summary.row_dimensions[note_row + offset].height = (
            42 if "priced high-risk / lifecycle amount" in note else 30
        )
    for row in summary.iter_rows(min_row=4, max_row=9 + len(metrics), min_col=1, max_col=2):
        for cell in row:
            cell.border = border
            if cell.row not in (8, 9):
                cell.alignment = Alignment(vertical="center", wrap_text=True)
    summary.column_dimensions["A"].width = 36
    summary.column_dimensions["B"].width = 62
    summary.freeze_panes = "A9"

    def add_table(sheet_name: str, data: list[dict[str, Any]], table_name: str) -> None:
        sheet = workbook.create_sheet(sheet_name)
        sheet.sheet_view.showGridLines = False
        for column_index, label in enumerate(DETAIL_COLUMNS, start=1):
            cell = sheet.cell(1, column_index, label)
            cell.font = Font(name="Aptos", size=10, bold=True, color=white)
            cell.fill = PatternFill("solid", fgColor=navy)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border
        sheet.row_dimensions[1].height = 32
        for row_index, row in enumerate(data, start=2):
            for column_index, label in enumerate(DETAIL_COLUMNS, start=1):
                value = _safe_cell(row.get(label, ""))
                cell = sheet.cell(row_index, column_index, value)
                cell.font = Font(name="Aptos", size=10, color="1E293B")
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = border
                if label == "Risk":
                    fill = risk_fills.get(str(row.get("Risk") or ""))
                    if fill:
                        cell.fill = PatternFill("solid", fgColor=fill)
                        cell.font = Font(name="Aptos", size=10, bold=True, color=navy)
                if label in {"Qty", "Stock", "Lead time (weeks)", "Supplier count", "Risk score", "Unit price", "Extended cost"} and isinstance(value, (int, float)):
                    cell.number_format = "#,##0.0000" if label == "Unit price" else "#,##0.00" if label == "Extended cost" else "#,##0.##"
        sheet.freeze_panes = "A2"
        last_column = get_column_letter(len(DETAIL_COLUMNS))
        sheet.auto_filter.ref = f"A1:{last_column}{max(1, len(data) + 1)}"
        sheet.print_title_rows = "1:1"
        widths = {
            "MPN": 24, "Description": 38, "Manufacturer": 24, "Qty": 10,
            "Lifecycle": 18, "Stock": 14, "Evidence source": 24, "Recorded supplier": 22,
            "Stock coverage": 18, "Lead time (weeks)": 17, "Lead-time source": 22,
            "Supplier count": 15, "Supplier coverage": 40, "Risk": 14,
            "Risk score": 13, "Why": 58, "Lifecycle evidence": 44,
            "Lifecycle conflict": 22, "Alternate search status": 38,
            "Approved alternatives": 28, "Unit price": 14,
            "Unit price currency": 19, "Extended cost": 16,
            "Description-mentioned alternatives": 38,
        }
        for index, label in enumerate(DETAIL_COLUMNS, start=1):
            sheet.column_dimensions[sheet.cell(1, index).column_letter].width = widths[label]
        if data:
            table = Table(displayName=table_name, ref=f"A1:{last_column}{len(data) + 1}")
            table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True, showColumnStripes=False)
            sheet.add_table(table)

    add_table("Component Details", rows, "CadivorComponentDetails")
    add_table("High Risk Parts", high_rows, "CadivorHighRiskParts")
    if not high_rows:
        high_sheet = workbook["High Risk Parts"]
        last_column = get_column_letter(len(DETAIL_COLUMNS))
        high_sheet.merge_cells(
            start_row=2,
            start_column=1,
            end_row=2,
            end_column=len(DETAIL_COLUMNS),
        )
        note = high_sheet.cell(
            2,
            1,
            _safe_cell(
                "No parts were classified High risk. "
                f"{unassessed_count} of {len(rows)} part(s) were not assessed; "
                "an unassessed part is not proof of low risk."
            ),
        )
        note.font = Font(name="Aptos", size=10, bold=True, color="7C2D12")
        note.fill = PatternFill("solid", fgColor="FFF7ED")
        note.alignment = Alignment(wrap_text=True, vertical="center")
        high_sheet.row_dimensions[2].height = 42
        high_sheet.auto_filter.ref = f"A1:{last_column}1"

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


"""Customer-facing evidence-aware exports for Cadivor BOM risk reports."""

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
    "Supplier product URL",
    "Datasheet URL",
    "Sourcing checked at",
    "Mitigation status",
    "Approved alternatives",
    "Alternate search status",
    "Candidate MPNs",
    "Risk",
    "Risk score",
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
    "Supplier product URL",
    "Datasheet URL",
    "Sourcing checked at",
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
    "Candidate MPNs",
    "Candidate count",
    "Mitigation status",
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
    value = _first(record, "stock_data_sources", "Stock Data Sources")
    names = _joined(value) if value not in (None, "", []) else ""
    if names:
        return names
    # Older/public analysis records may store the evidence-source list under
    # the public stress-test field name. Do not substitute the preferred price
    # supplier: it does not prove that supplier returned an inventory count.
    return _text(_first(record, "sources", "Sources Available"))


def _safe_http_url(value: Any) -> str:
    url = str(value or "").strip()
    return url if url.startswith(("https://", "http://")) else ""


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
        alternate_status = _text(
            _first(record, "alternate_search_status", "Alternate Search Status"),
            fallback="",
        )
        if "found related catalog lead(s)" in alternate_status.casefold():
            # Preserve the distinction between the requested BOM identity and
            # a related orderable variant. The lead is useful for review, but
            # its stock, price, and lifecycle cannot safely rate the original.
            route_status = alternate_status.split(";", 1)[0].strip()
            return (
                f"{route_status} Confirm that the package, electrical device, "
                "and ordering suffix meet the design requirements before using "
                "candidate evidence; this BOM part remains unassessed."
            )
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
            _text(
                _first(
                    record,
                    "primary_supplier",
                    "best_source",
                    "Best Source",
                    "supplier",
                    "distributor",
                ),
                "",
            ),
            _text(_first(record, "lead_time_source", "Lead Time Source"), ""),
            _lifecycle_evidence(
                _first(record, "lifecycle_evidence", "Lifecycle Evidence")
            ),
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
        _first(record, "unit_price_currency", "Unit Price Currency", "currency", "Currency")
    )
    if explicit:
        return explicit
    if price is None or not supplier:
        return ""
    offers = _json_value(_first(record, "supplier_offers", "Supplier Offers"))
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
    gross_high_rows = [row for row in rows if _is_high_or_lifecycle_risk(row)]
    open_high_rows = [
        row for row in gross_high_rows
        if not str(row.get("Mitigation status") or "").casefold().startswith("approved alternative")
    ]
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
            open_high_rows
        ),
        "gross_high_risk_amount_by_currency": _currency_totals(
            gross_high_rows
        ),
        "approved_high_risk_component_count": sum(
            str(row.get("Mitigation status") or "").casefold().startswith("approved alternative")
            for row in gross_high_rows
        ),
        "open_high_risk_component_count": len(open_high_rows),
        "approved_high_risk_amount_by_currency": _currency_totals(
            gross_high_rows,
            predicate=lambda row: str(row.get("Mitigation status") or "").casefold().startswith("approved alternative"),
        ),
        "high_risk_without_extended_cost_count": sum(
            not isinstance(row.get("Extended cost"), (int, float))
            for row in open_high_rows
        ),
        "high_risk_missing_currency_count": sum(
            isinstance(row.get("Extended cost"), (int, float))
            and row.get("Unit price currency") == "Not reported"
            for row in open_high_rows
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
        complete = _flag(_first(record, "stock_data_complete", "Stock Data Complete"))
        supplier_count_value = _number(_first(record, "supplier_count", "Supplier Count", "Suppliers"))
        has_supplier_evidence = stock_sources != "—" or (supplier_count_value or 0) > 0
        coverage = (
            "Complete"
            if complete is True
            else "Incomplete"
            if complete is False and has_supplier_evidence
            else "Unavailable"
        )
        conflict = _flag(_first(record, "lifecycle_conflict", "Lifecycle Conflict"))
        evidence_conflict = (
            "Conflict detected" if conflict is True
            else "No conflict recorded" if conflict is False
            else "Unavailable"
        )
        price = _number(_first(record, "unit_price", "Unit Price", "price"))
        mpn = _text(_first(record, "mpn", "MPN", "part_number", "manufacturer_part_number"))
        supplier = _text(
            _first(record, "primary_supplier", "best_source", "Best Source", "supplier", "distributor"),
            "",
        )
        quantity = _number(_first(record, "quantity", "Quantity", "qty"))
        extended = extended_cost(price, quantity)
        price_currency = _price_currency(
            record, mpn=mpn, supplier=supplier, price=price
        )
        description = _first(record, "description", "Description", "part_description")
        description_alternates = extract_description_alternates(description)
        from src.alternate_candidate_evidence import normalize_candidate_evidence

        candidates = normalize_candidate_evidence(
            _first(record, "alternate_candidates", "Alternate Candidates", default=[]),
            original_mpn=mpn,
        )
        alternate_status = _text(
            _first(record, "alternate_search_status", "Alternate Search Status")
        )
        candidate_mpns = ", ".join(item["mpn"] for item in candidates)
        if not candidate_mpns and "candidate" in alternate_status.casefold() and "returned" in alternate_status.casefold():
            candidate_mpns = "Candidate details were not saved in this analysis snapshot"
        product_url = _safe_http_url(
            _first(record, "product_url", "Product URL", "product_detail_url", "source_url")
        )
        datasheet_url = _safe_http_url(
            _first(record, "datasheet_url", "Datasheet URL", "datasheet", "datasheet_link")
        )
        approvals = approved_by_part.get(
            part_key(_first(record, "mpn", "MPN", "part_number", "manufacturer_part_number")),
            [],
        )
        approved_names = [
            str(item.get("alternative_part") or "").strip()
            for item in approvals
            if str(item.get("alternative_part") or "").strip()
        ]
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
            "Supplier product URL": product_url or "—",
            "Datasheet URL": datasheet_url or "—",
            "Sourcing checked at": _text(
                _first(record, "sourcing_updated_at", "retrieved_at", "updated_at")
            ),
            "Mitigation status": (
                "Approved alternative (BOM update pending)"
                if approved_names
                else "No approved alternative"
            ),
            "Approved alternatives": ", ".join(approved_names) or "—",
            "Recorded supplier": supplier or "—",
            "Stock coverage": coverage,
            "Lead time (weeks)": _lead_time(record),
            "Lead-time source": _text(_first(record, "lead_time_source", "Lead Time Source")),
            "Supplier count": _supplier_count(record),
            "Supplier coverage": _text(
                _first(record, "supplier_coverage", "Supplier Coverage")
            ),
            "Risk": risk,
            "Risk score": score if score is not None else ("Not assessed" if risk == "Not assessed" else "Not recorded"),
            "Why": _reasons(record),
            "Lifecycle evidence": _lifecycle_evidence(
                _first(record, "lifecycle_evidence", "Lifecycle Evidence")
            ),
            "Lifecycle conflict": evidence_conflict,
            "Alternate search status": alternate_status,
            "Candidate MPNs": candidate_mpns or "—",
            "Candidate count": len(candidates) if candidates else ("Not saved" if candidate_mpns else 0),
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
            "Supplier product URL": row["Supplier product URL"],
            "Datasheet URL": row["Datasheet URL"],
            "Sourcing checked at": row["Sourcing checked at"],
            "Mitigation status": row["Mitigation status"],
            "Approved alternatives": row["Approved alternatives"],
            "Alternate search status": row["Alternate search status"],
            "Candidate MPNs": row["Candidate MPNs"],
            "Risk": row["Risk"],
            "Risk score": row["Risk score"],
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


def _candidate_rows(parts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    from src.alternate_candidate_evidence import normalize_candidate_evidence

    output = []
    for record in parts or []:
        if not isinstance(record, dict):
            continue
        source_mpn = _text(_first(record, "mpn", "MPN", "part_number", "manufacturer_part_number"))
        for candidate in normalize_candidate_evidence(
            _first(record, "alternate_candidates", "Alternate Candidates", default=[]),
            original_mpn=source_mpn,
        ):
            output.append({
                "Source MPN": source_mpn,
                "Candidate MPN": candidate["mpn"],
                "Manufacturer": candidate["manufacturer"] or "—",
                "Supplier": candidate["supplier"] or "—",
                "Relationship label": candidate["relationship"] or "Unclassified supplier lead",
                "Evidence type": candidate["evidence_type"] or "—",
                "Discovery scope": candidate["discovery_scope"] or "—",
                "Primary category": candidate["primary_category"] or "—",
                "Description": candidate["description"] or "—",
                "Package": candidate["package"] or "—",
                "Pin count": candidate["pin_count"] if candidate["pin_count"] is not None else "Not reported",
                "Architecture": candidate["architecture"] or "—",
                "Lifecycle": candidate["lifecycle"] or "Unknown",
                "Candidate risk": candidate["risk_level"] or "Needs verification",
                "Candidate risk score": candidate["risk_score"] if candidate["risk_score"] is not None else "Not assessed",
                "Candidate risk reasons": candidate["risk_reasons"] or "—",
                "Supplier product URL": candidate["product_url"] or "—",
                "Datasheet URL": candidate["datasheet_url"] or "—",
                "Retrieved at": candidate["retrieved_at"] or "—",
                "Approval status": "Unapproved search lead; technical compatibility not established",
            })
    return output


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
        ("Gross priced high-risk / lifecycle extended cost by currency", exposure["gross_high_risk_amount_by_currency"]),
        ("High-risk components with approved alternatives", exposure["approved_high_risk_component_count"]),
        ("Open high-risk / lifecycle components", exposure["open_high_risk_component_count"]),
        ("High-risk / lifecycle rows without extended cost", exposure["high_risk_without_extended_cost_count"]),
        ("Priced high-risk rows missing currency", exposure["high_risk_missing_currency_count"]),
        ("Longest reported part lead time", exposure["longest_reported_lead_time"]),
        ("Components with lead-time data", exposure["components_with_lead_time_count"]),
        ("Description-mentioned replacement candidates", sum(row["Description-mentioned alternatives"] != "—" for row in rows)),
        ("Components with a saved supplier product link", sum(row["Supplier product URL"] != "—" for row in rows)),
        ("Components with a saved datasheet link", sum(row["Datasheet URL"] != "—" for row in rows)),
        ("Components with named candidates saved", sum(isinstance(row["Candidate count"], int) and row["Candidate count"] > 0 for row in rows)),
        ("Unapproved candidate records saved", len(_candidate_rows(parts))),
        ("Searches reporting candidates without saved candidate details", sum(
            row["Candidate count"] == "Not saved" for row in rows
        )),
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
        "Approved alternatives are user-recorded engineering decisions. They do not independently certify electrical or mechanical compatibility, and the source BOM is unchanged until a revised BOM is uploaded.",
        "A replacement mentioned in a supplier description is an unverified search lead, not a confirmed or approved cross.",
        "Rows on Alternative Candidates are unapproved catalog leads. A supplier similarity label, matching family, or datasheet link does not establish drop-in compatibility; engineers must compare electrical ratings, architecture, pinout, footprint, dimensions, and operating conditions.",
        "The saved score is additive and capped at 100: lifecycle conflict +35; obsolete/EOL/discontinued +50; NRND +35; replacement suggested or factory special order +20; confirmed zero stock +45; stock below BOM quantity +15 to +35; sufficiently covered supplier concentration +5 to +25; lead time 8+ weeks +10, 12+ weeks +15, 26+ weeks +30, and 52+ weeks +35. Bands are 0–29 Low, 30–59 Medium, and 60–100 High. Without usable risk evidence, the result is Needs verification. Read the row reasons and evidence before acting; this score is a sourcing triage signal, not a technical compatibility verdict.",
        "Extended cost is recorded unit price × BOM quantity. Totals include only rows with an explicitly recorded currency and are grouped by currency. They are not inventory valuation or committed spend.",
        "Open priced high-risk / lifecycle cost excludes line items with a saved approved alternative; gross cost still includes those original BOM lines. Both figures use only rows with a usable unit price, BOM quantity, and currency. Rows without extended cost or currency are counted separately; these amounts are not total exposure.",
        "The longest reported component lead time is a possible sourcing bottleneck, not a forecast of project delay.",
        "Risk ratings and reasons reflect the saved analysis. Re-run the analysis to refresh distributor data.",
    )
    for offset, note in enumerate(notes, start=1):
        cell = summary.cell(note_row + offset, 1, _safe_cell(note))
        summary.merge_cells(start_row=note_row + offset, start_column=1, end_row=note_row + offset, end_column=2)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        cell.font = Font(name="Aptos", size=10, color="52647A")
        summary.row_dimensions[note_row + offset].height = (
            72 if "saved score is additive" in note else
            52 if "open priced high-risk / lifecycle cost" in note else
            48 if "Alternative Candidates" in note else 30
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
                if label in {"Supplier product URL", "Datasheet URL"} and _safe_http_url(value):
                    cell.hyperlink = _safe_http_url(value)
                    cell.font = Font(name="Aptos", size=10, color=blue, underline="single")
                if label in {"Qty", "Stock", "Lead time (weeks)", "Supplier count", "Risk score", "Unit price", "Extended cost"} and isinstance(value, (int, float)):
                    cell.number_format = "#,##0.0000" if label == "Unit price" else "#,##0.00" if label == "Extended cost" else "#,##0.##"
        sheet.freeze_panes = "A2"
        last_column = get_column_letter(len(DETAIL_COLUMNS))
        sheet.auto_filter.ref = f"A1:{last_column}{max(1, len(data) + 1)}"
        sheet.print_title_rows = "1:1"
        widths = {
            "MPN": 24, "Description": 38, "Manufacturer": 24, "Qty": 10,
            "Lifecycle": 18, "Stock": 14, "Evidence source": 24, "Recorded supplier": 22,
            "Supplier product URL": 34, "Datasheet URL": 34, "Sourcing checked at": 24,
            "Stock coverage": 18, "Lead time (weeks)": 17, "Lead-time source": 22,
            "Supplier count": 15, "Supplier coverage": 40, "Risk": 14,
            "Risk score": 13, "Mitigation status": 34, "Why": 58, "Lifecycle evidence": 44,
            "Lifecycle conflict": 22, "Alternate search status": 38,
            "Candidate MPNs": 34, "Candidate count": 16,
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

    candidate_data = _candidate_rows(parts)
    candidate_sheet = workbook.create_sheet("Alternative Candidates")
    candidate_sheet.sheet_view.showGridLines = False
    candidate_sheet.merge_cells("A1:T1")
    candidate_sheet["A1"] = "Unapproved alternatives found during BOM analysis"
    candidate_sheet["A1"].font = Font(name="Aptos Display", size=16, bold=True, color=white)
    candidate_sheet["A1"].fill = PatternFill("solid", fgColor=navy)
    candidate_sheet["A1"].alignment = Alignment(vertical="center")
    candidate_sheet.row_dimensions[1].height = 30
    candidate_sheet.merge_cells("A2:T2")
    candidate_sheet["A2"] = (
        "These are search leads, not approved replacements or drop-in certifications. "
        "Validate the source and candidate datasheets, package dimensions, pinout, architecture, "
        "electrical limits, and operating conditions before engineering approval."
    )
    candidate_sheet["A2"].font = Font(name="Aptos", size=10, color="7C2D12", bold=True)
    candidate_sheet["A2"].fill = PatternFill("solid", fgColor="FFF7ED")
    candidate_sheet["A2"].alignment = Alignment(wrap_text=True, vertical="center")
    candidate_sheet.row_dimensions[2].height = 42
    candidate_columns = (
        "Source MPN", "Candidate MPN", "Manufacturer", "Supplier", "Relationship label",
        "Evidence type", "Discovery scope", "Primary category", "Description", "Package",
        "Pin count", "Architecture", "Lifecycle", "Candidate risk", "Candidate risk score",
        "Candidate risk reasons", "Supplier product URL", "Datasheet URL", "Retrieved at", "Approval status",
    )
    for column_index, label in enumerate(candidate_columns, start=1):
        cell = candidate_sheet.cell(4, column_index, label)
        cell.font = Font(name="Aptos", size=10, bold=True, color=white)
        cell.fill = PatternFill("solid", fgColor=navy)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    candidate_sheet.row_dimensions[4].height = 34
    for row_index, record in enumerate(candidate_data, start=5):
        for column_index, label in enumerate(candidate_columns, start=1):
            value = _safe_cell(record.get(label, "—"))
            cell = candidate_sheet.cell(row_index, column_index, value)
            cell.font = Font(name="Aptos", size=10, color="1E293B")
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = border
            if label in {"Supplier product URL", "Datasheet URL"} and _safe_http_url(value):
                cell.hyperlink = _safe_http_url(value)
                cell.font = Font(name="Aptos", size=10, color=blue, underline="single")
    if not candidate_data:
        candidate_sheet.merge_cells("A5:T5")
        candidate_sheet["A5"] = "No named candidate evidence was saved with this analysis."
        candidate_sheet["A5"].font = Font(name="Aptos", size=10, color="52647A", italic=True)
        candidate_sheet["A5"].alignment = Alignment(vertical="center")
    else:
        candidate_sheet.auto_filter.ref = f"A4:T{len(candidate_data) + 4}"
        table = Table(displayName="CadivorAlternativeCandidates", ref=f"A4:T{len(candidate_data) + 4}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True, showColumnStripes=False)
        candidate_sheet.add_table(table)
    candidate_sheet.freeze_panes = "A5"
    candidate_sheet.print_title_rows = "1:4"
    for index, label in enumerate(candidate_columns, start=1):
        candidate_sheet.column_dimensions[get_column_letter(index)].width = {
            "Source MPN": 24, "Candidate MPN": 24, "Manufacturer": 22, "Supplier": 18,
            "Relationship label": 30, "Evidence type": 25, "Discovery scope": 24,
            "Primary category": 28, "Description": 40, "Package": 20, "Pin count": 13,
            "Architecture": 24, "Lifecycle": 18, "Candidate risk": 20,
            "Candidate risk score": 21, "Candidate risk reasons": 48,
            "Supplier product URL": 34, "Datasheet URL": 34, "Retrieved at": 24,
            "Approval status": 56,
        }[label]

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


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
    "BOM manufacturer",
    "Supplier manufacturer",
    "Manufacturer source",
    "Qty",
    "Lifecycle",
    "Stock",
    "Stock evidence",
    "Lead time (weeks)",
    "Lead-time source",
    "Lead-time checked at",
    "Lead-time evidence",
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
    "BOM manufacturer",
    "Supplier manufacturer",
    "Manufacturer source",
    "Qty",
    "Lifecycle",
    "Stock",
    "Stock evidence",
    "Stock aggregation",
    "Evidence source",
    "Supplier product URL",
    "Datasheet URL",
    "Sourcing checked at",
    "Recorded supplier",
    "Stock coverage",
    "Lead time (weeks)",
    "Lead-time source",
    "Lead-time checked at",
    "Lead-time evidence",
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


def _evidence_readings(value: Any, *, key: str, unit: str = "") -> str:
    """Format source-specific values and timestamps without losing lineage."""
    value = _json_value(value)
    if isinstance(value, dict):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = [item for item in value if isinstance(item, dict)]
    else:
        return _text(value, "")
    readings = []
    for item in items:
        amount = item.get(key)
        source = _text(
            _first(item, "source", "distributor", "supplier", "vendor"), ""
        )
        if amount in (None, ""):
            continue
        label = f"{source}: " if source else ""
        label += f"{amount}{(' ' + unit) if unit else ''}"
        if item.get("retrieved_at"):
            label += f" (retrieved {item['retrieved_at']})"
        readings.append(label)
    return "; ".join(readings) or "—"


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
        # Risk Level == High only — matches report/decision-queue high_risk_count.
        # open_high_risk_component_count also includes NRND/EOL lifecycle exposure.
        "high_risk_component_count": sum(1 for row in rows if row.get("Risk") == "High"),
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
            and row.get("Unit price currency") 
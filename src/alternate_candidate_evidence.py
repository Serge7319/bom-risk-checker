"""Small, explicit candidate evidence snapshots for saved BOM analysis rows."""

from __future__ import annotations

import json
import math
import re
from typing import Any


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip().casefold() not in {"", "nan", "none", "null"}:
            return value
    return None


def _mpn_key(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _url(value: Any) -> str:
    text = str(value or "").strip()
    return text if text.startswith(("https://", "http://")) else ""


def _supplier_url(value: Any, supplier: Any) -> str:
    from src.supplier_source_identity import supplier_listing_url_is_valid

    text = str(value or "").strip()
    return text if supplier_listing_url_is_valid(supplier, text) else ""


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


def normalize_candidate_evidence(value: Any, *, original_mpn: str = "") -> list[dict[str, Any]]:
    """Keep a bounded allowlist of search evidence; never serialize API internals."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []

    original_key = _mpn_key(original_mpn)
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for candidate in value:
        if not isinstance(candidate, dict):
            continue
        mpn = str(
            _first(candidate, "Alternative Part", "alternative_part", "manufacturer_part_number", "mpn", "MPN")
            or ""
        ).strip()
        key = _mpn_key(mpn)
        if not mpn or not key or key == original_key or key in seen:
            continue
        seen.add(key)

        pin_count = _number(_first(candidate, "pin_count", "Pin Count"))
        if pin_count is not None and pin_count <= 0:
            pin_count = None
        risk_score = _number(_first(candidate, "Estimated Risk Score", "risk_score"))
        unit_price = _number(_first(candidate, "Unit Price", "unit_price", "price"))
        if unit_price is not None and unit_price <= 0:
            unit_price = None
        stock = _number(_first(candidate, "Stock", "stock_total", "stock_available"))
        lead_time = _number(_first(candidate, "Lead Time Weeks", "lead_time_weeks"))
        reasons = _first(candidate, "Risk Reasons", "risk_reasons")
        if isinstance(reasons, (list, tuple, set)):
            reasons = "; ".join(str(item).strip() for item in reasons if str(item).strip())

        output.append({
            "mpn": mpn,
            "manufacturer": str(_first(candidate, "Manufacturer", "manufacturer") or "").strip(),
            "description": str(_first(candidate, "description", "Description") or "").strip(),
            "supplier": str(_first(candidate, "Supplier", "Evidence Source", "source") or "").strip(),
            "relationship": str(_first(candidate, "Classification", "Category", "classification") or "").strip(),
            "evidence_type": str(_first(candidate, "Evidence Type", "evidence_type") or "").strip(),
            "discovery_scope": str(_first(candidate, "Discovery Scope", "discovery_scope") or "").strip(),
            "substitute_type": str(_first(candidate, "Substitute Type", "substitute_type") or "").strip(),
            "primary_category": str(_first(candidate, "Primary Category", "primary_category") or "").strip(),
            "package": str(_first(candidate, "package", "Package") or "").strip(),
            "pin_count": pin_count,
            "architecture": str(_first(candidate, "architecture", "Architecture", "device_family") or "").strip(),
            "lifecycle": str(_first(candidate, "Lifecycle", "lifecycle_status", "Lifecycle Status") or "Unknown").strip(),
            "risk_level": str(_first(candidate, "Estimated Risk", "risk_level") or "Needs verification").strip(),
            "risk_score": risk_score,
            "risk_reasons": str(reasons or "").strip(),
            "stock": stock,
            "unit_price": unit_price,
            "currency": str(_first(candidate, "Currency", "unit_price_currency", "currency") or "").strip(),
            "lead_time_weeks": lead_time,
            "lead_time_source": str(_first(candidate, "lead_time_source", "Supplier", "Evidence Source") or "").strip(),
            "retrieved_at": str(_first(candidate, "Retrieved At", "retrieved_at", "checked_at") or "").strip(),
            "field_sources": dict(_first(candidate, "field_sources") or {})
            if isinstance(_first(candidate, "field_sources"), dict) else {},
            "supplier_offers": [dict(item) for item in candidate.get("supplier_offers", []) if isinstance(item, dict)]
            if isinstance(candidate.get("supplier_offers"), list) else [],
            "compliance_evidence": dict(_first(candidate, "compliance_evidence") or {})
            if isinstance(_first(candidate, "compliance_evidence"), dict) else {},
            "product_url": _supplier_url(
                _first(candidate, "Product URL", "product_detail_url", "Source URL", "source_url"),
                _first(candidate, "Supplier", "Evidence Source", "source"),
            ),
            "datasheet_url": _url(_first(candidate, "Datasheet URL", "datasheet_url", "datasheet")),
            "retrieved_at": str(_first(candidate, "Retrieved At", "retrieved_at", "checked_at") or "").strip(),
        })
    return output

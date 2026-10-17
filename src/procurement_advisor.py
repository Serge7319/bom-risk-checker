"""Compact procurement intelligence used by Cadivor's overview and Procurement Advisor."""
from __future__ import annotations
from datetime import datetime
import json
import math
from typing import Any, Dict, Iterable, Mapping
import pandas as pd
from src.part_images import normalize_supplier_image_url, part_image_markup


SOURCING_OVERRIDE_FIELDS = (
    "primary_supplier",
    "unit_price",
    "currency",
    "stock_available",
    "lead_time_weeks",
    "supplier_count",
    "lifecycle_status",
)

def _t(v, default=""):
    if v is None:
        return default
    v = str(v).strip()
    return default if v.casefold() in {"", "nan", "none", "null"} else v

def _n(v, default=0.0):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return default
        return float(v)
    except Exception:
        return default


def _maybe_n(value):
    """Parse a recorded finite number; blanks and invalid values stay unknown."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str) and value.strip().casefold() in {"", "nan", "none", "null", "—", "-"}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _truthy(value):
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "verified"}
    return bool(value)


def _parse_override(value):
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def apply_sourcing_override(part: Mapping[str, Any]) -> Dict[str, Any]:
    """Overlay user-verified, current sourcing values without rewriting BOM evidence."""
    row = dict(part or {})
    override = _parse_override(row.get("sourcing_override"))
    row["_sourcing_override_fields"] = frozenset(override)
    for field in SOURCING_OVERRIDE_FIELDS:
        if field in override:
            row[field] = override[field]
    if override:
        row["supplier_data_verified"] = any(
            override.get(field) not in (None, "")
            for field in SOURCING_OVERRIDE_FIELDS
        )
    return row


def normalize_sourcing_override(values: Mapping[str, Any]):
    """Validate editable sourcing values. Empty fields remain None, never zero defaults."""
    payload: Dict[str, Any] = {}
    errors = []
    payload["primary_supplier"] = _t(values.get("primary_supplier")) or None
    payload["lifecycle_status"] = _t(values.get("lifecycle_status")) or None
    payload["currency"] = _t(values.get("currency")).upper() or None
    for field, label, integer_only in (
        ("unit_price", "Unit price", False),
        ("stock_available", "Available stock", True),
        ("lead_time_weeks", "Lead time", False),
        ("supplier_count", "Supplier count", True),
    ):
        raw = values.get(field)
        if raw is None or str(raw).strip() == "":
            payload[field] = None
            continue
        number = _maybe_n(raw)
        if number is None or number < 0 or (integer_only and not number.is_integer()):
            errors.append(f"{label} must be a non-negative {'whole number' if integer_only else 'number'}, or blank.")
            continue
        payload[field] = int(number) if integer_only else number
    if payload.get("unit_price") is not None and not payload.get("currency"):
        errors.append("Currency code is required when entering a unit price.")
    return payload, errors


def persist_sourcing_update(
    supabase,
    *,
    user_id: str,
    mpn: str,
    workspace_id: str = "",
    description: str = "",
    category: str = "",
    sourcing_override: Mapping[str, Any],
    updated_at: str,
) -> int:
    """Save current sourcing metadata to matching rows owned by this user/workspace."""
    part_number = str(mpn or "").strip()
    if not str(user_id or "").strip() or not part_number:
        raise ValueError("A signed-in user and component MPN are required.")
    updates = {
        "description": str(description or "").strip() or None,
        "category": str(category or "").strip() or None,
        "sourcing_override": dict(sourcing_override or {}),
        "sourcing_updated_at": str(updated_at or "").strip(),
    }
    query = (
        supabase.table("analysis_parts")
        .update(updates)
        .eq("user_id", str(user_id))
        .eq("mpn", part_number)
    )
    if workspace_id:
        query = query.eq("workspace_id", str(workspace_id))
    response = query.select("id").execute()
    rows = getattr(response, "data", None) or []
    if not rows:
        raise RuntimeError("No saved component records were found to update.")
    return len(rows)


def _offer_updated_at(value: Any) -> str:
    offers = value
    if isinstance(offers, str):
        try:
            offers = json.loads(offers)
        except (TypeError, ValueError):
            offers = []
    if isinstance(offers, Mapping):
        offers = [offers]
    if not isinstance(offers, (list, tuple)):
        return ""
    timestamps = [
        str(offer.get("retrieved_at") or "").strip()
        for offer in offers
        if isinstance(offer, Mapping) and str(offer.get("retrieved_at") or "").strip()
    ]
    if not timestamps:
        return ""
    return max(timestamps)


def _part_currency(part: Mapping[str, Any]) -> str:
    explicit = _t(_first(part, "currency", "Currency", default=""))
    if explicit:
        return explicit.upper()
    offers = part.get("supplier_offers") or []
    if isinstance(offers, str):
        try:
            offers = json.loads(offers)
        except (TypeError, ValueError):
            offers = []
    if isinstance(offers, Mapping):
        offers = [offers]
    if not isinstance(offers, (list, tuple)):
        return ""
    supplier = _t(_first(part, "primary_supplier", "best_source", "supplier", default=""))
    currency_values = {
        _t(offer.get("currency")).upper()
        for offer in offers
        if isinstance(offer, Mapping)
        and _t(offer.get("currency"))
        and (not supplier or _t(offer.get("distributor")).casefold() == supplier.casefold())
    }
    if len(currency_values) == 1:
        return next(iter(currency_values))
    if not supplier:
        all_currencies = {
            _t(offer.get("currency")).upper()
            for offer in offers
            if isinstance(offer, Mapping) and _t(offer.get("currency"))
        }
        if len(all_currencies) == 1:
            return next(iter(all_currencies))
    return ""


def _updated_at(row: Mapping[str, Any]) -> str:
    return str(
        _first(
            row,
            "sourcing_updated_at",
            "updated_at",
            default=_offer_updated_at(row.get("supplier_offers"))
            or row.get("_analysis_created_at")
            or row.get("created_at")
            or "",
        )
        or ""
    ).strip()


def procurement_header_html(
    part: Mapping[str, Any],
    recommendation: Mapping[str, Any] | None = None,
) -> str:
    """Render one part's saved identity, source date, and evidence-based next step."""
    part = apply_sourcing_override(part or {})

    def first(*keys: str, default: str = "Not recorded") -> str:
        for key in keys:
            value = part.get(key)
            if value is not None and str(value).strip().casefold() not in {"", "nan", "none"}:
                return str(value).strip()
        return default

    def display_date(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return "Not recorded"
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.strftime("%b %d, %Y")
        except (TypeError, ValueError):
            return raw[:10] if len(raw) >= 10 else raw

    offers = part.get("supplier_offers") or []
    if isinstance(offers, str):
        try:
            offers = json.loads(offers)
        except (TypeError, ValueError):
            offers = []
    if isinstance(offers, Mapping):
        offers = [offers]
    offer_dates = [
        str(row.get("retrieved_at") or "").strip()
        for row in offers
        if isinstance(row, Mapping) and str(row.get("retrieved_at") or "").strip()
    ] if isinstance(offers, (list, tuple)) else []
    last_updated_raw = _updated_at(part) or (
        max(offer_dates) if offer_dates else ""
    )
    if _t(part.get("sourcing_updated_at")):
        updated_source = "Sourcing edit"
    elif _t(part.get("updated_at")):
        updated_source = "Saved record"
    elif offer_dates:
        updated_source = "Supplier lookup"
    elif _t(part.get("_analysis_created_at") or part.get("created_at")):
        updated_source = "BOM analysis"
    else:
        updated_source = ""
    mpn = html_escape(first("mpn", "MPN", "part_number", default="Part"))
    maker = html_escape(first("manufacturer", "Manufacturer"))
    description = html_escape(first("description", "Description", "part_description", "product_description"))
    normalized = _recommend(dict(part))
    lifecycle = html_escape(normalized.get("Lifecycle Status") or "Not recorded")
    category = html_escape(first("category", "Category", "component_category", "device_type", "component_type", "part_type", "architecture"))
    price = (recommendation or normalized).get("Unit Price")
    currency = _part_currency(part)
    price_label = "Not recorded" if price in (None, "") else html_escape(
        f"{price} {currency}" if currency else price
    )
    updated = html_escape(display_date(last_updated_raw))
    if updated_source and updated != "Not recorded":
        updated += f"<small>{html_escape(updated_source)}</small>"
    image_url = normalize_supplier_image_url(
        _first(part, "image_url", "Image URL", "photo_url", default="")
    )
    photo = part_image_markup(
        image_url,
        first("mpn", "MPN", "part_number", default=""),
        size=64,
        part=dict(part),
    )
    action = html_escape(str((recommendation or {}).get("Recommendation") or "Complete sourcing data"))
    next_step = html_escape(str((recommendation or {}).get("Next Step") or "Confirm the current supplier, stock, and lead time before making a purchasing decision."))
    missing = str((recommendation or {}).get("Missing Sourcing Data") or "").strip()
    evidence_note = (
        f"<p class='cv-pa-evidence-gap'><strong>Still needed:</strong> {html_escape(missing)}. "
        "Cadivor leaves missing evidence unscored; confirm it with an authorized source or enter a verified quote.</p>"
        if missing
        else "<p class='cv-pa-evidence-ok'>Based on the sourcing fields recorded for this component.</p>"
    )
    fields = (
        ("MPN", mpn),
        ("Manufacturer", maker),
        ("Description", description),
        ("Lifecycle", lifecycle),
        ("Category", category),
        ("Unit price", price_label),
        ("Last updated", updated),
    )
    cells = "".join(
        f"<div class='cv-pa-field'><span>{label}</span><strong>{value}</strong></div>"
        for label, value in fields
    )
    return (
        "<style>"
        ".cv-pa-part-head{display:flex;gap:14px;align-items:center;background:#fff;border:1px solid #e6edf5;border-radius:16px;padding:14px 16px;margin:0 0 12px}"
        ".cv-pa-meta-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:10px 16px;flex:1;min-width:0}"
        ".cv-pa-field{min-width:0}.cv-pa-field span{display:block;color:#64748b;font-size:10px;font-weight:750;letter-spacing:.045em;text-transform:uppercase;margin-bottom:4px}"
        ".cv-pa-field strong{display:block;color:#0f172a;font-size:12px;line-height:1.35;overflow-wrap:anywhere;font-weight:700}"
        ".cv-pa-field strong small{display:block;color:#64748b;font-size:10px;font-weight:500;margin-top:2px}"
        ".cv-pa-recommendation{background:#eff6ff;border:1px solid #dbeafe;border-radius:16px;padding:14px 18px;margin:0 0 14px}"
        ".cv-pa-recommendation h2{font-size:16px;margin:2px 0 5px;color:#0f172a}.cv-pa-recommendation p{margin:4px 0;color:#334155;font-size:12px;line-height:1.45}"
        ".cv-pa-evidence-gap{color:#92400e!important}.cv-pa-evidence-ok{color:#166534!important}"
        "@media(max-width:700px){.cv-pa-part-head{align-items:flex-start}.cv-pa-meta-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}"
        "</style>"
        f"<div class='cv-pa-part-head'>{photo}<div class='cv-pa-meta-grid'>{cells}</div></div>"
        f"<div class='cv-pa-recommendation'><span class='cv-ap-meta'>Recommended next step</span><h2>{action}</h2>"
        f"<p>{next_step}</p>{evidence_note}</div>"
    )


def procurement_page_header_html() -> str:
    """Render the page heading used by the sourcing recommendation workspace."""
    return (
        "<style>"
        ".cv-pa-page-head{margin:0 0 18px}.cv-pa-breadcrumb{color:#64748b;font-size:12px;font-weight:650;margin:0 0 12px}"
        ".cv-pa-breadcrumb span{padding:0 9px;color:#94a3b8}.cv-pa-page-head h1{margin:0;color:#111827;font-size:36px;line-height:1.1;letter-spacing:-.035em;font-weight:820}"
        ".cv-pa-page-head p{margin:8px 0 0;color:#64748b;font-size:15px;line-height:1.5}"
        "@media(max-width:700px){.cv-pa-page-head h1{font-size:29px}.cv-pa-page-head p{font-size:13px}}"
        "</style>"
        "<div class='cv-pa-page-head'><div class='cv-pa-breadcrumb'>Procurement Advisor"
        "<span aria-hidden='true'>›</span>Sourcing Recommendation</div>"
        "<h1>Procurement advisor</h1>"
        "<p>AI-powered supplier insights and sourcing recommendations to reduce risk, ensure supply continuity, and optimize total cost.</p></div>"
    )


def procurement_part_summary_html(
    part: Mapping[str, Any],
    recommendation: Mapping[str, Any] | None = None,
    analysis: Mapping[str, Any] | None = None,
) -> str:
    """Render the selected part facts without inferring missing commercial data."""
    part = apply_sourcing_override(part or {})
    recommendation = recommendation or _recommend(dict(part))
    analysis = analysis or {}

    def first(*keys: str, default: str = "Not recorded") -> str:
        value = _first(part, *keys)
        if value is None:
            value = _first(analysis, *keys)
        return _t(value, default) if value is not None else default

    def number_label(value: Any, suffix: str = "") -> str:
        number = _maybe_n(value)
        if number is None:
            return "Not recorded"
        text = f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}".rstrip("0").rstrip(".")
        return text + suffix

    part_number = first("mpn", "MPN", "part_number", default="Component")
    description = first("description", "Description", "part_description", "product_description")
    manufacturer = first("manufacturer", "Manufacturer")
    lifecycle = _t(recommendation.get("Lifecycle Status"), "Not recorded")
    annual_demand = number_label(
        _first(part, "annual_demand", "annual_quantity", "yearly_demand"), " units"
    )
    currency = _t(
        _first(part, "target_currency", "target_price_currency", default="")
    ).upper() or _part_currency(part)
    target_price = _maybe_n(_first(part, "target_unit_price", "target_price"))
    target_price_label = (
        f"{target_price:,.4g} {currency}".strip()
        if target_price is not None
        else "Not recorded"
    )
    required_by = first("required_by", "required_date", "need_by_date", "required_at")
    bom_label = first("bom_name", "filename", "project_name", default="Not recorded")
    revision = first("bom_revision", "revision", "rev", default="")
    bom_value = bom_label + (f" · Rev {revision}" if revision and revision != "Not recorded" else "")
    action = _t(recommendation.get("Recommendation"), "Complete sourcing data")
    lifecycle_key = lifecycle.casefold()
    lifecycle_tone = (
        "good"
        if any(token in lifecycle_key for token in ("active", "production", "preferred"))
        else "warn"
        if any(token in lifecycle_key for token in ("obsolete", "eol", "end of life", "nrnd"))
        else ""
    )
    image = part_image_markup(
        _first(part, "image_url", "Image URL", "photo_url", default=""),
        part_number,
        size=76,
        part=dict(part),
    )
    supplier_count = _maybe_n(recommendation.get("Supplier Sources"))
    if supplier_count is None:
        offers = normalize_supplier_offer_records(part)
        supplier_count = float(len({row["supplier"].casefold() for row in offers})) if offers else None
    if supplier_count is None:
        sourcing_status = "Not recorded"
    elif supplier_count <= 1:
        sourcing_status = "Single source"
    else:
        sourcing_status = f"{int(supplier_count)} sources"
    fields = (
        ("Annual demand", annual_demand),
        ("Target unit price", target_price_label),
        ("Required by", required_by),
        ("Sourcing status", sourcing_status),
    )
    cells = "".join(
        f"<div class='cv-pa-summary-fact'><span>{html_escape(label)}</span><strong>{html_escape(value)}</strong>"
        f"{'<small>Action recommended</small>' if label == 'Sourcing status' and action != 'No immediate action' else ''}</div>"
        for label, value in fields
    )
    return (
        "<style>"
        ".cv-pa-summary{display:grid;grid-template-columns:76px minmax(230px,1.6fr) repeat(4,minmax(115px,1fr));gap:16px;align-items:center;padding:18px 20px;margin:0 0 16px;background:#fff;border:1px solid #e2e8f0;border-radius:14px;box-shadow:0 3px 10px rgba(15,23,42,.035)}"
        ".cv-pa-summary-image{width:76px;height:76px;display:flex;align-items:center;justify-content:center;border-radius:10px;background:#f1f5f9;overflow:hidden}.cv-pa-summary-image img{max-width:100%;max-height:100%;object-fit:contain}"
        ".cv-pa-summary-identity{min-width:0}.cv-pa-summary-mpn{font-size:11px;color:#64748b;font-weight:750;letter-spacing:.045em;margin-bottom:4px}.cv-pa-summary-identity h2{font-size:18px;line-height:1.2;color:#0f172a;margin:0 0 4px;font-weight:780}.cv-pa-summary-identity p{font-size:12px;line-height:1.4;color:#64748b;margin:0 0 8px;overflow-wrap:anywhere}"
        ".cv-pa-chip{display:inline-flex;align-items:center;border-radius:999px;background:#eff6ff;color:#475569;padding:4px 9px;margin:0 5px 2px 0;font-size:10px;font-weight:700}.cv-pa-chip--good{background:#dcfce7;color:#15803d}.cv-pa-chip--warn{background:#fef3c7;color:#92400e}"
        ".cv-pa-summary-fact{min-height:48px;padding-left:14px;border-left:1px solid #e2e8f0;min-width:0}.cv-pa-summary-fact span{display:block;color:#64748b;font-size:10px;font-weight:700;margin-bottom:5px}.cv-pa-summary-fact strong{display:block;color:#0f172a;font-size:13px;line-height:1.3;overflow-wrap:anywhere}.cv-pa-summary-fact small{display:block;color:#64748b;font-size:10px;margin-top:3px}"
        "@media(max-width:1100px){.cv-pa-summary{grid-template-columns:70px minmax(200px,1fr) repeat(2,minmax(130px,1fr))}.cv-pa-summary-fact{padding:8px 0 0;border:0;border-top:1px solid #e2e8f0}}"
        "@media(max-width:650px){.cv-pa-summary{grid-template-columns:60px 1fr;gap:10px;padding:14px}.cv-pa-summary-image{width:60px;height:60px}.cv-pa-summary-identity h2{font-size:16px}.cv-pa-summary-fact{grid-column:span 1}.cv-pa-summary-fact:nth-last-child(2){grid-column:span 2}}"
        "</style>"
        f"<div class='cv-pa-summary'><div class='cv-pa-summary-image'>{image}</div>"
        f"<div class='cv-pa-summary-identity'><div class='cv-pa-summary-mpn'>{html_escape(part_number)} · {html_escape(manufacturer)}</div>"
        f"<h2>{html_escape(description if description != 'Not recorded' else part_number)}</h2>"
        f"<p>{html_escape(first('component_type','category','device_type','part_type'))}</p>"
        f"<span class='cv-pa-chip cv-pa-chip--{lifecycle_tone}'>{html_escape(lifecycle)}</span>"
        f"<span class='cv-pa-chip'>{html_escape(bom_value)}</span></div>{cells}</div>"
    )


def _trusted_sourcing_values(part: Mapping[str, Any]) -> dict[str, Any]:
    """Return only fields supported by a verified row or an explicit override."""
    raw_part = dict(part or {})
    override = _parse_override(raw_part.get("sourcing_override"))
    raw_verified = raw_part.get("supplier_data_verified")
    if _truthy(raw_verified) or (raw_verified is None and not override):
        normalized = _recommend(apply_sourcing_override(raw_part))
        return {
            "primary_supplier": _t(_first(raw_part, "primary_supplier", "best_source", "supplier", default="")) or None,
            "unit_price": normalized.get("Unit Price"),
            "currency": _part_currency(raw_part) or None,
            "stock_available": normalized.get("Available Stock"),
            "supplier_count": normalized.get("Supplier Sources"),
            "lead_time_weeks": normalized.get("Lead Time (Weeks)"),
            "lifecycle_status": (
                normalized.get("Lifecycle Status")
                if str(normalized.get("Lifecycle Status") or "").casefold() not in {"unknown", "not recorded"}
                else None
            ),
        }
    return {field: override.get(field) for field in SOURCING_OVERRIDE_FIELDS}


def normalize_supplier_offer_records(part: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Read saved distributor quotes and the current source as comparison rows."""
    raw_part = dict(part or {})
    trusted_values = _trusted_sourcing_values(raw_part)
    part = apply_sourcing_override(raw_part)
    offers = part.get("supplier_offers") or []
    if isinstance(offers, str):
        try:
            offers = json.loads(offers)
        except (TypeError, ValueError):
            offers = []
    if isinstance(offers, Mapping):
        offers = [offers]
    if not isinstance(offers, (list, tuple)):
        offers = []

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, float | None, str, float | None]] = set()
    for raw in offers:
        if not isinstance(raw, Mapping):
            continue
        supplier = _t(_first(raw, "distributor", "source", "supplier", default=""))
        if not supplier or supplier.casefold() in {"unknown", "not recorded", "no supplier match", "—", "-"}:
            continue
        price = _maybe_n(_first(raw, "unit_price", "price"))
        currency = _t(_first(raw, "currency", "unit_price_currency", default="")).upper()
        stock = _maybe_n(_first(raw, "stock", "stock_total", "available_stock"))
        lead = _maybe_n(_first(raw, "lead_time_weeks", "lead_time"))
        break_quantity = _maybe_n(_first(raw, "price_break_quantity", "quantity"))
        key = (supplier.casefold(), price, currency, break_quantity)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "supplier": supplier,
            "unit_price": price,
            "currency": currency,
            "stock": int(stock) if stock is not None and stock.is_integer() else stock,
            "lead_time_weeks": lead,
            "price_break_quantity": break_quantity,
            "region": _t(_first(raw, "region", "ship_from", "country", default="")),
            "supply_risk": _t(_first(raw, "supply_risk", "risk_level", default="")),
            "product_url": _t(_first(raw, "product_url", "product_detail_url", "source_url", default="")),
            "retrieved_at": _t(_first(raw, "retrieved_at", "updated_at", default="")),
            "is_current": False,
        })

    current_supplier = _t(trusted_values.get("primary_supplier"))
    if current_supplier.casefold() in {"unknown", "not recorded", "no supplier match", "—", "-"}:
        current_supplier = ""
    current_price = _maybe_n(trusted_values.get("unit_price"))
    current_currency = _t(trusted_values.get("currency")).upper()
    current_stock = _maybe_n(trusted_values.get("stock_available"))
    current_lead = _maybe_n(trusted_values.get("lead_time_weeks"))
    if current_supplier:
        match = next((row for row in rows if row["supplier"].casefold() == current_supplier.casefold()), None)
        if match is None:
            rows.append({
                "supplier": current_supplier,
                "unit_price": current_price,
                "currency": current_currency,
                "stock": int(current_stock) if current_stock is not None and current_stock.is_integer() else current_stock,
                "lead_time_weeks": current_lead,
                "price_break_quantity": None,
                "region": "",
                "supply_risk": "",
                "product_url": _t(_first(part, "product_url", "source_url", default="")),
                "retrieved_at": _updated_at(part),
                "is_current": True,
            })
        else:
            match["is_current"] = True
            if match.get("unit_price") is None:
                match["unit_price"] = current_price
            if not match.get("currency"):
                match["currency"] = current_currency
            if match.get("stock") is None:
                match["stock"] = int(current_stock) if current_stock is not None and current_stock.is_integer() else current_stock
            if match.get("lead_time_weeks") is None:
                match["lead_time_weeks"] = current_lead
    return rows


def supplier_comparison_dataframe(
    part: Mapping[str, Any], *, selected_supplier: str = "", view: str = "Key comparison"
) -> pd.DataFrame:
    """Create a string-only quote table so mixed supplier values never reach Arrow."""
    offers = normalize_supplier_offer_records(part)
    trusted_values = _trusted_sourcing_values(part or {})
    currency = _t(trusted_values.get("currency")).upper()
    current_price = _maybe_n(trusted_values.get("unit_price"))
    prices = [
        row["unit_price"] for row in offers
        if row.get("unit_price") is not None and currency and row.get("currency") == currency
    ]
    best_price = min(prices) if prices else None
    columns = ["Selected", "Supplier", "Unit price", "Price vs current", "Available stock", "Lead time", "Region", "Supply risk", "Unit price index"]
    if view == "All evidence":
        columns.extend(["Price break", "Retrieved", "Product page"])
    display_rows = []
    for row in offers:
        price = row.get("unit_price")
        row_currency = row.get("currency")
        same_currency = bool(currency and row_currency == currency)
        if price is not None and row_currency:
            price_label = f"{price:,.4g} {row_currency}"
        else:
            price_label = "Not recorded"
        delta = "—"
        if price is not None and current_price is not None and same_currency and current_price > 0:
            pct = (price / current_price - 1) * 100
            delta = f"{pct:+.1f}%" if abs(pct) >= .05 else "Current price"
        stock = row.get("stock")
        lead = row.get("lead_time_weeks")
        price_break = row.get("price_break_quantity")
        index = "—"
        if best_price and price and same_currency:
            # A unit-price index is explicitly normalized to the cheapest quote.
            index = f"{round(best_price / price * 100):d}"
        item = {
            "Selected": "● Selected" if row["supplier"].casefold() == str(selected_supplier).casefold() else "○ Select row",
            "Supplier": row["supplier"] + (" · Current source" if row.get("is_current") else " · Offer recorded"),
            "Unit price": price_label,
            "Price vs current": delta,
            "Available stock": f"{stock:,}" if isinstance(stock, (int, float)) else "Not recorded",
            "Lead time": f"{lead:g} weeks" if lead is not None else "Not recorded",
            "Region": row.get("region") or "Not recorded",
            "Supply risk": row.get("supply_risk") or "Not recorded",
            "Unit price index": index,
            "Price break": f"{price_break:,.0f} units" if price_break is not None else "Not recorded",
            "Retrieved": (row.get("retrieved_at") or "Not recorded")[:10],
            "Product page": "Saved link" if row.get("product_url", "").startswith(("https://", "http://")) else "Not recorded",
        }
        # Retain row identity in the frame; it is hidden in the UI and supports stable selection.
        item["_supplier_key"] = row["supplier"]
        display_rows.append(item)
    return pd.DataFrame(display_rows, columns=columns + ["_supplier_key"])


def supplier_offer_override(part: Mapping[str, Any], supplier: str) -> dict[str, Any]:
    """Merge the selected recorded quote into a sourcing override without clearing unknowns."""
    part = dict(part or {})
    existing = _parse_override(part.get("sourcing_override"))
    selected = next(
        (row for row in normalize_supplier_offer_records(part) if row["supplier"].casefold() == str(supplier or "").casefold()),
        None,
    )
    if selected is None:
        raise ValueError("Choose a saved supplier offer before applying it.")

    # A partial manual override must not make unrelated legacy defaults appear
    # verified simply because one quote is being applied.
    values = _trusted_sourcing_values(part)
    current_supplier = _t(values.get("primary_supplier"))
    if current_supplier.casefold() != selected["supplier"].casefold():
        # Price, stock, and lead time belong to the selected source. Do not
        # carry another supplier's numbers across when the quote omits them.
        for field in ("unit_price", "currency", "stock_available", "lead_time_weeks"):
            values[field] = None
    existing = values
    updates = {"primary_supplier": selected["supplier"]}
    if selected.get("unit_price") is not None and selected.get("currency"):
        updates.update(unit_price=selected["unit_price"], currency=selected["currency"])
    if selected.get("stock") is not None:
        updates["stock_available"] = selected["stock"]
    if selected.get("lead_time_weeks") is not None:
        updates["lead_time_weeks"] = selected["lead_time_weeks"]
    existing.update(updates)
    return existing


def procurement_recommendation_html(
    part: Mapping[str, Any],
    recommendation: Mapping[str, Any] | None,
    price_comparison: Mapping[str, Any] | None = None,
) -> str:
    """Render a recommendation and three evidence callouts from recorded values."""
    part = apply_sourcing_override(part or {})
    recommendation = recommendation or _recommend(dict(part))
    price_comparison = price_comparison or {}
    offers = normalize_supplier_offer_records(part)
    supplier_count = _maybe_n(recommendation.get("Supplier Sources"))
    if supplier_count is not None:
        coverage_value = f"{int(supplier_count)} recorded source{'s' if supplier_count != 1 else ''}"
        coverage_detail = "Supplier count in the saved sourcing record"
    elif offers:
        coverage_value = f"{len({row['supplier'].casefold() for row in offers})} offer source{'s' if len(offers) != 1 else ''}"
        coverage_detail = "Recorded offers; qualification is not recorded"
    else:
        coverage_value = "Not recorded"
        coverage_detail = "Add verified supplier coverage"

    savings = price_comparison.get("savings_per_unit")
    if savings is not None:
        price_value = f"{savings:,.4g} {price_comparison.get('currency') or ''} / unit".strip()
        price_detail = f"Lower quote from {price_comparison.get('lower_distributor') or 'saved offers'}"
    else:
        price_value = "No comparable quotes"
        price_detail = "Same currency and applicable price breaks are required"

    lead = _maybe_n(recommendation.get("Lead Time (Weeks)"))
    lead_value = f"{lead:g} weeks" if lead is not None else "Not recorded"
    lead_detail = "Current sourcing record" if lead is not None else "Confirm with an authorized supplier"
    callouts = (
        ("Supply coverage", coverage_value, coverage_detail, "◈"),
        ("Price comparison", price_value, price_detail, "▥"),
        ("Lead time", lead_value, lead_detail, "◷"),
    )
    action = _t(recommendation.get("Recommendation"), "Complete sourcing data")
    action_title = {
        "Add a second source": "Add a second source to improve supply coverage",
        "Qualify a replacement": "Qualify a replacement for lifecycle continuity",
        "Resolve supply gap": "Resolve the verified supply gap",
        "Buy now": "Secure the units needed for the next build",
        "Order earlier": "Move procurement ahead of the long lead time",
        "Monitor closely": "Monitor supply before the next build",
        "Complete sourcing data": "Complete current sourcing evidence",
        "No immediate action": "Continue routine supplier monitoring",
    }.get(action, action)
    next_step = _t(recommendation.get("Next Step"), "Confirm current sourcing evidence before ordering.")
    return (
        "<style>"
        ".cv-pa-recommendation-v2{display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,.45fr);gap:26px;align-items:center;padding:25px 28px;margin:0 0 16px;border:1px solid #dbeafe;border-radius:14px;background:linear-gradient(115deg,#eff6ff 0%,#f8fbff 100%)}"
        ".cv-pa-reco-main{display:grid;grid-template-columns:56px minmax(0,1fr);gap:18px;align-items:start}.cv-pa-reco-star{width:56px;height:56px;display:flex;align-items:center;justify-content:center;border-radius:50%;background:#dbeafe;color:#2563eb;font-size:27px}.cv-pa-reco-eyebrow{font-size:10px;color:#2563eb;letter-spacing:.11em;font-weight:850;margin:0 0 7px}.cv-pa-reco-main h2{font-size:22px;line-height:1.2;letter-spacing:-.02em;margin:0 0 9px;color:#102341;font-weight:800}.cv-pa-reco-main p{font-size:13px;line-height:1.6;color:#475569;margin:0;max-width:820px}"
        ".cv-pa-reco-callouts{display:grid;gap:12px;padding-left:22px;border-left:1px solid #cfe0f7}.cv-pa-reco-callout{display:grid;grid-template-columns:30px 1fr;gap:10px;align-items:start}.cv-pa-reco-icon{color:#2563eb;font-size:20px;line-height:1.2}.cv-pa-reco-callout strong{display:block;color:#172b4d;font-size:12px;font-weight:780}.cv-pa-reco-callout small{display:block;color:#64748b;font-size:10px;line-height:1.4;margin-top:2px}"
        "@media(max-width:850px){.cv-pa-recommendation-v2{grid-template-columns:1fr}.cv-pa-reco-callouts{grid-template-columns:repeat(3,minmax(0,1fr));padding:16px 0 0;border-left:0;border-top:1px solid #cfe0f7}}"
        "@media(max-width:600px){.cv-pa-recommendation-v2{padding:18px}.cv-pa-reco-main{grid-template-columns:42px 1fr;gap:12px}.cv-pa-reco-star{width:42px;height:42px;font-size:21px}.cv-pa-reco-main h2{font-size:18px}.cv-pa-reco-callouts{grid-template-columns:1fr}}"
        "</style>"
        "<div class='cv-pa-recommendation-v2'><div class='cv-pa-reco-main'>"
        "<div class='cv-pa-reco-star' aria-hidden='true'>★</div><div>"
        f"<div class='cv-pa-reco-eyebrow'>RECOMMENDATION</div><h2>{html_escape(action_title)}</h2>"
        f"<p>{html_escape(next_step)}</p></div></div><div class='cv-pa-reco-callouts'>"
        + "".join(
            f"<div class='cv-pa-reco-callout'><span class='cv-pa-reco-icon' aria-hidden='true'>{icon}</span>"
            f"<div><strong>{html_escape(value)}</strong><small>{html_escape(detail)}</small></div></div>"
            for _label, value, detail, icon in callouts
        )
        + "</div></div>"
    )


def procurement_summary_cards_html(
    part: Mapping[str, Any],
    recommendation: Mapping[str, Any] | None,
    price_comparison: Mapping[str, Any] | None = None,
) -> str:
    """Render four mockup-style cards, showing unavailable evidence as unknown."""
    part = apply_sourcing_override(part or {})
    recommendation = recommendation or _recommend(dict(part))
    price_comparison = price_comparison or {}
    offers = normalize_supplier_offer_records(part)
    supplier_count = _maybe_n(recommendation.get("Supplier Sources"))
    if supplier_count is None and offers:
        quote_count = len({row["supplier"].casefold() for row in offers})
        coverage_value = f"{quote_count} quote source{'s' if quote_count != 1 else ''}"
        coverage_detail = "Saved offers; qualification is not recorded"
    elif supplier_count is None:
        coverage_value, coverage_detail = "Not recorded", "Confirm authorized supplier coverage"
    elif supplier_count <= 1:
        coverage_value, coverage_detail = f"{int(supplier_count)} → 2", "If a second source is qualified"
    else:
        coverage_value, coverage_detail = f"{int(supplier_count)} sources", "Recorded in current sourcing data"

    annual_demand = _maybe_n(_first(part, "annual_demand", "annual_quantity", "yearly_demand"))
    annual_comparison = {}
    if annual_demand is not None:
        from src.saved_bom_cost import distributor_comparison

        annual_comparison = distributor_comparison(
            part.get("supplier_offers"),
            mpn=_t(_first(part, "mpn", "MPN", "part_number", default="")),
            bom_quantity=annual_demand,
        )
    savings = annual_comparison.get("savings_per_unit")
    if annual_demand is not None and savings is not None:
        annual_savings_value = f"{savings * annual_demand:,.2f} {annual_comparison.get('currency') or ''}".strip()
        annual_savings_detail = f"At {annual_demand:,.0f} units/year; quote is indicative"
    else:
        annual_savings_value = "Not recorded"
        annual_savings_detail = "Annual demand and applicable comparable quotes are required"

    risk = _t(_first(part, "blended_supply_risk", "supply_risk", default=""))
    risk_value = risk if risk else "Not assessed"
    risk_detail = "Recorded supply-risk assessment" if risk else "No blended supplier-risk evidence"
    action = _t(recommendation.get("Recommendation"), "Complete sourcing data")
    cards = (
        ("Sourcing coverage", coverage_value, coverage_detail, "coverage"),
        ("Estimated annual savings", annual_savings_value, annual_savings_detail, "cost"),
        ("Supply risk (blended)", risk_value, risk_detail, "risk"),
        ("Recommendation", action, _t(recommendation.get("Next Step"), "Review saved sourcing data"), "action"),
    )
    return (
        "<style>"
        ".cv-pa-metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 16px}.cv-pa-metric{min-height:105px;padding:16px 18px;border:1px solid #e2e8f0;border-radius:12px;background:#fff;box-shadow:0 2px 8px rgba(15,23,42,.025)}.cv-pa-metric--action{background:#f0fdf4;border-color:#d1fae5}.cv-pa-metric-label{font-size:11px;color:#64748b;font-weight:700;margin:0 0 9px}.cv-pa-metric-value{font-size:20px;color:#0f172a;font-weight:800;line-height:1.2;overflow-wrap:anywhere}.cv-pa-metric--action .cv-pa-metric-value{font-size:16px;color:#166534}.cv-pa-metric-detail{font-size:10px;color:#64748b;line-height:1.4;margin-top:7px}"
        "@media(max-width:900px){.cv-pa-metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:520px){.cv-pa-metric-grid{grid-template-columns:1fr}.cv-pa-metric{min-height:0}}"
        "</style><div class='cv-pa-metric-grid'>"
        + "".join(
            f"<div class='cv-pa-metric cv-pa-metric--{tone}'><div class='cv-pa-metric-label'>{html_escape(label)}</div>"
            f"<div class='cv-pa-metric-value'>{html_escape(value)}</div><div class='cv-pa-metric-detail'>{html_escape(detail)}</div></div>"
            for label, value, detail, tone in cards
        )
        + "</div>"
    )


def procurement_workspace_panels_html(
    part: Mapping[str, Any],
    recommendation: Mapping[str, Any] | None,
    analysis: Mapping[str, Any] | None = None,
    price_comparison: Mapping[str, Any] | None = None,
) -> str:
    """Return the mockup's selected-part, recommendation, and KPI panels together.

    Keeping these related blocks in one Streamlit HTML host prevents a page
    rerun from leaving the selector and supplier table mounted while dropping
    the intervening custom-markup elements.
    """
    import re

    fragments = (
        procurement_part_summary_html(part, recommendation, analysis),
        procurement_recommendation_html(part, recommendation, price_comparison),
        procurement_summary_cards_html(part, recommendation, price_comparison),
    )
    styles: list[str] = []
    body: list[str] = []
    style_pattern = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.IGNORECASE | re.DOTALL)
    for fragment in fragments:
        styles.extend(style_pattern.findall(fragment))
        body.append(style_pattern.sub("", fragment))
    return "<style>" + "\n".join(styles) + "</style>" + "".join(body)


def procurement_details_display_frame(recommendation_df: pd.DataFrame) -> pd.DataFrame:
    """Prepare the all-components table without mixing text into numeric Arrow columns."""
    frame = recommendation_df.copy()
    integer_columns = ("Available Stock", "Required Quantity", "Supplier Sources", "Priority Score")
    decimal_columns = ("Unit Price", "Lead Time (Weeks)")
    for column in integer_columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    for column in decimal_columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Float64")
    numeric = set(integer_columns + decimal_columns)
    for column in frame.columns:
        if column in numeric:
            continue
        values = frame[column].astype("object")
        frame[column] = values.where(pd.notna(values), "Not recorded").astype("string")
    return frame


def html_escape(value: Any) -> str:
    import html

    return html.escape(str(value or ""))


def sourcing_editor_values(part: Mapping[str, Any]) -> Dict[str, Any]:
    """Return only evidence Cadivor currently considers recorded for the editor."""
    row = apply_sourcing_override(part or {})
    normalized = _recommend(row)
    manual_fields = set(row.get("_sourcing_override_fields") or ())
    supplier_known = (
        "primary_supplier" in manual_fields
        or row.get("supplier_data_verified") is not False
    )
    supplier = _t(_first(row, "primary_supplier", "best_source", "supplier", default=""))
    return {
        "description": _t(_first(row, "description", "Description", "part_description", "product_description")),
        "category": _t(_first(row, "category", "Category", "component_category", "device_type", "component_type", "part_type", "architecture")),
        "primary_supplier": supplier if supplier_known else "",
        "unit_price": normalized.get("Unit Price"),
        "currency": _part_currency(row),
        "stock_available": normalized.get("Available Stock"),
        "supplier_count": normalized.get("Supplier Sources"),
        "lead_time_weeks": normalized.get("Lead Time (Weeks)"),
        "lifecycle_status": "" if str(normalized.get("Lifecycle Status") or "").casefold() in {"unknown", "not recorded"} else normalized.get("Lifecycle Status"),
    }

def _first(row, *keys, default=None):
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip().casefold() not in {"", "nan", "none", "null"}:
            return value
    return default

def _recommend(row: Dict[str, Any]) -> Dict[str, Any]:
    row = apply_sourcing_override(row)
    part = _t(_first(row, "mpn", "MPN", "part_number", default="Component"), "Component")
    manufacturer = _t(_first(row, "manufacturer", "Manufacturer", default="Unknown"), "Unknown")
    raw_stock = _maybe_n(_first(row, "stock_available", "stock"))
    qty_value = _maybe_n(_first(row, "quantity", "qty"))
    qty = int(qty_value) if qty_value is not None and qty_value > 0 else None
    raw_suppliers = _maybe_n(_first(row, "supplier_count"))
    raw_lead = _maybe_n(_first(row, "lead_time_weeks", "lead_time"))
    lifecycle = _t(_first(row, "lifecycle_status", default="Unknown"), "Unknown")
    risk_value = _maybe_n(_first(row, "risk_score"))
    risk = int(risk_value or 0)
    supplier_name = _t(_first(row, "primary_supplier", "best_source", "supplier", default=""))
    manual_fields = set(row.get("_sourcing_override_fields") or ())
    has_verification_flag = row.get("supplier_data_verified") is not None
    verified = _truthy(row.get("supplier_data_verified"))
    if has_verification_flag and not verified and "lifecycle_status" not in manual_fields:
        lifecycle = "Unknown"
    offers = row.get("supplier_offers") or []
    offer_stock_recorded = False
    if isinstance(offers, str):
        try:
            offers = json.loads(offers)
        except (TypeError, ValueError):
            offers = []
    if isinstance(offers, Mapping):
        offers = [offers]
    if isinstance(offers, (list, tuple)):
        offer_stock_recorded = any(
            isinstance(offer, Mapping) and _maybe_n(offer.get("stock")) is not None
            for offer in offers
        )
    if "stock_available" in manual_fields or (has_verification_flag and verified):
        stock = raw_stock
    elif has_verification_flag:
        stock = None
    elif raw_stock is not None and raw_stock > 0:
        stock = raw_stock
    elif raw_stock == 0 and (raw_suppliers is not None and raw_suppliers > 0 or supplier_name or offer_stock_recorded):
        stock = raw_stock
    else:
        stock = None
    if "supplier_count" in manual_fields or (has_verification_flag and verified):
        suppliers_value = raw_suppliers
    elif has_verification_flag:
        suppliers_value = None
    else:
        suppliers_value = raw_suppliers if raw_suppliers is not None and raw_suppliers > 0 else None
    if "lead_time_weeks" in manual_fields or (has_verification_flag and verified):
        lead = raw_lead
    elif has_verification_flag:
        lead = None
    else:
        lead = raw_lead if raw_lead is not None and raw_lead > 0 else None
    price_value = _maybe_n(_first(row, "unit_price", "Unit Price", "price"))
    if "unit_price" not in manual_fields and has_verification_flag and not verified:
        price_value = None
    if price_value is not None and price_value <= 0:
        price_value = None
    if stock is not None and stock < 0:
        stock = None
    if suppliers_value is not None and suppliers_value < 0:
        suppliers_value = None
    if lead is not None and lead < 0:
        lead = None
    suppliers = int(suppliers_value) if suppliers_value is not None else None
    if qty is None:
        qty = None
    lower = lifecycle.lower()

    score = risk
    if stock is not None:
        score += 40 if stock <= 0 else 30 if qty is not None and stock < qty else 18 if qty is not None and stock < max(100, qty * 3) else 0
    if suppliers is not None:
        score += 20 if suppliers <= 1 else 8 if suppliers == 2 else 0
    if lead is not None:
        score += 18 if lead >= 16 else 9 if lead >= 10 else 0
    score += 35 if any(x in lower for x in ("obsolete", "eol", "end of life")) else 20 if any(x in lower for x in ("replacement", "nrnd", "not recommended")) else 0
    score = min(100, score)

    if any(x in lower for x in ("obsolete", "eol", "end of life")):
        recommendation = "Qualify a replacement"
        next_step = "Avoid a long-term purchase and secure only bridge inventory."
    elif stock is not None and stock <= 0:
        recommendation = "Resolve supply gap"
        next_step = "Find authorized stock or approve a substitute before the next build."
    elif stock is not None and qty is not None and stock < qty:
        recommendation = "Buy now"
        next_step = f"Secure at least {qty:,} units for the next scheduled build."
    elif suppliers is not None and suppliers <= 1:
        recommendation = "Add a second source"
        next_step = "Approve another authorized supplier or compatible alternate."
    elif lead is not None and lead >= 16:
        recommendation = "Order earlier"
        next_step = "Move the purchase date forward or establish safety stock."
    elif stock is not None and qty is not None and stock < max(100, qty * 3):
        recommendation = "Monitor closely"
        next_step = "Review stock weekly and prepare a sourcing fallback."
    elif stock is None or suppliers is None or lead is None:
        recommendation = "Complete sourcing data"
        next_step = "Confirm current stock, authorized supplier coverage, and lead time before making a buy decision."
    else:
        recommendation = "No immediate action"
        next_step = "Continue routine stock, price, and lifecycle monitoring."

    missing = []
    if stock is None:
        missing.append("available stock")
    if suppliers is None:
        missing.append("supplier coverage")
    if lead is None:
        missing.append("lead time")
    if price_value is None:
        missing.append("unit price")
    evidence_known = 4 - len(missing)
    evidence_status = "Complete" if not missing else ("Partial" if evidence_known else "Incomplete")

    return {
        "Part Number": part,
        "Image URL": normalize_supplier_image_url(
            _first(row, "image_url", "Image URL", "photo_url")
        ),
        "Manufacturer": manufacturer,
        "Recommendation": recommendation,
        "Next Step": next_step,
        "Priority Score": score,
        "Available Stock": int(stock) if stock is not None else None,
        "Required Quantity": qty,
        "Supplier Sources": suppliers,
        "Unit Price": price_value,
        "Currency": _part_currency(row),
        "Lead Time (Weeks)": lead,
        "Lifecycle Status": lifecycle,
        "Evidence Status": evidence_status,
        "Missing Sourcing Data": ", ".join(missing),
        "description": _t(_first(row, "description", "Description", "part_description", "product_description", default="")),
        "category": _t(_first(row, "category", "Category", "component_category", "device_type", "component_type", "part_type", "architecture", default="")),
        "Last Updated": _updated_at(row),
    }

def build_procurement_advisor(*, analyses: Iterable[Dict[str, Any]], parts: Iterable[Dict[str, Any]], alerts=None):
    rows = [_recommend(row) for row in list(parts or []) if isinstance(row, dict)]
    # Consolidate duplicate MPNs so purchasing sees one decision per component.
    consolidated = {}
    for row in rows:
        key = row["Part Number"].upper()
        existing = consolidated.get(key)
        if existing is None or row["Priority Score"] > existing["Priority Score"]:
            consolidated[key] = row
        else:
            existing["Required Quantity"] = sum(
                value for value in (existing.get("Required Quantity"), row.get("Required Quantity"))
                if isinstance(value, (int, float))
            ) or None
    rows = sorted(consolidated.values(), key=lambda x: -x["Priority Score"])
    df = pd.DataFrame(rows)
    urgent = [
        r for r in rows
        if r["Priority Score"] >= 75 and r["Recommendation"] != "Complete sourcing data"
    ]
    monitor = [r for r in rows if r["Recommendation"] == "Monitor closely"]
    second_source = [r for r in rows if r["Recommendation"] == "Add a second source"]
    replace = [r for r in rows if r["Recommendation"] == "Qualify a replacement"]
    return {
        "recommendations": rows,
        "recommendation_df": df,
        "urgent_count": len(urgent),
        "monitor_count": len(monitor),
        "second_source_count": len(second_source),
        "replace_count": len(replace),
        "summary": (
            f"{len(urgent)} component(s) have evidence-backed purchasing actions, "
            f"{len(second_source)} need another source, and {len(monitor)} should be monitored."
            + (
                f" {sum(1 for r in rows if r['Recommendation'] == 'Complete sourcing data')} need current sourcing data before Cadivor can prioritize a purchase."
                if any(r["Recommendation"] == "Complete sourcing data" for r in rows)
                else ""
            )
            if rows else "No purchasing intelligence is available yet."
        ),
    }

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
        f"<section class='cv-pa-part-head'>{photo}<div class='cv-pa-meta-grid'>{cells}</div></section>"
        f"<section class='cv-pa-recommendation'><span class='cv-ap-meta'>Recommended next step</span><h2>{action}</h2>"
        f"<p>{next_step}</p>{evidence_note}</section>"
    )


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

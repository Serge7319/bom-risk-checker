"""Compact procurement intelligence used by Cadivor's overview and Procurement Advisor."""
from __future__ import annotations
from typing import Any, Dict, Iterable
import pandas as pd

def _t(v, default=""):
    if v is None:
        return default
    v = str(v).strip()
    return v or default

def _n(v, default=0.0):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return default
        return float(v)
    except Exception:
        return default

def _first(row, *keys, default=None):
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return default

def _recommend(row: Dict[str, Any]) -> Dict[str, Any]:
    part = _t(_first(row, "mpn", "MPN", "part_number", default="Component"), "Component")
    manufacturer = _t(_first(row, "manufacturer", "Manufacturer", default="Unknown"), "Unknown")
    stock = _n(_first(row, "stock_available", "stock", default=0))
    qty = max(1, int(_n(_first(row, "quantity", "qty", default=1), 1)))
    suppliers = int(_n(_first(row, "supplier_count", default=0)))
    lead = _n(_first(row, "lead_time_weeks", "lead_time", default=0))
    lifecycle = _t(_first(row, "lifecycle_status", default="Unknown"), "Unknown")
    risk = int(_n(_first(row, "risk_score", default=0)))
    lower = lifecycle.lower()

    score = risk
    score += 40 if stock <= 0 else 30 if stock < qty else 18 if stock < max(100, qty * 3) else 0
    score += 20 if suppliers <= 1 else 8 if suppliers == 2 else 0
    score += 18 if lead >= 16 else 9 if lead >= 10 else 0
    score += 35 if any(x in lower for x in ("obsolete", "eol", "end of life")) else 20 if any(x in lower for x in ("replacement", "nrnd", "not recommended")) else 0
    score = min(100, score)

    if any(x in lower for x in ("obsolete", "eol", "end of life")):
        recommendation = "Qualify a replacement"
        next_step = "Avoid a long-term purchase and secure only bridge inventory."
    elif stock <= 0:
        recommendation = "Resolve supply gap"
        next_step = "Find authorized stock or approve a substitute before the next build."
    elif stock < qty:
        recommendation = "Buy now"
        next_step = f"Secure at least {qty:,} units for the next scheduled build."
    elif suppliers <= 1:
        recommendation = "Add a second source"
        next_step = "Approve another authorized supplier or compatible alternate."
    elif lead >= 16:
        recommendation = "Order earlier"
        next_step = "Move the purchase date forward or establish safety stock."
    elif stock < max(100, qty * 3):
        recommendation = "Monitor closely"
        next_step = "Review stock weekly and prepare a sourcing fallback."
    else:
        recommendation = "No immediate action"
        next_step = "Continue routine stock, price, and lifecycle monitoring."

    return {
        "Part Number": part,
        "Manufacturer": manufacturer,
        "Recommendation": recommendation,
        "Next Step": next_step,
        "Priority Score": score,
        "Available Stock": int(stock),
        "Required Quantity": qty,
        "Supplier Sources": suppliers,
        "Lead Time (Weeks)": lead,
        "Lifecycle Status": lifecycle,
    }

def build_procurement_advisor(*, analyses: Iterable[Dict[str, Any]], parts: Iterable[Dict[str, Any]], alerts=None):
    rows = [_recommend(row) for row in list(parts or [])]
    # Consolidate duplicate MPNs so purchasing sees one decision per component.
    consolidated = {}
    for row in rows:
        key = row["Part Number"].upper()
        existing = consolidated.get(key)
        if existing is None or row["Priority Score"] > existing["Priority Score"]:
            consolidated[key] = row
        else:
            existing["Required Quantity"] += row["Required Quantity"]
    rows = sorted(consolidated.values(), key=lambda x: -x["Priority Score"])
    df = pd.DataFrame(rows)
    urgent = [r for r in rows if r["Priority Score"] >= 75]
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
            f"{len(urgent)} component(s) require immediate purchasing attention, "
            f"{len(second_source)} need another source, and {len(monitor)} should be monitored."
            if rows else "No purchasing intelligence is available yet."
        ),
    }

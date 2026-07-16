"""Cadivor Milestone 14.0 — AI Procurement Advisor."""
from __future__ import annotations
from typing import Any, Dict, Iterable
import pandas as pd

def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    value = str(value).strip()
    return value or default

def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except Exception:
        return default

def _first(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return default

def _buy_recommendation(row: Dict[str, Any]) -> Dict[str, Any]:
    mpn = _text(_first(row, "mpn", "MPN", "part_number", "Manufacturer Part Number", default="Component"), "Component")
    manufacturer = _text(_first(row, "manufacturer", "Manufacturer", default="Unknown"), "Unknown")
    stock = _number(_first(row, "stock_available", "Stock Available", "Available Stock", "stock", default=0), 0)
    suppliers = int(_number(_first(row, "supplier_count", "Supplier Count", "Supplier Sources", default=0), 0))
    lead = _number(_first(row, "lead_time_weeks", "Lead Time Weeks", "Lead Time (Weeks)", "lead_time", default=0), 0)
    unit_price = _number(_first(row, "unit_price", "Unit Price", "price", default=0), 0)
    quantity = max(1, int(_number(_first(row, "quantity", "Quantity", "qty", default=1), 1)))
    lifecycle = _text(_first(row, "lifecycle_status", "Lifecycle Status", default="Unknown"), "Unknown")
    risk = _text(_first(row, "risk_level", "Risk Level", default="Low"), "Low")
    risk_score = int(_number(_first(row, "risk_score", "Risk Score", default=0), 0))

    lifecycle_lower = lifecycle.lower()
    score = risk_score
    score += 40 if stock <= 0 else 32 if stock < quantity else 22 if stock < quantity * 3 else 14 if stock < 100 else 0
    score += 22 if suppliers <= 1 else 10 if suppliers == 2 else 0
    score += 22 if lead >= 20 else 12 if lead >= 12 else 0
    score += 35 if any(t in lifecycle_lower for t in ("obsolete", "eol", "end of life")) else 22 if any(t in lifecycle_lower for t in ("replacement", "nrnd", "not recommended")) else 0
    score = min(100, score)

    if any(t in lifecycle_lower for t in ("obsolete", "eol", "end of life")):
        recommendation, action, urgency, category, owner = (
            "Do not place a long-term purchase",
            "Qualify an approved replacement and secure only bridge inventory.",
            "Immediate engineering action",
            "Replace",
            "Engineering + Procurement",
        )
    elif stock <= 0:
        recommendation, action, urgency, category, owner = (
            "Find alternative or alternate source",
            "Confirm authorized stock or an approved substitute before the next build.",
            "Today",
            "Supply Gap",
            "Procurement",
        )
    elif stock < quantity:
        recommendation, action, urgency, category, owner = (
            "Buy now",
            f"Secure at least {quantity:,} units or enough coverage for the next scheduled build.",
            "Within 24 hours",
            "Critical Buy",
            "Procurement",
        )
    elif suppliers <= 1:
        recommendation, action, urgency, category, owner = (
            "Qualify a second source",
            "Approve another authorized supplier or compatible alternate.",
            "This week",
            "Single Source",
            "Procurement + Component Engineering",
        )
    elif lead >= 16:
        recommendation, action, urgency, category, owner = (
            "Advance the purchase order",
            "Align the order date with production and evaluate safety stock.",
            "Before the current planning window closes",
            "Long Lead",
            "Supply Chain",
        )
    elif stock < max(100, quantity * 3):
        recommendation, action, urgency, category, owner = (
            "Monitor closely",
            "Review inventory weekly and prepare a sourcing fallback.",
            "This week",
            "Low Stock",
            "Supply Chain",
        )
    else:
        recommendation, action, urgency, category, owner = (
            "No immediate purchase required",
            "Continue routine price, stock, and lifecycle monitoring.",
            "Review in 30 days",
            "Healthy",
            "Procurement",
        )

    return {
        "Part Number": mpn,
        "Manufacturer": manufacturer,
        "Recommendation": recommendation,
        "Category": category,
        "Urgency": urgency,
        "Owner": owner,
        "Recommended Action": action,
        "Priority Score": score,
        "Confidence": min(96, 62 + (8 if stock >= 0 else 0) + (8 if suppliers > 0 else 0) + (8 if lead > 0 else 0) + (8 if lifecycle.lower() != "unknown" else 0)),
        "Available Stock": int(stock),
        "Required Quantity": quantity,
        "Supplier Sources": suppliers,
        "Lead Time (Weeks)": lead,
        "Lifecycle Status": lifecycle,
        "Risk Level": risk,
        "Unit Price": round(unit_price, 4),
        "Estimated Order Value": round(unit_price * quantity, 2),
        "Estimated Shortage Exposure": round(max(0, quantity - stock) * unit_price, 2),
    }

def build_procurement_advisor(*, analyses: Iterable[Dict[str, Any]], parts: Iterable[Dict[str, Any]], alerts=None) -> Dict[str, Any]:
    recommendations = [_buy_recommendation(row) for row in list(parts or [])]
    recommendations.sort(key=lambda item: (item["Recommendation"] == "No immediate purchase required", -int(item["Priority Score"])))
    df = pd.DataFrame(recommendations)

    if df.empty:
        buy_now = monitor = replace = second_source = 0
        order_value = shortage_exposure = 0.0
    else:
        buy_now = int(df["Recommendation"].astype(str).str.contains("Buy now|Advance the purchase order", regex=True).sum())
        monitor = int(df["Recommendation"].eq("Monitor closely").sum())
        replace = int(df["Recommendation"].astype(str).str.contains("alternative|replacement", case=False, regex=True).sum())
        second_source = int(df["Recommendation"].astype(str).str.contains("second source", case=False, regex=False).sum())
        order_value = float(df.loc[df["Recommendation"].astype(str).str.contains("Buy now|Advance the purchase order", regex=True), "Estimated Order Value"].sum())
        shortage_exposure = float(df["Estimated Shortage Exposure"].sum())

    high_priority = 0 if df.empty else int((df["Priority Score"] >= 75).sum())
    if high_priority:
        posture, tone = "Immediate Procurement Action Required", "bad"
        summary = f"{high_priority} component purchasing decision(s) require immediate attention."
    elif buy_now or second_source or monitor:
        posture, tone = "Focused Purchasing Review", "warn"
        summary = f"{buy_now} buy-now, {second_source} second-source, and {monitor} monitoring action(s) are open."
    else:
        posture, tone = "Procurement Healthy", "good"
        summary = "No immediate purchasing exception dominates the available BOM data."

    return {
        "posture": posture,
        "tone": tone,
        "summary": summary,
        "parts_reviewed": len(recommendations),
        "buy_now_count": buy_now,
        "monitor_count": monitor,
        "replace_count": replace,
        "second_source_count": second_source,
        "projected_order_value": round(order_value, 2),
        "shortage_exposure": round(shortage_exposure, 2),
        "recommendations": recommendations,
        "recommendation_df": df,
        "weekly_actions": recommendations[:10],
    }

"""Cadivor Milestone 12.0A — deterministic Engineering & Supply Advisor."""
from __future__ import annotations
from typing import Any, Dict, Iterable


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except Exception:
        return default


def _value(part: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = part.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return default


def _mpn(part: Dict[str, Any]) -> str:
    return _text(_value(part, "mpn", "MPN", "manufacturer_part_number", "part_number", default="Component"), "Component")


def _risk(part: Dict[str, Any]) -> str:
    return _text(_value(part, "risk_level", "Risk Level", "risk_level_display", default="Low"), "Low").lower()


def _lifecycle(part: Dict[str, Any]) -> str:
    return _text(_value(part, "lifecycle_status", "Lifecycle Status", "lifecycle", default="Unknown"), "Unknown")


def _stock(part: Dict[str, Any]) -> float:
    return _number(_value(part, "stock_available", "Stock Available", "stock", "total_stock", default=0), 0)


def _supplier_count(part: Dict[str, Any]) -> int:
    count = int(_number(_value(part, "supplier_count", "Supplier Count", "authorized_supplier_count", "distributor_count", default=0), 0))
    if count:
        return count
    suppliers = _value(part, "suppliers", "supplier_names", "authorized_distributors", default="")
    if isinstance(suppliers, (list, tuple, set)):
        return len([x for x in suppliers if _text(x)])
    text = _text(suppliers)
    if not text:
        return 0
    for sep in ("|", ";", ","):
        if sep in text:
            return len([x for x in text.split(sep) if x.strip()])
    return 1


def _lead_time(part: Dict[str, Any]) -> float:
    return _number(_value(part, "lead_time_weeks", "Lead Time Weeks", "lead_time", "Lead Time", default=0), 0)


def _priority_score(part: Dict[str, Any]) -> int:
    score = 0
    risk = _risk(part)
    lifecycle = _lifecycle(part).lower()
    stock = _stock(part)
    suppliers = _supplier_count(part)
    lead = _lead_time(part)
    score += 45 if "high" in risk else 25 if "medium" in risk else 0
    score += 45 if any(x in lifecycle for x in ("obsolete", "eol", "end of life")) else 32 if any(x in lifecycle for x in ("replacement", "nrnd", "not recommended")) else 0
    score += 28 if stock <= 0 else 18 if stock < 100 else 8 if stock < 500 else 0
    score += 20 if suppliers <= 1 else 10 if suppliers == 2 else 0
    score += 18 if lead >= 20 else 10 if lead >= 12 else 0
    return min(100, score)


def _action(part: Dict[str, Any]) -> Dict[str, Any]:
    mpn = _mpn(part)
    lifecycle = _lifecycle(part)
    lifecycle_l = lifecycle.lower()
    stock = _stock(part)
    suppliers = _supplier_count(part)
    lead = _lead_time(part)
    score = _priority_score(part)
    if any(x in lifecycle_l for x in ("obsolete", "eol", "end of life")):
        title, reason, impact, owner = f"Replace {mpn} before the next production release", f"Lifecycle status is {lifecycle}.", "Avoids emergency redesign and future material shortage.", "Engineering"
    elif any(x in lifecycle_l for x in ("replacement", "nrnd", "not recommended")):
        title, reason, impact, owner = f"Qualify a replacement for {mpn}", f"The lifecycle signal is {lifecycle}.", "Reduces future redesign and qualification risk.", "Engineering"
    elif stock <= 0:
        title, reason, impact, owner = f"Resolve the supply gap for {mpn}", "No available stock is recorded.", "Protects the next build from material-driven delay.", "Procurement"
    elif suppliers <= 1:
        title, reason, impact, owner = f"Add a second approved source for {mpn}", "The part has one recorded supplier source.", "Improves resilience and negotiating leverage.", "Procurement"
    elif lead >= 12:
        title, reason, impact, owner = f"Review the buy timing for {mpn}", f"Lead time is approximately {lead:g} weeks.", "Reduces late-purchase and schedule exposure.", "Supply Chain"
    elif stock < 100:
        title, reason, impact, owner = f"Monitor {mpn} before the next purchase cycle", f"Recorded stock is approximately {int(stock)} units.", "Provides time to react before availability becomes critical.", "Supply Chain"
    else:
        title, reason, impact, owner = f"Review {mpn}", "The component contributes to the current risk profile.", "Confirms the current selection remains acceptable.", "Engineering"
    return {
        "title": title,
        "reason": reason,
        "impact": impact,
        "owner": owner,
        "urgency": "Immediate" if score >= 75 else "High" if score >= 55 else "Medium",
        "effort": "Medium" if owner == "Engineering" and score >= 70 else "Low",
        "score": score,
    }


def build_engineering_supply_advisor(*, analysis: Dict[str, Any], parts: Iterable[Dict[str, Any]], alerts=None, alternatives=None) -> Dict[str, Any]:
    parts = list(parts or [])
    alerts = list(alerts or [])
    alternatives = list(alternatives or [])
    health = int(_number(analysis.get("health_score"), 0))
    high = int(_number(analysis.get("high_risk_count"), 0))
    medium = int(_number(analysis.get("medium_risk_count"), 0))

    lifecycle = [p for p in parts if any(x in _lifecycle(p).lower() for x in ("obsolete", "eol", "end of life", "replacement", "nrnd"))]
    no_stock = [p for p in parts if _stock(p) <= 0]
    limited_sources = [p for p in parts if _supplier_count(p) <= 1]
    long_lead = [p for p in parts if _lead_time(p) >= 12]

    ranked = sorted(parts, key=_priority_score, reverse=True)
    actions = [_action(p) for p in ranked if _priority_score(p) > 0][:5]
    if not actions:
        actions = [{
            "title": "Continue controlled lifecycle and sourcing monitoring",
            "reason": "No immediate exception dominates this BOM.",
            "impact": "Maintains readiness while preserving early warning coverage.",
            "owner": "Engineering & Supply Chain",
            "urgency": "Routine",
            "effort": "Low",
            "score": 20,
        }]

    engineering_risk = min(100, high * 28 + medium * 9 + len(lifecycle) * 14)
    supply_risk = min(100, len(no_stock) * 12 + len(limited_sources) * 7 + len(long_lead) * 8 + len(alerts) * 3)
    procurement_opportunity = min(100, len(limited_sources) * 15 + len(no_stock) * 12 + len(alternatives) * 6)
    confidence = max(58, min(96, 66 + min(12, len(parts)) + (5 if alerts else 0) + (5 if alternatives else 0)))
    overall = max(engineering_risk, supply_risk, 100 - health)

    if overall >= 70:
        assessment, tone = "Action Required", "bad"
    elif overall >= 40:
        assessment, tone = "Focused Review Recommended", "warn"
    else:
        assessment, tone = "Healthy with Monitoring", "good"

    return {
        "overall_assessment": assessment,
        "overall_tone": tone,
        "confidence": confidence,
        "engineering_risk_score": engineering_risk,
        "supply_risk_score": supply_risk,
        "procurement_opportunity_score": procurement_opportunity,
        "priority_actions": actions,
        "engineering_summary": f"{high} high-risk and {medium} medium-risk components are recorded. {len(lifecycle)} components show lifecycle concern. " + ("Address the highest-ranked replacement actions before release." if high or lifecycle else "No immediate redesign requirement dominates the BOM."),
        "procurement_summary": f"{len(limited_sources)} components have limited supplier coverage and {len(no_stock)} have no recorded stock. " + ("Prioritize second-source qualification and purchasing review." if limited_sources or no_stock else "No immediate purchasing exception dominates the BOM."),
        "supply_chain_summary": f"{len(long_lead)} long-lead components, {len(alerts)} monitoring alerts, and {len(alternatives)} saved alternatives inform the current supply outlook.",
        "executive_summary": "The BOM requires focused action before the next production commitment." if tone == "bad" else "The BOM is usable, but targeted engineering and procurement actions should be completed before scale-up." if tone == "warn" else "The BOM is broadly healthy for continued development with routine monitoring.",
        "metrics": {
            "obsolete_or_replacement": len(lifecycle),
            "no_stock": len(no_stock),
            "sole_source": len(limited_sources),
            "long_lead": len(long_lead),
            "monitoring_alerts": len(alerts),
            "saved_alternatives": len(alternatives),
        },
    }

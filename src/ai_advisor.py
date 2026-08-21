"""Cadivor Milestone 12.0B — Engineering Copilot Intelligence."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from src.bom_intelligence import infer_cross_component_relationships


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    result = str(value).strip()
    return result or default


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
    return _text(
        _value(
            part,
            "mpn",
            "MPN",
            "manufacturer_part_number",
            "part_number",
            default="Component",
        ),
        "Component",
    )


def _risk(part: Dict[str, Any]) -> str:
    return _text(
        _value(part, "risk_level", "Risk Level", "risk_level_display", default="Low"),
        "Low",
    ).lower()


def _lifecycle(part: Dict[str, Any]) -> str:
    return _text(
        _value(part, "lifecycle_status", "Lifecycle Status", "lifecycle", default="Unknown"),
        "Unknown",
    )


def _stock(part: Dict[str, Any]) -> float:
    return _number(
        _value(part, "stock_available", "Stock Available", "stock", "total_stock", default=0),
        0,
    )


def _supplier_count(part: Dict[str, Any]) -> int:
    explicit = int(
        _number(
            _value(
                part,
                "supplier_count",
                "Supplier Count",
                "authorized_supplier_count",
                "distributor_count",
                default=0,
            ),
            0,
        )
    )
    if explicit:
        return explicit

    suppliers = _value(
        part,
        "suppliers",
        "supplier_names",
        "authorized_distributors",
        default="",
    )
    if isinstance(suppliers, (list, tuple, set)):
        return len([item for item in suppliers if _text(item)])

    text = _text(suppliers)
    if not text:
        return 0
    for separator in ("|", ";", ","):
        if separator in text:
            return len([item for item in text.split(separator) if item.strip()])
    return 1


def _lead_time(part: Dict[str, Any]) -> float:
    return _number(
        _value(
            part,
            "lead_time_weeks",
            "Lead Time Weeks",
            "lead_time",
            "Lead Time",
            default=0,
        ),
        0,
    )


def _risk_score(part: Dict[str, Any]) -> int:
    stored = _number(_value(part, "risk_score", "Risk Score", default=0), 0)
    if stored > 0:
        return min(100, int(stored))

    score = 0
    risk = _risk(part)
    lifecycle = _lifecycle(part).lower()
    stock = _stock(part)
    suppliers = _supplier_count(part)
    lead_time = _lead_time(part)

    score += 42 if "high" in risk else 24 if "medium" in risk else 0
    score += (
        42
        if any(term in lifecycle for term in ("obsolete", "eol", "end of life"))
        else 30
        if any(term in lifecycle for term in ("replacement", "nrnd", "not recommended"))
        else 0
    )
    score += 25 if stock <= 0 else 16 if stock < 100 else 7 if stock < 500 else 0
    score += 18 if suppliers <= 1 else 9 if suppliers == 2 else 0
    score += 16 if lead_time >= 20 else 9 if lead_time >= 12 else 0
    return min(100, score)


def _signal(name: str, available: bool, detail: str) -> Dict[str, Any]:
    return {"name": name, "available": available, "detail": detail}


def _impact_level(score: int, modifier: int = 0) -> int:
    return max(1, min(5, round((score + modifier) / 20)))


def _priority_bucket(schedule: str, score: int) -> str:
    schedule_lower = schedule.lower()
    if score >= 80 or schedule_lower in {"today", "immediate"}:
        return "Do Now"
    if "week" in schedule_lower or score >= 60:
        return "Do This Week"
    if "production" in schedule_lower or "purchase" in schedule_lower or score >= 45:
        return "Do Before Production"
    return "Can Wait"


def _lifecycle_risk_label(lifecycle: str, lifecycle_problem: bool) -> str:
    lifecycle_lower = lifecycle.lower()
    if any(term in lifecycle_lower for term in ("obsolete", "eol", "end of life")):
        return "Critical"
    if lifecycle_problem:
        return "High"
    if lifecycle_lower not in {"", "unknown", "active"}:
        return "Medium"
    return "Low"


def _schedule_improvement_weeks(score: int, lead_problem: bool, stock_problem: bool) -> int:
    if score >= 80:
        return 3 if lead_problem else 2
    if score >= 60:
        return 2 if stock_problem else 1
    return 1


def _build_decision_impact(
    *,
    current_health: int,
    improvement: Mapping[str, Any],
    score: int,
    lifecycle: str,
    lifecycle_problem: bool,
    suppliers: int,
    source_problem: bool,
    effort_hours: int,
    lead_problem: bool,
    stock_problem: bool,
) -> Dict[str, Any]:
    health_after = int(improvement.get("health_after", current_health))
    supply_after = max(0, score - int(improvement.get("supply_risk_reduction", 0)))
    lifecycle_label = _lifecycle_risk_label(lifecycle, lifecycle_problem)
    lifecycle_after = (
        "Medium"
        if lifecycle_label in {"Critical", "High"} and lifecycle_problem
        else "Low"
        if lifecycle_problem
        else lifecycle_label
    )
    single_source_after = max(0, (suppliers or 1) - (1 if source_problem else 0))
    schedule_weeks = _schedule_improvement_weeks(score, lead_problem, stock_problem)
    manufacturing = (
        "Improves release continuity"
        if lifecycle_problem or stock_problem
        else "Maintains current readiness"
    )
    return {
        "health": {"before": current_health, "after": health_after},
        "supply_risk": {"before": score, "after": supply_after},
        "lifecycle_risk": {"before": lifecycle_label, "after": lifecycle_after},
        "single_source_exposure": {
            "before": suppliers or 1,
            "after": max(1, single_source_after) if source_problem else suppliers or 1,
        },
        "manufacturing_readiness": manufacturing,
        "schedule_improvement_weeks": schedule_weeks,
        "procurement_effort_hours": effort_hours,
        "schedule_confidence": (
            "High" if score >= 70 and not stock_problem else "Moderate" if score >= 50 else "Limited"
        ),
    }


def _build_inaction_consequences(
    *,
    lifecycle_problem: bool,
    stock_problem: bool,
    source_problem: bool,
    lead_problem: bool,
    score: int,
    lifecycle: str,
    mpn: str,
) -> List[str]:
    consequences: List[str] = []
    if lifecycle_problem:
        consequences.append(
            f"Replacement options for {mpn} may shrink as {lifecycle.lower()} status persists."
        )
        consequences.append("Production delay risk probability increases without a qualified successor.")
    if stock_problem:
        consequences.append("Next build may stall even if other components are available.")
        consequences.append("Supplier availability may worsen before procurement reacts.")
    if source_problem:
        consequences.append("Single-source disruption can halt purchasing with no approved fallback.")
    if lead_problem:
        consequences.append("Procurement may miss the required delivery window for near-term builds.")
    if score >= 60:
        consequences.append("Future redesign cost is likely to increase if validation moves closer to release.")
    if not consequences:
        consequences.append("An unresolved component concern may remain hidden until release review.")
    return consequences[:5]


def _build_confidence_breakdown(
    signals: List[Dict[str, Any]],
    *,
    alternative_count: int,
    alert_count: int,
    cross_bom: bool,
) -> List[Dict[str, Any]]:
    breakdown = [
        {
            "label": "Lifecycle data",
            "available": any(s["name"] == "Lifecycle status" and s["available"] for s in signals),
        },
        {
            "label": "Supplier data",
            "available": any(s["name"] == "Supplier coverage" and s["available"] for s in signals),
        },
        {
            "label": "Inventory data",
            "available": any(s["name"] == "Stock availability" and s["available"] for s in signals),
        },
        {
            "label": "Lead-time data",
            "available": any(s["name"] == "Lead time" and s["available"] for s in signals),
        },
        {
            "label": "Cross-BOM history",
            "available": cross_bom,
        },
        {
            "label": "Saved alternative evidence",
            "available": alternative_count > 0,
        },
        {
            "label": "Monitoring alerts",
            "available": alert_count > 0,
        },
        {
            "label": "Customer usage history",
            "available": False,
        },
    ]
    return breakdown


def _build_tradeoffs(
    *,
    mpn: str,
    action_route: str,
    lifecycle_problem: bool,
    source_problem: bool,
    score: int,
) -> List[Dict[str, str]]:
    if action_route != "alternative":
        return [
            {
                "option": "Option A — Monitor",
                "summary": "Lowest immediate effort",
                "detail": "Continue monitoring while evidence develops.",
            },
            {
                "option": "Option B — Validate",
                "summary": "Balanced engineering effort",
                "detail": "Confirm lifecycle and sourcing evidence before the next build.",
            },
            {
                "option": "Option C — Escalate",
                "summary": "Highest schedule protection",
                "detail": "Treat as a release gate if evidence deteriorates further.",
            },
        ]
    return [
        {
            "option": "Option A — Keep current part",
            "summary": "Lowest cost · highest lifecycle risk",
            "detail": f"Retain {mpn} for bridge builds only if inventory remains available.",
        },
        {
            "option": "Option B — Qualify successor",
            "summary": "Balanced reliability · moderate validation effort",
            "detail": "Approve a compatible alternate with documented test evidence.",
        },
        {
            "option": "Option C — Premium alternate",
            "summary": "Highest reliability · higher procurement cost",
            "detail": "Select a long-availability successor with stronger supplier coverage.",
        },
    ]


def _build_engineering_reasoning(
    *,
    mpn: str,
    lifecycle: str,
    lifecycle_problem: bool,
    stock: float,
    suppliers: int,
    source_problem: bool,
    score: int,
    cross_component: List[Mapping[str, str]],
    product_usage_count: int,
) -> List[str]:
    reasons: List[str] = []
    if product_usage_count > 1:
        reasons.append(f"{mpn} appears in {product_usage_count} active product record(s).")
    elif product_usage_count == 1:
        reasons.append(f"{mpn} is a recorded component in this saved BOM.")
    if lifecycle_problem:
        reasons.append(f"Lifecycle entered {lifecycle}.")
    if stock <= 0:
        reasons.append("Supplier inventory has fallen to zero recorded units.")
    elif stock < 100:
        reasons.append(f"Recorded inventory is approximately {int(stock)} units.")
    if source_problem:
        reasons.append(f"Only {suppliers or 1} supplier source is currently represented.")
    if not any(s for s in cross_component if "alternate" in s.get("relationship", "").lower()):
        if lifecycle_problem or source_problem:
            reasons.append("No approved alternate exists in saved evidence.")
    if cross_component:
        affected = ", ".join(item["component"] for item in cross_component[:3])
        reasons.append(f"Change may affect related components: {affected}.")
    if lifecycle_problem or source_problem or stock <= 0:
        reasons.append("Acting now reduces the chance of a production interruption.")
    if score >= 55 and not reasons:
        reasons.append(f"The component contributes a {score}/100 risk score to this BOM review.")
    return reasons[:6]


def _build_dependencies(*, action_route: str, category: str) -> List[str]:
    if action_route == "alternative":
        return [
            "Qualify alternate",
            "Approve alternate",
            "Update BOM",
            "Release production",
        ]
    if category in {"Procurement", "Sourcing", "Supply Chain"}:
        return [
            "Confirm supplier evidence",
            "Approve sourcing plan",
            "Update BOM",
            "Release production",
        ]
    if category == "Monitoring":
        return [
            "Configure monitoring",
            "Review alert thresholds",
            "Document response plan",
        ]
    return [
        "Complete engineering review",
        "Document decision",
        "Update BOM",
        "Release production",
    ]


def _build_decision_timeline(
    *,
    schedule: str,
    owner: str,
    support_owner: str,
    effort_hours: int,
) -> List[Dict[str, str]]:
    schedule_lower = schedule.lower()
    engineering_window = "Today" if "today" in schedule_lower else "This week"
    procurement_window = (
        "This week"
        if "week" in schedule_lower or effort_hours <= 2
        else "Before production"
    )
    return [
        {"phase": "Today", "owner": owner, "detail": "Assign owner and confirm evidence."},
        {"phase": "Engineering", "owner": owner, "detail": f"Complete review within {engineering_window.lower()}."},
        {"phase": "Procurement", "owner": support_owner, "detail": f"Support sourcing within {procurement_window.lower()}."},
        {"phase": "Validation", "owner": owner, "detail": f"Estimated effort: {effort_hours} hour(s)."},
        {"phase": "Production Release", "owner": "Release Manager", "detail": "Close before final production approval."},
    ]


def _product_usage_count(mpn: str, all_parts: Iterable[Dict[str, Any]]) -> int:
    normalized = mpn.strip().upper()
    if not normalized or normalized == "COMPONENT":
        return 0
    count = 0
    for row in all_parts or []:
        candidate = _mpn(row).upper()
        if candidate == normalized:
            count += 1
    return max(1, count)


def _action(
    part: Dict[str, Any],
    current_health: int,
    *,
    all_parts: Optional[Iterable[Dict[str, Any]]] = None,
    alternative_rows: Optional[Iterable[Dict[str, Any]]] = None,
    alert_count: int = 0,
) -> Dict[str, Any]:
    mpn = _mpn(part)
    lifecycle = _lifecycle(part)
    lifecycle_lower = lifecycle.lower()
    stock = _stock(part)
    suppliers = _supplier_count(part)
    lead_time = _lead_time(part)
    score = _risk_score(part)
    risk = _risk(part)

    lifecycle_problem = any(
        term in lifecycle_lower
        for term in ("obsolete", "eol", "end of life", "replacement", "nrnd", "not recommended")
    )
    stock_problem = stock <= 0
    source_problem = suppliers <= 1
    lead_problem = lead_time >= 12

    if any(term in lifecycle_lower for term in ("obsolete", "eol", "end of life")):
        title = f"Replace {mpn} before production release"
        category = "Lifecycle"
        recommendation = (
            "Begin replacement qualification now and keep the current part only for controlled "
            "prototype or bridge builds."
        )
        why = (
            f"{mpn} is recorded as {lifecycle}. This is a direct continuity risk because future "
            "availability and manufacturer support can deteriorate without notice."
        )
        ignored = (
            "The team may be forced into an emergency redesign after purchasing or production "
            "commitments have already been made."
        )
        owner = "Electrical Engineer"
        support_owner = "Component Engineer"
        effort_hours = 8
        schedule = "Before production"
        action_route = "alternative"
    elif any(term in lifecycle_lower for term in ("replacement", "nrnd", "not recommended")):
        title = f"Qualify the preferred successor for {mpn}"
        category = "Engineering"
        recommendation = (
            "Evaluate a compatible successor during the current design revision and document "
            "the approved substitution before the next build."
        )
        why = (
            f"The lifecycle signal is {lifecycle}. Inventory may still be available, but the "
            "manufacturer is indicating that the current selection should not remain the long-term design choice."
        )
        ignored = (
            "Qualification work will move closer to the production deadline, increasing schedule "
            "pressure and the cost of validation."
        )
        owner = "Electrical Engineer"
        support_owner = "Procurement Specialist"
        effort_hours = 5
        schedule = "This week"
        action_route = "alternative"
    elif stock_problem:
        title = f"Resolve the immediate supply gap for {mpn}"
        category = "Procurement"
        recommendation = (
            "Check authorized distributors, approved alternates, and available bridge inventory "
            "before confirming the next build schedule."
        )
        why = (
            "Cadivor currently records no available stock for this component. A purchase order "
            "cannot be considered secure until a viable source or approved substitute is confirmed."
        )
        ignored = (
            "The next build can be delayed even if every other component is available."
        )
        owner = "Procurement Specialist"
        support_owner = "Supply Chain Manager"
        effort_hours = 2
        schedule = "Today"
        action_route = "alternative"
    elif source_problem:
        title = f"Approve a second source for {mpn}"
        category = "Sourcing"
        recommendation = (
            "Qualify another authorized distributor or compatible alternate and add it to the "
            "approved sourcing plan."
        )
        why = (
            f"Only {suppliers or 1} supplier source is currently represented. A single-source "
            "dependency concentrates availability, pricing, and fulfillment risk."
        )
        ignored = (
            "A disruption at the current source can stop purchasing with no approved fallback."
        )
        owner = "Procurement Specialist"
        support_owner = "Component Engineer"
        effort_hours = 2
        schedule = "This week"
        action_route = "alternative"
    elif lead_problem:
        title = f"Secure the purchasing window for {mpn}"
        category = "Supply Chain"
        recommendation = (
            "Align the purchase date with the production schedule and evaluate buffer inventory "
            "or an approved lower-lead-time alternative."
        )
        why = (
            f"The recorded lead time is approximately {lead_time:g} weeks. That duration can exceed "
            "the remaining planning window for a near-term build."
        )
        ignored = (
            "Procurement may miss the required delivery date and create a schedule-driven shortage."
        )
        owner = "Supply Chain Manager"
        support_owner = "Procurement Specialist"
        effort_hours = 1
        schedule = "Before purchase order"
        action_route = "monitor"
    elif stock < 100:
        title = f"Place {mpn} under active monitoring"
        category = "Monitoring"
        recommendation = (
            "Track inventory and supplier changes weekly and prepare a sourcing response before "
            "stock reaches a critical threshold."
        )
        why = f"Recorded inventory is approximately {int(stock)} units, leaving limited reaction time."
        ignored = "Availability may become critical before the team begins sourcing or qualification work."
        owner = "Supply Chain Manager"
        support_owner = "Procurement Specialist"
        effort_hours = 1
        schedule = "This week"
        action_route = "monitor"
    else:
        title = f"Complete a focused review of {mpn}"
        category = "Engineering Review"
        recommendation = (
            "Confirm lifecycle, sourcing coverage, and replacement readiness before final release."
        )
        why = (
            f"The component contributes a {score}/100 risk score to the current BOM review."
        )
        ignored = (
            "An unresolved component-level concern can remain hidden until purchasing or release review."
        )
        owner = "Component Engineer"
        support_owner = "Electrical Engineer"
        effort_hours = 1
        schedule = "Before release"
        action_route = "component"

    confidence_inputs = [
        _signal("Lifecycle status", _lifecycle(part).lower() != "unknown", lifecycle),
        _signal("Stock availability", stock >= 0, f"{int(stock)} units recorded"),
        _signal("Supplier coverage", suppliers > 0, f"{suppliers} supplier source(s) recorded"),
        _signal("Lead time", lead_time > 0, f"{lead_time:g} weeks" if lead_time else "Not available"),
        _signal("Risk classification", bool(risk), risk.title()),
    ]
    available_signals = sum(1 for signal in confidence_inputs if signal["available"])
    confidence = min(96, 58 + available_signals * 7 + (6 if score >= 55 else 0))

    health_gain = max(1, min(12, round(score / 11)))
    projected_health = min(100, current_health + health_gain)
    supply_reduction = max(2, min(18, round(score / 7)))

    part_list = list(all_parts or [])
    cross_component = infer_cross_component_relationships(part, part_list)
    usage_count = _product_usage_count(mpn, part_list)
    alt_for_part = [
        row
        for row in (alternative_rows or [])
        if _text(row.get("original_part") or row.get("original_mpn") or row.get("part_number")).upper()
        == mpn.upper()
    ]
    improvement = {
        "health_before": current_health,
        "health_after": projected_health,
        "health_gain": health_gain,
        "supply_risk_reduction": supply_reduction,
        "lifecycle_issues_removed": 1 if lifecycle_problem else 0,
        "sourcing_issues_removed": 1 if source_problem or stock_problem else 0,
    }
    decision_impact = _build_decision_impact(
        current_health=current_health,
        improvement=improvement,
        score=score,
        lifecycle=lifecycle,
        lifecycle_problem=lifecycle_problem,
        suppliers=suppliers,
        source_problem=source_problem,
        effort_hours=effort_hours,
        lead_problem=lead_problem,
        stock_problem=stock_problem,
    )

    return {
        "part_number": mpn,
        "title": title,
        "category": category,
        "recommendation": recommendation,
        "why": why,
        "if_ignored": ignored,
        "owner": owner,
        "support_owner": support_owner,
        "effort": f"{effort_hours} hour" if effort_hours == 1 else f"{effort_hours} hours",
        "effort_hours": effort_hours,
        "business_priority": (
            "Critical" if score >= 80 else "High" if score >= 60 else "Moderate"
        ),
        "schedule": schedule,
        "priority_bucket": _priority_bucket(schedule, score),
        "score": score,
        "confidence": confidence,
        "signals": confidence_inputs,
        "signal_count": available_signals,
        "confidence_breakdown": _build_confidence_breakdown(
            confidence_inputs,
            alternative_count=len(alt_for_part),
            alert_count=alert_count,
            cross_bom=usage_count > 1,
        ),
        "action_route": action_route,
        "impacts": {
            "engineering": _impact_level(score, 5 if lifecycle_problem else -8),
            "procurement": _impact_level(score, 8 if stock_problem or source_problem else -5),
            "production": _impact_level(score, 6 if stock_problem or lifecycle_problem else -10),
            "schedule": _impact_level(score, 8 if lead_problem or stock_problem else -8),
            "cost": _impact_level(score, 2 if source_problem or lifecycle_problem else -12),
        },
        "improvement": improvement,
        "decision_impact": decision_impact,
        "inaction_consequences": _build_inaction_consequences(
            lifecycle_problem=lifecycle_problem,
            stock_problem=stock_problem,
            source_problem=source_problem,
            lead_problem=lead_problem,
            score=score,
            lifecycle=lifecycle,
            mpn=mpn,
        ),
        "tradeoffs": _build_tradeoffs(
            mpn=mpn,
            action_route=action_route,
            lifecycle_problem=lifecycle_problem,
            source_problem=source_problem,
            score=score,
        ),
        "engineering_reasoning": _build_engineering_reasoning(
            mpn=mpn,
            lifecycle=lifecycle,
            lifecycle_problem=lifecycle_problem,
            stock=stock,
            suppliers=suppliers,
            source_problem=source_problem,
            score=score,
            cross_component=cross_component,
            product_usage_count=usage_count,
        ),
        "dependencies": _build_dependencies(action_route=action_route, category=category),
        "cross_component_impact": cross_component,
        "decision_timeline": _build_decision_timeline(
            schedule=schedule,
            owner=owner,
            support_owner=support_owner,
            effort_hours=effort_hours,
        ),
    }


def build_engineering_supply_advisor(
    *,
    analysis: Dict[str, Any],
    parts: Iterable[Dict[str, Any]],
    alerts: Iterable[Dict[str, Any]] | None = None,
    alternatives: Iterable[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    part_rows = list(parts or [])
    alert_rows = list(alerts or [])
    alternative_rows = list(alternatives or [])

    health = int(_number(analysis.get("health_score"), 0))
    high = int(_number(analysis.get("high_risk_count"), 0))
    medium = int(_number(analysis.get("medium_risk_count"), 0))

    lifecycle_concerns = [
        part
        for part in part_rows
        if any(
            term in _lifecycle(part).lower()
            for term in ("obsolete", "eol", "end of life", "replacement", "nrnd", "not recommended")
        )
    ]
    no_stock = [part for part in part_rows if _stock(part) <= 0]
    limited_sources = [part for part in part_rows if _supplier_count(part) <= 1]
    long_lead = [part for part in part_rows if _lead_time(part) >= 12]

    ranked = sorted(part_rows, key=_risk_score, reverse=True)
    actions = [
        _action(
            part,
            health,
            all_parts=part_rows,
            alternative_rows=alternative_rows,
            alert_count=len(alert_rows),
        )
        for part in ranked
        if _risk_score(part) > 0
    ][:5]

    if not actions:
        actions = [
            {
                "part_number": "BOM",
                "title": "Maintain controlled lifecycle and sourcing monitoring",
                "category": "Monitoring",
                "recommendation": "Continue periodic review of lifecycle, stock, supplier, and lead-time changes.",
                "why": "No immediate exception dominates the current BOM.",
                "if_ignored": "Emerging risks may not be identified early enough for low-cost action.",
                "owner": "Component Engineer",
                "support_owner": "Supply Chain Manager",
                "effort": "1 hour",
                "effort_hours": 1,
                "business_priority": "Routine",
                "schedule": "Monthly",
                "score": 20,
                "confidence": 75,
                "signals": [],
                "signal_count": 0,
                "action_route": "monitor",
                "impacts": {
                    "engineering": 1,
                    "procurement": 1,
                    "production": 1,
                    "schedule": 1,
                    "cost": 1,
                },
                "improvement": {
                    "health_before": health,
                    "health_after": health,
                    "health_gain": 0,
                    "supply_risk_reduction": 0,
                    "lifecycle_issues_removed": 0,
                    "sourcing_issues_removed": 0,
                },
                "priority_bucket": "Can Wait",
                "decision_impact": {},
                "inaction_consequences": [],
                "confidence_breakdown": [],
                "tradeoffs": [],
                "engineering_reasoning": [],
                "dependencies": [],
                "cross_component_impact": [],
                "decision_timeline": [],
            }
        ]

    engineering_exposure = min(100, high * 28 + medium * 9 + len(lifecycle_concerns) * 14)
    supply_exposure = min(
        100,
        len(no_stock) * 14
        + len(limited_sources) * 8
        + len(long_lead) * 9
        + len(alert_rows) * 3,
    )
    confidence = max(
        60,
        min(
            96,
            64
            + min(14, len(part_rows))
            + (5 if alert_rows else 0)
            + (5 if alternative_rows else 0),
        ),
    )

    blocking_actions = [action for action in actions if action["score"] >= 80]
    high_actions = [action for action in actions if action["score"] >= 60]
    total_effort = sum(action.get("effort_hours", 0) for action in actions)

    if blocking_actions or no_stock:
        readiness = "Needs Action Before Production"
        readiness_tone = "bad"
        readiness_reason = (
            f"{len(blocking_actions)} critical recommendation(s) and "
            f"{len(no_stock)} no-stock component(s) require resolution."
        )
    elif high_actions or lifecycle_concerns or limited_sources:
        readiness = "Prototype Ready — Production Review Needed"
        readiness_tone = "warn"
        readiness_reason = (
            f"{len(high_actions)} high-priority action(s), "
            f"{len(lifecycle_concerns)} lifecycle concern(s), and "
            f"{len(limited_sources)} limited-source component(s) remain."
        )
    else:
        readiness = "Production Ready with Monitoring"
        readiness_tone = "good"
        readiness_reason = "No production blocker dominates the current analysis."

    projected_health = min(
        100,
        health + sum(action["improvement"]["health_gain"] for action in actions[:3]),
    )
    projected_supply = max(
        0,
        supply_exposure
        - sum(action["improvement"]["supply_risk_reduction"] for action in actions[:3]),
    )

    executive_recommendation = (
        f"This BOM is currently classified as {readiness.lower()}. "
        f"Cadivor recommends completing {len(high_actions) or len(actions)} focused action(s) "
        f"before final production approval. Estimated combined team effort is approximately "
        f"{total_effort} hours. Completing the three highest-priority actions is projected to "
        f"improve BOM health from {health} to {projected_health} and reduce supply exposure "
        f"from {supply_exposure} to approximately {projected_supply}."
    )

    documentation_score = min(
        100,
        55
        + (15 if alternative_rows else 0)
        + (10 if alert_rows else 0)
        + (10 if len(part_rows) >= 5 else 5)
        + (10 if confidence >= 80 else 0),
    )
    engineering_score = max(0, min(100, 100 - engineering_exposure))
    supply_chain_score = max(0, min(100, 100 - supply_exposure))
    manufacturing_score = max(
        0,
        min(
            100,
            health
            - len(no_stock) * 4
            - len(lifecycle_concerns) * 3
            + (8 if not blocking_actions else -len(blocking_actions) * 5),
        ),
    )
    procurement_score = max(
        0,
        min(
            100,
            100
            - len(limited_sources) * 5
            - len(no_stock) * 4
            - len(long_lead) * 3,
        ),
    )
    overall_readiness = round(
        (
            engineering_score
            + supply_chain_score
            + manufacturing_score
            + procurement_score
            + documentation_score
        )
        / 5
    )

    return {
        "production_readiness": readiness,
        "readiness_tone": readiness_tone,
        "readiness_reason": readiness_reason,
        "confidence": confidence,
        "engineering_exposure_score": engineering_exposure,
        "supply_exposure_score": supply_exposure,
        "executive_readiness": {
            "overall": overall_readiness,
            "engineering": engineering_score,
            "supply_chain": supply_chain_score,
            "manufacturing": manufacturing_score,
            "procurement": procurement_score,
            "documentation": documentation_score,
        },
        "priority_actions": actions,
        "estimated_total_effort": total_effort,
        "projected_health": projected_health,
        "projected_supply_exposure": projected_supply,
        "executive_recommendation": executive_recommendation,
        "engineering_summary": (
            f"{high} high-risk and {medium} medium-risk components are recorded. "
            f"{len(lifecycle_concerns)} component(s) show lifecycle concern."
        ),
        "procurement_summary": (
            f"{len(limited_sources)} component(s) have limited sourcing coverage and "
            f"{len(no_stock)} component(s) have no recorded stock."
        ),
        "supply_chain_summary": (
            f"{len(long_lead)} long-lead component(s), {len(alert_rows)} monitoring alert(s), "
            f"and {len(alternative_rows)} saved alternative record(s) inform the outlook."
        ),
        "metrics": {
            "lifecycle_concerns": len(lifecycle_concerns),
            "no_stock": len(no_stock),
            "limited_sources": len(limited_sources),
            "long_lead": len(long_lead),
            "active_alerts": len(alert_rows),
            "saved_alternatives": len(alternative_rows),
        },
    }

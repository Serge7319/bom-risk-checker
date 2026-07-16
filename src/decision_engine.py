"""Cadivor Milestone 13.1 — Decision workflow and management intelligence."""
from __future__ import annotations

from hashlib import sha1
from typing import Any, Dict, Iterable, List

import pandas as pd


STATUSES = [
    "New",
    "Engineering Review",
    "Procurement Review",
    "Manager Approval",
    "Production Approved",
    "Closed",
    "Rejected",
]

WORKFLOW_PROGRESS = {
    "New": 10,
    "Open": 10,
    "Engineering Review": 30,
    "Procurement Review": 50,
    "Manager Approval": 70,
    "Awaiting Approval": 70,
    "Approved": 85,
    "Production Approved": 90,
    "Production Ready": 90,
    "Closed": 100,
    "Rejected": 100,
}


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    result = str(value).strip()
    return result or default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except Exception:
        return default


def _stable_id(*values: Any) -> str:
    raw = "|".join(_text(value) for value in values)
    return sha1(raw.encode("utf-8")).hexdigest()[:16]


def _severity_rank(value: Any) -> int:
    text = _text(value).lower()
    if "critical" in text:
        return 4
    if "high" in text:
        return 3
    if "medium" in text:
        return 2
    if "low" in text:
        return 1
    return 0


def _timestamp(value: Any) -> pd.Timestamp:
    try:
        parsed = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(parsed):
            return pd.Timestamp.now(tz="UTC")
        return parsed
    except Exception:
        return pd.Timestamp.now(tz="UTC")


def _days_open(created_at: Any, status: str) -> int:
    if status in ("Closed", "Rejected"):
        return 0
    created = _timestamp(created_at)
    return max(0, int((pd.Timestamp.now(tz="UTC") - created).total_seconds() // 86400))


def _aging_tone(days_open: int) -> str:
    if days_open >= 14:
        return "bad"
    if days_open >= 7:
        return "warn"
    if days_open >= 3:
        return "watch"
    return "good"


def _priority_breakdown(decision: Dict[str, Any]) -> Dict[str, int]:
    text = " ".join(
        [
            _text(decision.get("decision_type")),
            _text(decision.get("reason")),
            _text(decision.get("recommended_action")),
        ]
    ).lower()
    base = int(_number(decision.get("priority_score"), 0))

    production = min(40, max(5, round(base * 0.40)))
    lifecycle = 0
    supply = 0
    cost = 0
    compliance = 0

    if "lifecycle" in text or any(term in text for term in ("obsolete", "replacement", "eol", "nrnd")):
        lifecycle = min(25, max(10, round(base * 0.25)))
    if any(term in text for term in ("stock", "supplier", "supply", "purchasing", "inventory")):
        supply = min(20, max(8, round(base * 0.20)))
    if any(term in text for term in ("cost", "price", "commercial")):
        cost = min(10, max(5, round(base * 0.10)))
    if any(term in text for term in ("approval", "release", "production")):
        compliance = min(5, max(2, round(base * 0.05)))

    total = production + lifecycle + supply + cost + compliance
    if total > 100:
        production = max(0, production - (total - 100))

    return {
        "Production Risk": production,
        "Lifecycle Risk": lifecycle,
        "Supply Risk": supply,
        "Cost Risk": cost,
        "Approval Risk": compliance,
    }


def _confidence_reasons(decision: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    evidence = decision.get("evidence") or []
    evidence_text = " ".join(str(item).lower() for item in evidence)

    if evidence:
        reasons.append("Multiple decision signals are available.")
    if "current value" in evidence_text or "stock" in evidence_text:
        reasons.append("Current monitoring or availability data is recorded.")
    if "severity" in evidence_text or "risk" in evidence_text:
        reasons.append("Risk severity is explicitly classified.")
    if decision.get("analysis_id"):
        reasons.append("The decision is linked to a saved BOM record.")
    if int(_number(decision.get("priority_score"), 0)) >= 65:
        reasons.append("The recommendation is supported by a strong priority signal.")
    if not reasons:
        reasons.append("Confidence is based on the currently available engineering record.")
    return reasons[:4]


def enrich_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(decision)
    status = _text(enriched.get("status"), "New")
    if status == "Open":
        status = "New"
    created_at = enriched.get("detected_at") or enriched.get("created_at")
    days_open = _days_open(created_at, status)

    enriched["status"] = status
    enriched["workflow_progress"] = WORKFLOW_PROGRESS.get(status, 10)
    enriched["next_required_action"] = {
        "New": "Assign an owner and begin engineering review.",
        "Engineering Review": "Complete technical validation and document findings.",
        "Procurement Review": "Confirm supplier, stock, lead time, and commercial readiness.",
        "Manager Approval": "Approve, reject, or return the decision for further review.",
        "Production Approved": "Complete release documentation and close the decision.",
        "Closed": "No additional action required.",
        "Rejected": "Record the rejection rationale and alternative path.",
    }.get(status, "Confirm the next workflow action.")
    enriched["days_open"] = days_open
    enriched["aging_tone"] = _aging_tone(days_open)
    enriched["priority_breakdown"] = _priority_breakdown(enriched)
    enriched["confidence_reasons"] = _confidence_reasons(enriched)
    return enriched


def _alert_decision(alert: Dict[str, Any]) -> Dict[str, Any]:
    part = _text(alert.get("part_number"), "Component")
    alert_type = _text(alert.get("alert_type"), "Monitoring change")
    message = _text(alert.get("alert_message"), "Monitoring change detected")
    severity = _text(alert.get("severity"), "Medium").title()
    current_value = _text(alert.get("current_value"), "Unknown")
    detected_at = _text(alert.get("created_at"), "Unknown")
    text = f"{alert_type} {message}".lower()

    score = _severity_rank(severity) * 20
    owner = "Engineering"
    supporting_team = "Supply Chain"
    due = "This week"
    effort = 2
    action = f"Review monitoring change for {part}"
    decision_type = "Monitoring Review"
    health_gain = 2
    supply_reduction = 4
    lifecycle_reduction = 0

    if "stock" in text:
        owner = "Procurement"
        supporting_team = "Supply Chain"
        decision_type = "Supply Decision"
        stock = _number(alert.get("current_value"), 0)
        if stock <= 0:
            score += 40
            due = "Today"
            action = f"Approve a substitute or secure inventory for {part}"
            health_gain = 7
            supply_reduction = 18
        elif stock < 100:
            score += 25
            due = "Within 48 hours"
            action = f"Approve purchasing coverage for {part}"
            health_gain = 4
            supply_reduction = 12
        else:
            score += 10
            action = f"Review stock trend and purchasing window for {part}"
            supply_reduction = 7

    if "lifecycle" in text:
        owner = "Component Engineering"
        supporting_team = "Electrical Engineering"
        decision_type = "Lifecycle Decision"
        if any(term in text for term in ("obsolete", "eol", "end of life")):
            score += 40
            due = "Before production approval"
            effort = 6
            action = f"Approve replacement qualification for {part}"
            health_gain = 9
            supply_reduction = 12
            lifecycle_reduction = 1
        elif any(term in text for term in ("replacement", "nrnd", "not recommended")):
            score += 28
            due = "This week"
            effort = 4
            action = f"Review and qualify a successor for {part}"
            health_gain = 6
            lifecycle_reduction = 1
        else:
            score += 12
            action = f"Verify lifecycle status for {part}"

    if "price" in text:
        owner = "Procurement"
        supporting_team = "Finance"
        decision_type = "Cost Decision"
        score += 12
        due = "Before next purchase order"
        action = f"Review cost exposure and sourcing options for {part}"
        health_gain = 2

    score = min(100, score)
    confidence = min(96, 68 + _severity_rank(severity) * 6 + (6 if current_value != "Unknown" else 0))
    priority = (
        "Critical" if score >= 85
        else "High" if score >= 65
        else "Medium" if score >= 40
        else "Routine"
    )

    return {
        "decision_id": _stable_id(part, alert_type, message, detected_at),
        "source": "Monitoring",
        "analysis_id": _text(alert.get("analysis_id")),
        "part_number": part,
        "decision_type": decision_type,
        "title": action,
        "reason": message,
        "evidence": [
            f"Alert type: {alert_type}",
            f"Severity: {severity}",
            f"Previous value: {_text(alert.get('previous_value'), 'Unknown')}",
            f"Current value: {current_value}",
            f"Detected: {detected_at}",
        ],
        "owner": owner,
        "supporting_team": supporting_team,
        "due_date": due,
        "estimated_effort_hours": effort,
        "priority_score": score,
        "priority": priority,
        "confidence": confidence,
        "recommended_action": action,
        "expected_impact": (
            "Reduces continuity, purchasing, or production risk created by the detected change."
        ),
        "current_health": 0,
        "projected_health": health_gain,
        "health_gain": health_gain,
        "supply_risk_reduction": supply_reduction,
        "lifecycle_exposure_reduction": lifecycle_reduction,
        "estimated_cost_impact": "Requires commercial validation",
        "detected_at": detected_at,
    }


def _analysis_decisions(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    analysis_id = _text(analysis.get("id"))
    project = _text(
        analysis.get("project_name") or analysis.get("name"),
        "Saved BOM",
    )
    health = int(_number(analysis.get("health_score"), 0))
    high = int(_number(analysis.get("high_risk_count") or analysis.get("high_risk_parts"), 0))
    medium = int(_number(analysis.get("medium_risk_count") or analysis.get("medium_risk_parts"), 0))
    created = _text(analysis.get("created_at"), "Unknown")
    decisions: List[Dict[str, Any]] = []

    if high > 0:
        score = min(100, 70 + high * 8)
        gain = min(12, high * 4)
        decisions.append(
            {
                "decision_id": _stable_id(analysis_id, "high-risk-review"),
                "source": "BOM Analysis",
                "analysis_id": analysis_id,
                "part_number": project,
                "decision_type": "Release Decision",
                "title": f"Resolve high-risk components in {project}",
                "reason": f"{high} high-risk component(s) require engineering review.",
                "evidence": [
                    f"Current BOM health: {health}/100",
                    f"High-risk components: {high}",
                    f"Medium-risk components: {medium}",
                    f"Analysis created: {created}",
                ],
                "owner": "Engineering Manager",
                "supporting_team": "Component Engineering",
                "due_date": "Before production approval",
                "estimated_effort_hours": max(3, high * 3),
                "priority_score": score,
                "priority": "Critical" if score >= 85 else "High",
                "confidence": 88,
                "recommended_action": "Complete component-level review and document approved mitigations.",
                "expected_impact": "Prevents unresolved component risk from entering production.",
                "current_health": health,
                "projected_health": min(100, health + gain),
                "health_gain": gain,
                "supply_risk_reduction": min(20, high * 5),
                "lifecycle_exposure_reduction": min(high, 3),
                "estimated_cost_impact": "Avoids emergency redesign cost",
                "detected_at": created,
            }
        )

    if medium > 0 and high == 0:
        gain = min(8, medium * 2)
        decisions.append(
            {
                "decision_id": _stable_id(analysis_id, "focused-review"),
                "source": "BOM Analysis",
                "analysis_id": analysis_id,
                "part_number": project,
                "decision_type": "Engineering Review",
                "title": f"Complete focused review for {project}",
                "reason": f"{medium} medium-risk component(s) remain before release.",
                "evidence": [
                    f"Current BOM health: {health}/100",
                    f"Medium-risk components: {medium}",
                    f"Analysis created: {created}",
                ],
                "owner": "Component Engineering",
                "supporting_team": "Procurement",
                "due_date": "This week",
                "estimated_effort_hours": max(2, medium * 2),
                "priority_score": min(75, 40 + medium * 8),
                "priority": "High" if medium >= 3 else "Medium",
                "confidence": 82,
                "recommended_action": "Review lifecycle, supplier coverage, and replacement readiness.",
                "expected_impact": "Improves release confidence and preserves sourcing options.",
                "current_health": health,
                "projected_health": min(100, health + gain),
                "health_gain": gain,
                "supply_risk_reduction": min(12, medium * 3),
                "lifecycle_exposure_reduction": 0,
                "estimated_cost_impact": "Low-cost preventive review",
                "detected_at": created,
            }
        )

    return decisions


def build_decision_center(
    *,
    alert_df: pd.DataFrame,
    analyses: Iterable[Dict[str, Any]],
    saved_state: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    state = saved_state or {}
    decisions: List[Dict[str, Any]] = []

    if isinstance(alert_df, pd.DataFrame) and not alert_df.empty:
        decisions.extend(_alert_decision(row) for row in alert_df.to_dict("records"))

    for analysis in analyses or []:
        decisions.extend(_analysis_decisions(analysis))

    deduped: Dict[str, Dict[str, Any]] = {}
    for decision in decisions:
        existing = deduped.get(decision["decision_id"])
        if existing is None or decision["priority_score"] > existing["priority_score"]:
            deduped[decision["decision_id"]] = decision

    final = []
    for decision in deduped.values():
        saved = state.get(decision["decision_id"], {})
        decision = dict(decision)
        decision["status"] = _text(saved.get("status"), "New")
        decision["assigned_owner"] = _text(saved.get("owner"), decision["owner"])
        decision["updated_at"] = _text(saved.get("updated_at"), decision["detected_at"])
        decision["notes"] = list(saved.get("notes") or [])
        final.append(enrich_decision(decision))

    final.sort(
        key=lambda item: (
            item["status"] in ("Closed", "Rejected"),
            -int(item["priority_score"]),
        )
    )

    open_decisions = [
        decision
        for decision in final
        if decision["status"] not in ("Closed", "Rejected")
    ]
    critical = [decision for decision in open_decisions if decision["priority_score"] >= 85]
    awaiting = [
        decision
        for decision in open_decisions
        if decision["status"] in ("Manager Approval", "Awaiting Approval")
    ]
    production_ready = [
        decision
        for decision in final
        if decision["status"] in ("Production Approved", "Production Ready")
    ]
    closed = [
        decision
        for decision in final
        if decision["status"] in ("Closed", "Rejected")
    ]

    average_age = round(
        sum(int(decision.get("days_open", 0)) for decision in open_decisions)
        / max(1, len(open_decisions)),
        1,
    )
    projected_health_gain = sum(
        int(decision.get("health_gain", 0)) for decision in open_decisions[:10]
    )
    projected_risk_reduction = sum(
        int(decision.get("supply_risk_reduction", 0)) for decision in open_decisions[:10]
    )

    return {
        "decisions": final,
        "open_count": len(open_decisions),
        "critical_count": len(critical),
        "awaiting_approval_count": len(awaiting),
        "production_ready_count": len(production_ready),
        "closed_count": len(closed),
        "estimated_hours": sum(
            int(decision["estimated_effort_hours"])
            for decision in open_decisions
        ),
        "average_age_days": average_age,
        "projected_health_gain": projected_health_gain,
        "projected_risk_reduction": projected_risk_reduction,
    }

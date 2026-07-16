"""Cadivor Milestone 15.0 — AI Mission Control intelligence."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

import pandas as pd


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


def _analysis_name(row: Dict[str, Any]) -> str:
    return _text(
        row.get("project_name")
        or row.get("name")
        or row.get("filename"),
        "Saved BOM",
    )


def _analysis_health(row: Dict[str, Any]) -> int:
    return int(
        max(
            0,
            min(
                100,
                _number(
                    row.get("health_score")
                    or row.get("health")
                    or row.get("bom_health"),
                    0,
                ),
            ),
        )
    )


def _analysis_risk(row: Dict[str, Any]) -> int:
    return int(
        _number(
            row.get("high_risk_count")
            or row.get("high_risk_parts")
            or row.get("high_risk"),
            0,
        )
    )


def _decision_is_open(decision: Dict[str, Any]) -> bool:
    return _text(decision.get("status"), "New") not in {
        "Closed",
        "Rejected",
    }


def _owner_group(owner: Any) -> str:
    text = _text(owner, "Engineering").lower()
    if "procurement" in text or "supply" in text or "purchas" in text:
        return "Procurement"
    if "quality" in text or "qa" in text or "compliance" in text:
        return "Quality"
    if "manager" in text or "management" in text or "executive" in text:
        return "Management"
    return "Engineering"


def build_mission_control(
    *,
    user_name: str,
    analyses: Iterable[Dict[str, Any]],
    parts: Iterable[Dict[str, Any]],
    alerts: Iterable[Dict[str, Any]],
    decisions: Iterable[Dict[str, Any]],
    procurement: Dict[str, Any],
) -> Dict[str, Any]:
    analysis_rows = list(analyses or [])
    part_rows = list(parts or [])
    alert_rows = list(alerts or [])
    decision_rows = list(decisions or [])

    projects: List[Dict[str, Any]] = []
    for row in analysis_rows:
        health = _analysis_health(row)
        high_risk = _analysis_risk(row)
        if health >= 90 and high_risk == 0:
            readiness = "Production Ready"
            tone = "good"
        elif health >= 75 and high_risk <= 1:
            readiness = "Focused Review"
            tone = "warn"
        else:
            readiness = "Blocked"
            tone = "bad"

        projects.append(
            {
                "analysis_id": _text(row.get("id")),
                "project": _analysis_name(row),
                "health": health,
                "high_risk": high_risk,
                "parts": int(
                    _number(
                        row.get("total_parts")
                        or row.get("parts_count")
                        or row.get("part_count"),
                        0,
                    )
                ),
                "readiness": readiness,
                "tone": tone,
                "updated": _text(
                    row.get("updated_at") or row.get("created_at"),
                    "Unknown",
                ),
            }
        )

    projects.sort(
        key=lambda item: (
            item["readiness"] == "Production Ready",
            item["health"],
        )
    )

    open_decisions = [
        decision for decision in decision_rows if _decision_is_open(decision)
    ]
    critical_decisions = [
        decision
        for decision in open_decisions
        if int(_number(decision.get("priority_score"), 0)) >= 85
    ]

    procurement_actions = list(procurement.get("recommendations") or [])
    urgent_procurement = [
        item
        for item in procurement_actions
        if int(_number(item.get("Priority Score"), 0)) >= 75
    ]

    actions: List[Dict[str, Any]] = []
    for decision in open_decisions:
        actions.append(
            {
                "source": "Engineering Decision",
                "priority": int(
                    _number(decision.get("priority_score"), 0)
                ),
                "owner": _text(
                    decision.get("assigned_owner")
                    or decision.get("owner"),
                    "Engineering",
                ),
                "action": _text(
                    decision.get("title")
                    or decision.get("recommended_action"),
                    "Review engineering decision",
                ),
                "due": _text(decision.get("due_date"), "This week"),
                "part": _text(decision.get("part_number"), "BOM"),
                "decision_id": _text(decision.get("decision_id")),
                "analysis_id": _text(decision.get("analysis_id")),
                "page": "Engineering Decisions",
            }
        )

    for item in procurement_actions:
        score = int(_number(item.get("Priority Score"), 0))
        if score < 45:
            continue
        actions.append(
            {
                "source": "Procurement",
                "priority": score,
                "owner": _text(item.get("Owner"), "Procurement"),
                "action": _text(
                    item.get("Recommended Action"),
                    item.get("Recommendation"),
                ),
                "due": _text(item.get("Urgency"), "This week"),
                "part": _text(item.get("Part Number"), "Component"),
                "decision_id": "",
                "analysis_id": "",
                "page": "Procurement Advisor",
            }
        )

    actions.sort(key=lambda item: item["priority"], reverse=True)
    top_actions = actions[:7]

    workload = {
        "Engineering": 0,
        "Procurement": 0,
        "Quality": 0,
        "Management": 0,
    }
    workload_hours = {
        "Engineering": 0,
        "Procurement": 0,
        "Quality": 0,
        "Management": 0,
    }
    for decision in open_decisions:
        group = _owner_group(
            decision.get("assigned_owner") or decision.get("owner")
        )
        workload[group] += 1
        workload_hours[group] += int(
            _number(decision.get("estimated_effort_hours"), 0)
        )
    for item in urgent_procurement:
        group = _owner_group(item.get("Owner"))
        workload[group] += 1

    lifecycle_changes = sum(
        1
        for row in alert_rows
        if "lifecycle" in _text(row.get("alert_type")).lower()
        or "lifecycle" in _text(row.get("alert_message")).lower()
    )
    stock_changes = sum(
        1
        for row in alert_rows
        if "stock" in _text(row.get("alert_type")).lower()
        or "stock" in _text(row.get("alert_message")).lower()
    )
    price_changes = sum(
        1
        for row in alert_rows
        if "price" in _text(row.get("alert_type")).lower()
        or "price" in _text(row.get("alert_message")).lower()
    )

    recent_activity: List[Dict[str, Any]] = []
    for row in alert_rows[:8]:
        recent_activity.append(
            {
                "type": "Monitoring alert",
                "title": _text(
                    row.get("part_number"),
                    "Component update",
                ),
                "detail": _text(
                    row.get("alert_message"),
                    "Monitoring change detected",
                ),
                "time": _text(row.get("created_at"), "Unknown"),
            }
        )
    for decision in decision_rows[:5]:
        recent_activity.append(
            {
                "type": "Engineering decision",
                "title": _text(
                    decision.get("part_number"),
                    "Decision update",
                ),
                "detail": (
                    f"{_text(decision.get('status'), 'New')} — "
                    f"{_text(decision.get('title'), 'Engineering review')}"
                ),
                "time": _text(
                    decision.get("updated_at")
                    or decision.get("detected_at"),
                    "Unknown",
                ),
            }
        )
    recent_activity = recent_activity[:10]

    production_ready = sum(
        1 for project in projects if project["readiness"] == "Production Ready"
    )
    critical_components = sum(project["high_risk"] for project in projects)
    estimated_hours = sum(
        int(_number(decision.get("estimated_effort_hours"), 0))
        for decision in open_decisions
    )

    average_health = (
        round(sum(project["health"] for project in projects) / len(projects))
        if projects
        else 0
    )
    projected_gain = min(
        15,
        sum(
            int(_number(decision.get("health_gain"), 0))
            for decision in open_decisions[:5]
        ),
    )
    projected_health = min(100, average_health + projected_gain)

    if critical_decisions or urgent_procurement:
        posture = "Action Required Today"
        tone = "bad"
        executive_summary = (
            f"Cadivor found {len(critical_decisions)} critical engineering "
            f"decision(s) and {len(urgent_procurement)} urgent procurement "
            "action(s). Address the highest-ranked lifecycle and supply risks "
            "before production approval."
        )
    elif open_decisions or alert_rows:
        posture = "Focused Review Recommended"
        tone = "warn"
        executive_summary = (
            f"{len(open_decisions)} engineering decision(s) and "
            f"{len(alert_rows)} monitoring alert(s) remain open. "
            "No immediate production blocker dominates, but ownership and "
            "deadlines should be confirmed."
        )
    else:
        posture = "Workspace Healthy"
        tone = "good"
        executive_summary = (
            "No urgent engineering or procurement exception is recorded. "
            "Continue routine monitoring and release-readiness review."
        )

    recommendations: List[str] = []
    if critical_decisions:
        recommendations.append(
            "Resolve the highest-priority engineering decision before the next release gate."
        )
    if urgent_procurement:
        recommendations.append(
            "Secure critical inventory or approve an alternate source before purchasing coverage closes."
        )
    if lifecycle_changes:
        recommendations.append(
            f"Review {lifecycle_changes} lifecycle change(s) and confirm replacement readiness."
        )
    single_source = int(procurement.get("second_source_count") or 0)
    if single_source:
        recommendations.append(
            f"Qualify additional sourcing coverage for {single_source} single-source component(s)."
        )
    if not recommendations:
        recommendations.append(
            "Continue controlled monitoring and review the workspace again after the next supplier-data refresh."
        )

    return {
        "greeting_name": _text(user_name, "there").split()[0],
        "posture": posture,
        "tone": tone,
        "executive_summary": executive_summary,
        "active_projects": len(projects),
        "production_ready": production_ready,
        "critical_components": critical_components,
        "procurement_actions": len(urgent_procurement),
        "engineering_decisions": len(open_decisions),
        "estimated_hours": estimated_hours,
        "parts_tracked": len(part_rows),
        "average_health": average_health,
        "projected_health": projected_health,
        "projects": projects,
        "top_actions": top_actions,
        "workload": workload,
        "workload_hours": workload_hours,
        "risk_radar": {
            "Lifecycle Changes": lifecycle_changes,
            "Stock Changes": stock_changes,
            "Price Changes": price_changes,
            "Monitoring Alerts": len(alert_rows),
            "Critical Decisions": len(critical_decisions),
        },
        "recent_activity": recent_activity,
        "recommendations": recommendations,
    }

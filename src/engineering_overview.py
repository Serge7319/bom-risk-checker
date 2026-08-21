"""Milestone 15.1 — simplified Engineering Overview intelligence."""
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

def build_engineering_overview(*, analyses, parts, alerts, decisions, procurement):
    analyses = list(analyses or [])
    alerts = list(alerts or [])
    decisions = list(decisions or [])
    open_decisions = [d for d in decisions if _t(d.get("status"), "New") not in ("Closed", "Rejected")]
    projects = []
    for row in analyses:
        health = int(_n(row.get("health_score"), 0))
        high = int(_n(row.get("high_risk_count") or row.get("high_risk_parts"), 0))
        projects.append({
            "id": _t(row.get("id")),
            "name": _t(row.get("project_name") or row.get("name") or row.get("filename"), "Saved BOM"),
            "health": health,
            "high": high,
            "parts": int(_n(row.get("total_parts") or row.get("part_count") or row.get("parts_count"), 0)),
            "status": "Ready for Production" if health >= 90 and high == 0 else "Needs Review",
        })
    projects.sort(key=lambda x: (x["status"] == "Ready for Production", x["health"]))

    actions = []
    for d in open_decisions:
        actions.append({
            "priority": int(_n(d.get("priority_score"), 0)),
            "title": _t(d.get("title") or d.get("recommended_action"), "Review engineering decision"),
            "item": _t(d.get("part_number"), "BOM"),
            "owner": _t(d.get("assigned_owner") or d.get("owner"), "Engineering"),
            "due": _t(d.get("due_date"), "This week"),
            "decision_id": _t(d.get("decision_id")),
            "analysis_id": _t(d.get("analysis_id")),
            "page": "Engineering Decisions",
        })
    for p in procurement.get("recommendations", []):
        if int(p.get("Priority Score", 0)) >= 55:
            actions.append({
                "priority": int(p["Priority Score"]),
                "title": p["Next Step"],
                "item": p["Part Number"],
                "owner": "Procurement",
                "due": "Today" if p["Priority Score"] >= 75 else "This week",
                "decision_id": "",
                "analysis_id": "",
                "page": "Procurement Advisor",
            })
    actions.sort(key=lambda x: -x["priority"])

    action_today = [
        action for action in actions
        if "today" in action["due"].lower()
        or "24 hour" in action["due"].lower()
        or action["priority"] >= 85
    ]
    action_this_week = [
        action for action in actions
        if action not in action_today
        and (
            "week" in action["due"].lower()
            or "production approval" in action["due"].lower()
            or action["priority"] >= 60
        )
    ]
    action_later = [
        action for action in actions
        if action not in action_today and action not in action_this_week
    ]

    lifecycle = sum(1 for a in alerts if "lifecycle" in (_t(a.get("alert_type")) + _t(a.get("alert_message"))).lower())
    stock = sum(1 for a in alerts if "stock" in (_t(a.get("alert_type")) + _t(a.get("alert_message"))).lower())
    price = sum(1 for a in alerts if "price" in (_t(a.get("alert_type")) + _t(a.get("alert_message"))).lower())
    recently_changed_components = len({
        _t(a.get("part_number") or a.get("mpn"))
        for a in alerts[:20]
        if _t(a.get("part_number") or a.get("mpn"))
    })

    recommendations = []
    if actions:
        recommendations.append(actions[0]["title"])
    if lifecycle:
        recommendations.append(
            f"Review {lifecycle} lifecycle "
            f"{'change' if lifecycle == 1 else 'changes'} and confirm replacement readiness."
        )
    if procurement.get("second_source_count"):
        second_source_count = procurement["second_source_count"]
        recommendations.append(
            f"Add sourcing coverage for {second_source_count} single-source "
            f"{'component' if second_source_count == 1 else 'components'}."
        )
    if not recommendations:
        recommendations.append("Continue routine monitoring; no urgent exception is recorded.")

    return {
        "projects": projects,
        "top_actions": actions[:5],
        "all_actions": actions,
        "action_today": action_today,
        "action_this_week": action_this_week,
        "action_later": action_later,
        "recommendations": recommendations[:3],
        "recent_alerts": alerts[:5],
        "recent_change_summary": {
            "components": recently_changed_components,
            "lifecycle": lifecycle,
            "stock": stock,
            "price": price,
        },
        "active_projects": len(projects),
        "ready_projects": sum(1 for p in projects if p["status"] == "Ready for Production"),
        "critical_components": sum(p["high"] for p in projects),
        "procurement_actions": procurement.get("urgent_count", 0),
        "engineering_decisions": len(open_decisions),
        "estimated_hours": sum(int(_n(d.get("estimated_effort_hours"), 0)) for d in open_decisions),
        "summary": (
            f"{len(actions)} {'action needs' if len(actions) == 1 else 'actions need'} "
            "attention across engineering and procurement. "
            f"{sum(1 for p in projects if p['status'] != 'Ready for Production')} "
            f"{'project still needs' if sum(1 for p in projects if p['status'] != 'Ready for Production') == 1 else 'projects still need'} review."
        ),
    }

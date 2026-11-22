"""Milestone 15.1 — simplified Engineering Overview intelligence."""
from __future__ import annotations
from typing import Any, Dict, Iterable
import pandas as pd
from src.risk_engine import calculate_risk

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
    parts = list(parts or [])
    alerts = list(alerts or [])
    decisions = list(decisions or [])
    open_decisions = [d for d in decisions if _t(d.get("status"), "New") not in ("Closed", "Rejected")]
    projects = []
    for row in analyses:
        analysis_id = _t(row.get("id"))
        linked = [p for p in parts if _t(p.get("analysis_id")) == analysis_id]
        assessments = [calculate_risk(p) for p in linked]
        high = sum(result.get("risk_level") == "High" for result in assessments)
        needs_verification = sum(result.get("risk_level") == "Needs verification" for result in assessments)
        health = None
        if assessments and not needs_verification and all(result.get("risk_score") is not None for result in assessments):
            health = round(100 - sum(float(result["risk_score"]) for result in assessments) / len(assessments))
        status = (
            "Needs verification" if not linked or needs_verification
            else "Verified risk signal" if high
            else "Engineering review required"
        )
        projects.append({
            "id": analysis_id,
            "name": _t(row.get("project_name") or row.get("name") or row.get("filename"), "Saved BOM"),
            "health": health,
            "high": high,
            "needs_verification": needs_verification,
            "parts": len(linked),
            "status": status,
        })
    projects.sort(key=lambda x: (
        x["status"] == "Verified risk signal",
        x["health"] if x["health"] is not None else -1,
    ))
    production_approved_analysis_ids = [
        _t(row.get("id")) for row in analyses
        if _t(row.get("release_status") or row.get("approval_status")).casefold() == "production approved"
    ]

    actions = []
    for d in open_decisions:
        actions.append({
            "priority": int(_n(d.get("priority_score"), 0)),
            "title": _t(d.get("title") or d.get("recommended_action"), "Review engineering decision"),
            "item": _t(d.get("part_number"), "BOM"),
            "owner": _t(d.get("assigned_owner") or d.get("owner"), "Engineering"),
            "due": _t(d.get("due_date"), "Not scheduled"),
            "decision_id": _t(d.get("decision_id")),
            "analysis_id": _t(d.get("analysis_id")),
            "page": "Engineering Decisions",
        })
    for p in procurement.get("recommendations", []):
        if int(p.get("Priority Score", 0) or 0) >= 55:
            actions.append({
                "priority": int(p["Priority Score"]),
                "title": p["Next Step"],
                "item": p["Part Number"],
                "owner": "Procurement",
                "due": _t(p.get("Urgency"), "Not scheduled"),
                "decision_id": "",
                "analysis_id": "",
                "page": "Procurement Advisor",
            })
    actions.sort(key=lambda x: -x["priority"])

    high_priority = [
        action for action in actions
        if action["priority"] >= 75
    ]
    medium_priority = [
        action for action in actions
        if 45 <= action["priority"] < 75
    ]
    lower_priority = [
        action for action in actions
        if action["priority"] < 45
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
        "action_today": high_priority,  # legacy key; this is a triage bucket, not a due-today list
        "action_this_week": medium_priority,
        "action_later": lower_priority,
        "high_priority_actions": high_priority,
        "medium_priority_actions": medium_priority,
        "lower_priority_actions": lower_priority,
        "recommendations": recommendations[:3],
        "recent_alerts": alerts[:5],
        "recent_change_summary": {
            "components": recently_changed_components,
            "lifecycle": lifecycle,
            "stock": stock,
            "price": price,
        },
        "active_projects": len(projects),
        "ready_projects": 0,
        "production_approved_projects": len(production_approved_analysis_ids),
        "production_approved_analysis_ids": production_approved_analysis_ids,
        "critical_components": sum(p["high"] for p in projects),
        "procurement_actions": procurement.get("urgent_count", 0),
        "engineering_decisions": len(open_decisions),
        "estimated_hours": (
            sum(float(d["estimated_effort_hours"]) for d in open_decisions if d.get("estimated_effort_hours") is not None)
            if any(d.get("estimated_effort_hours") is not None for d in open_decisions)
            else None
        ),
        "summary": (
            f"{len(actions)} {'review item is' if len(actions) == 1 else 'review items are'} "
            "ranked across engineering and procurement. Priority scores order the queue; they do not set due dates or approve release."
        ),
    }

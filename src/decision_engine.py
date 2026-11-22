"""Cadivor Milestone 13.1 — Decision workflow and management intelligence."""
from __future__ import annotations

from hashlib import sha1
from typing import Any, Dict, Iterable, List

from src.normalizer import normalize_part_number

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
    if result.casefold() in {"nan", "none", "<na>"}:
        return default
    return result or default


def decision_target_type(decision: Dict[str, Any]) -> str:
    """Return the engineering object this decision is asking a user to review.

    Older records overloaded ``part_number`` with a project/BOM title for
    analysis-level decisions.  Keep that data readable while exposing an
    explicit scope for new renderers and navigation guards.
    """
    raw = _text(decision.get("target_type")).lower()
    if raw in {"component", "bom"}:
        return raw
    source = _text(decision.get("source")).lower()
    return "bom" if source == "bom analysis" else "component"


def decision_target_label(decision: Dict[str, Any]) -> str:
    """Return the primary human-readable target label for a decision."""
    target_type = decision_target_type(decision)
    if target_type == "bom":
        project_name = _text(decision.get("project_name"))
        bom_name = _text(decision.get("bom_name"))
        if project_name and bom_name and not project_name.casefold().endswith(bom_name.casefold()):
            return f"{project_name} · {bom_name}"
        return _text(
            decision.get("target_label")
            or decision.get("project_name")
            or decision.get("bom_name")
            or decision.get("part_number"),
            "Saved BOM",
        )
    return _text(
        decision.get("target_label")
        or decision.get("mpn")
        or decision.get("part_number"),
        "Component",
    )


def decision_target_context(decision: Dict[str, Any]) -> str:
    """Return the secondary context line shown below a decision target."""
    if decision_target_type(decision) == "bom":
        count = int(_number(decision.get("affected_component_count"), 0))
        descriptor = _text(
            decision.get("affected_component_descriptor"),
            "affected components",
        )
        if count:
            return f"BOM review · {count:,} {descriptor}"
        return "BOM review"

    project_name = _text(decision.get("project_name"))
    bom_name = _text(decision.get("bom_name"))
    source_filename = _text(decision.get("source_filename"))
    related_boms = decision.get("related_boms") or []
    if len(related_boms) > 1:
        return f"Component · In {len(related_boms):,} saved BOMs"
    if project_name and bom_name and not project_name.casefold().endswith(bom_name.casefold()):
        context = f"{project_name} · {bom_name}"
    else:
        context = project_name or bom_name or source_filename
    if context and related_boms:
        return f"Component · Appears in {context}"
    return f"Component · {context}" if context else "Component · No saved BOM linked"


def decision_target_cell(decision: Dict[str, Any]) -> str:
    """Keep component rows scannable; show saved BOM context when expanded."""
    label = decision_target_label(decision)
    if decision_target_type(decision) == "component":
        return label
    return f"{label}\n{decision_target_context(decision)}"


def partition_decision_queue(
    decisions: Iterable[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Separate part alerts from whole-BOM reviews without dropping either."""
    components: List[Dict[str, Any]] = []
    saved_boms: List[Dict[str, Any]] = []
    for decision in decisions:
        (components if decision_target_type(decision) == "component" else saved_boms).append(decision)
    return components, saved_boms


def _analysis_context_title(analysis: Dict[str, Any]) -> str:
    project = _text(analysis.get("project_name"))
    bom = _text(analysis.get("bom_name"))
    if project and bom and not project.casefold().endswith(bom.casefold()):
        return f"{project} · {bom}"
    return project or bom or _text(analysis.get("filename"), "Saved BOM")


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
    base = int(_number(decision.get("priority_score"), 0))
    return {"Queue triage score (not a risk estimate)": base}


def _confidence_reasons(decision: Dict[str, Any]) -> List[str]:
    evidence = decision.get("evidence") or []
    return [str(item) for item in evidence[:4]] or [
        "No evidence details are attached to this decision."
    ]


def enrich_decision(decision: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(decision)
    target_type = decision_target_type(enriched)
    enriched["target_type"] = target_type
    enriched.setdefault("target_label", decision_target_label(enriched))
    if target_type == "component":
        enriched.setdefault(
            "mpn",
            _text(enriched.get("part_number"), ""),
        )
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
    part = _text(alert.get("part_number")) or _text(alert.get("mpn"), "Component")
    alert_type = _text(alert.get("alert_type"), "Monitoring change")
    message = _text(alert.get("alert_message"), "Monitoring change detected")
    severity = _text(alert.get("severity"), "Medium").title()
    current_value = _text(alert.get("current_value"), "Not recorded")
    detected_at = _text(alert.get("created_at"), "Unknown")
    text = f"{alert_type} {message}".lower()

    # Priority is a queue ordering signal derived from the recorded alert
    # severity. It is not a probability, predicted outcome, or new supplier check.
    score = _severity_rank(severity) * 20
    owner = "Engineering"
    supporting_team = "Supply Chain"
    action = f"Review monitoring change for {part}"
    decision_type = "Monitoring Review"

    if "stock" in text:
        owner = "Procurement"
        supporting_team = "Supply Chain"
        decision_type = "Supply Decision"
        action = f"Review the recorded inventory alert for {part}"

    if "lifecycle" in text:
        owner = "Component Engineering"
        supporting_team = "Electrical Engineering"
        decision_type = "Lifecycle Decision"
        action = f"Verify the recorded lifecycle alert for {part}"

    if "price" in text:
        owner = "Procurement"
        supporting_team = "Finance"
        decision_type = "Cost Decision"
        action = f"Review the recorded price alert for {part}"

    score = min(100, score)
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
        "mpn": part,
        "target_type": "component",
        "target_label": part,
        "decision_type": decision_type,
        "title": action,
        "reason": message,
        "evidence": [
            f"Alert type: {alert_type}",
            f"Severity: {severity}",
            f"Previous value: {_text(alert.get('previous_value'), 'Unknown')}",
            f"Value recorded at alert time: {current_value}",
            f"Alert timestamp: {detected_at}",
        ],
        "owner": owner,
        "supporting_team": supporting_team,
        "due_date": None,
        "estimated_effort_hours": None,
        "priority_score": score,
        "priority": priority,
        "priority_basis": "Recorded alert severity; manual triage required.",
        "confidence": None,
        "recommended_action": action,
        "expected_impact": "Outcome not quantified. Recheck and record supplier evidence after the review action.",
        "current_health": None,
        "projected_health": None,
        "health_gain": None,
        "supply_risk_reduction": None,
        "lifecycle_exposure_reduction": None,
        "estimated_cost_impact": None,
        "detected_at": detected_at,
    }


def monitoring_decision_id(alert: Dict[str, Any]) -> str:
    """Return the same stable key used by the decision center for an alert."""
    return _alert_decision(alert)["decision_id"]


def _analysis_decisions(
    analysis: Dict[str, Any],
    part_links: Iterable[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    from src.risk_engine import calculate_risk

    analysis_id = _text(analysis.get("id"))
    project = _text(
        analysis.get("project_name") or analysis.get("name"),
        "Saved BOM",
    )
    created = _text(analysis.get("created_at"), "Unknown")
    bom_name = _text(analysis.get("bom_name") or analysis.get("bom"))
    linked_rows = [
        dict(row) for row in (part_links or [])
        if isinstance(row, dict)
        and _text(row.get("analysis_id")) == analysis_id
    ]
    if not linked_rows:
        # Saved aggregate counts can be stale. Without the component evidence
        # rows, there is no current assessment from which to generate a BOM decision.
        return []
    assessed = [(row, calculate_risk(row)) for row in linked_rows]
    high_rows = [(row, result) for row, result in assessed if result.get("risk_level") == "High"]
    medium_rows = [(row, result) for row, result in assessed if result.get("risk_level") == "Medium"]
    unknown_rows = [(row, result) for row, result in assessed if result.get("risk_level") == "Needs verification"]
    if high_rows:
        selected, descriptor, title_prefix, queue_prefix, owner, team = (
            high_rows, "high-risk components", "Resolve high-risk components", "Resolve", "Engineering Manager", "Component Engineering"
        )
        decision_type = "Engineering Review"
        action = "Review the verified component risk findings and record approved mitigations."
        base_score = 80
    elif medium_rows:
        selected, descriptor, title_prefix, queue_prefix, owner, team = (
            medium_rows, "medium-risk components", "Review supplier risk signals", "Review", "Component Engineering", "Procurement"
        )
        decision_type = "Engineering Review"
        action = "Review verified lifecycle, inventory, and supplier-coverage findings."
        base_score = 55
    elif unknown_rows:
        selected, descriptor, title_prefix, queue_prefix, owner, team = (
            unknown_rows, "components needing verification", "Verify supplier evidence", "Verify", "Procurement", "Component Engineering"
        )
        decision_type = "Evidence Review"
        action = "Refresh supplier lookups and review exact-part identity, lifecycle, inventory, and coverage evidence."
        base_score = 40
    else:
        return []

    count = len(selected)
    score = max(
        base_score,
        max((int(_number(result.get("risk_score"), 0)) for _, result in selected), default=0),
    )
    evidence = [
        f"{_text(row.get('mpn') or row.get('part_number'), 'Component')}: "
        f"{_text(result.get('risk_level'), 'Needs verification')} — "
        f"{'; '.join(result.get('risk_reasons') or ['No complete assessment evidence.'])}"
        for row, result in selected[:12]
    ]
    evidence.extend([
        f"Components in linked analysis: {len(linked_rows)}",
        f"Analysis saved: {created}",
    ])
    return [{
        "decision_id": _stable_id(analysis_id, f"{decision_type.casefold()}-{descriptor}"),
        "source": "BOM Analysis",
        "analysis_id": analysis_id,
        "part_number": project,
        "project_name": project,
        "bom_name": bom_name,
        "target_type": "bom",
        "target_label": project,
        "affected_component_count": count,
        "affected_component_descriptor": descriptor,
        "decision_type": decision_type,
        "title": f"{title_prefix} in {project}",
        "queue_title": f"{queue_prefix} {count} {descriptor}",
        "reason": f"{count} linked component(s) have a {descriptor} finding in the saved evidence.",
        "evidence": evidence,
        "owner": owner,
        "supporting_team": team,
        "due_date": None,
        "estimated_effort_hours": None,
        "priority_score": min(100, score),
        "priority": "Critical" if score >= 85 else "High" if score >= 65 else "Medium" if score >= 45 else "Review",
        "priority_basis": "Triage ordering from recomputed component risk levels; not a probability or release gate.",
        "confidence": None,
        "recommended_action": action,
        "expected_impact": "Outcome not quantified. Recalculate supplier evidence after the review action is complete.",
        "current_health": None,
        "projected_health": None,
        "health_gain": None,
        "supply_risk_reduction": None,
        "lifecycle_exposure_reduction": None,
        "estimated_cost_impact": None,
        "detected_at": created,
    }]


def build_decision_center(
    *,
    alert_df: pd.DataFrame,
    analyses: Iterable[Dict[str, Any]],
    saved_state: Dict[str, Dict[str, Any]] | None = None,
    part_links: Iterable[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    state = saved_state or {}
    decisions: List[Dict[str, Any]] = []
    analysis_rows = list(analyses or [])
    linked_part_rows = list(part_links or [])
    analyses_by_id = {
        _text(analysis.get("id")): analysis
        for analysis in analysis_rows
        if _text(analysis.get("id"))
    }
    # Older monitoring alerts have no analysis_id. Resolve their MPN against
    # saved BOM parts, but never claim one BOM owns an alert when several do.
    part_analysis_ids: Dict[str, set[str]] = {}
    for link in linked_part_rows:
        mpn = normalize_part_number(_text(link.get("mpn")))
        analysis_id = _text(link.get("analysis_id"))
        if mpn and analysis_id in analyses_by_id:
            part_analysis_ids.setdefault(mpn, set()).add(analysis_id)

    if isinstance(alert_df, pd.DataFrame) and not alert_df.empty:
        for row in alert_df.to_dict("records"):
            decision = _alert_decision(row)
            requested_analysis_id = _text(decision.get("analysis_id"))
            related_analysis = analyses_by_id.get(requested_analysis_id)
            # Monitoring rows can outlive their saved BOM (or its workspace
            # membership). Do not expose a deep link unless that analysis is
            # available to the current decision workspace; infer a fresh,
            # scoped link from the component rows below when possible.
            if requested_analysis_id and related_analysis is None:
                decision["analysis_id"] = ""
            if not related_analysis:
                related_ids = part_analysis_ids.get(
                    normalize_part_number(_text(decision.get("mpn"))), set()
                )
                related_boms = [
                    {
                        "id": analysis_id,
                        "name": _analysis_context_title(analyses_by_id[analysis_id]),
                    }
                    for analysis_id in related_ids
                ]
                related_boms.sort(key=lambda bom: (bom["name"].casefold(), bom["id"]))
                if related_boms:
                    decision["related_boms"] = related_boms
                if len(related_boms) == 1:
                    related_analysis = analyses_by_id[related_boms[0]["id"]]
                    decision["context_analysis_id"] = related_boms[0]["id"]
            if related_analysis:
                decision["project_name"] = _text(
                    related_analysis.get("project_name")
                    or related_analysis.get("name"),
                    "",
                )
                decision["bom_name"] = _text(
                    related_analysis.get("bom_name")
                    or related_analysis.get("bom"),
                )
                decision["source_filename"] = _text(
                    related_analysis.get("filename")
                )
            decisions.append(decision)

    for analysis in analysis_rows:
        decisions.extend(_analysis_decisions(analysis, linked_part_rows))

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
        saved_payload = saved.get("decision_payload")
        if isinstance(saved_payload, dict):
            for key in (
                "resolution",
                "approved_alternative_mpn",
                "approved_alternative_record_id",
                "approved_alternative_analysis_id",
                "context_analysis_id",
                "inventory_evidence",
                "source_evidence",
            ):
                if saved_payload.get(key):
                    decision[key] = saved_payload[key]
        if (
            str(decision.get("source") or "").casefold() == "monitoring"
            and decision_target_type(decision) == "component"
        ):
            # Decision payloads are durable and may refer to a BOM that was
            # later deleted or moved out of the active workspace. Validate
            # both direct and saved context IDs after applying persisted state.
            direct_analysis_id = _text(decision.get("analysis_id"))
            if direct_analysis_id not in analyses_by_id:
                decision["analysis_id"] = ""
                direct_analysis_id = ""
            if direct_analysis_id:
                decision.pop("context_analysis_id", None)
            else:
                related_ids = part_analysis_ids.get(
                    normalize_part_number(_text(decision.get("mpn"))), set()
                )
                related_boms = [
                    {
                        "id": analysis_id,
                        "name": _analysis_context_title(analyses_by_id[analysis_id]),
                    }
                    for analysis_id in related_ids
                    if analysis_id in analyses_by_id
                ]
                related_boms.sort(key=lambda bom: (bom["name"].casefold(), bom["id"]))
                if related_boms:
                    decision["related_boms"] = related_boms
                    valid_context_ids = {bom["id"] for bom in related_boms}
                    saved_context_id = _text(decision.get("context_analysis_id"))
                    if saved_context_id not in valid_context_ids:
                        saved_context_id = ""
                    if len(related_boms) == 1:
                        decision["context_analysis_id"] = related_boms[0]["id"]
                    elif saved_context_id:
                        decision["context_analysis_id"] = saved_context_id
                    else:
                        decision.pop("context_analysis_id", None)
                else:
                    decision.pop("related_boms", None)
                    decision.pop("context_analysis_id", None)
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
    def measured_values(rows: Iterable[Dict[str, Any]], field: str) -> List[float]:
        values = []
        for row in rows:
            if row.get(field) is None:
                continue
            parsed = _number(row.get(field), None)
            if parsed is not None:
                values.append(parsed)
        return values

    health_gains = measured_values(open_decisions[:10], "health_gain")
    risk_reductions = measured_values(open_decisions[:10], "supply_risk_reduction")
    effort_values = measured_values(open_decisions, "estimated_effort_hours")

    return {
        "decisions": final,
        "open_count": len(open_decisions),
        "critical_count": len(critical),
        "awaiting_approval_count": len(awaiting),
        "production_ready_count": len(production_ready),
        "closed_count": len(closed),
        "estimated_hours": sum(effort_values) if effort_values else None,
        "average_age_days": average_age,
        "projected_health_gain": sum(health_gains) if health_gains else None,
        "projected_risk_reduction": sum(risk_reductions) if risk_reductions else None,
    }

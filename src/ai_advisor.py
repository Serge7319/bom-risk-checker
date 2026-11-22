"""Evidence-led engineering actions derived from saved BOM supplier records.

This module intentionally does not estimate confidence, engineering effort,
release readiness, or the benefit of a proposed action. Those require validated
engineering and commercial inputs that are not present in a supplier snapshot.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Mapping

from apps.api.evidence_contract import EVIDENCE_LIVE, classify_part_evidence
from integrations.stock_coercion import parse_stock_total
from src.risk_engine import _coverage_complete, calculate_risk


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    result = str(value).strip()
    return result if result and result.casefold() not in {"nan", "none", "null", "nat"} else default


def _mpn(part: Mapping[str, Any]) -> str:
    return _text(
        part.get("MPN") or part.get("mpn") or part.get("manufacturer_part_number")
        or part.get("part_number"),
        "Unidentified component",
    )


def _live(field: Mapping[str, Any] | None) -> bool:
    return isinstance(field, Mapping) and field.get("evidence_class") == EVIDENCE_LIVE


def _numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _component_action(part: Dict[str, Any], assessment: Mapping[str, Any]) -> Dict[str, Any] | None:
    mpn = _mpn(part)
    envelope = classify_part_evidence(part)
    fields = envelope.get("fields") if isinstance(envelope.get("fields"), dict) else {}
    lifecycle = fields.get("lifecycle") if isinstance(fields.get("lifecycle"), dict) else {}
    stock = fields.get("stock") if isinstance(fields.get("stock"), dict) else {}
    identity = fields.get("identity") if isinstance(fields.get("identity"), dict) else {}
    lead = fields.get("lead_time") if isinstance(fields.get("lead_time"), dict) else {}
    coverage_complete, _ = _coverage_complete(part)
    risk_level = _text(assessment.get("risk_level"), "Needs verification")
    reasons = [str(value) for value in assessment.get("risk_reasons", []) if _text(value)]

    if risk_level == "Low":
        return None

    needs_verification = risk_level == "Needs verification"
    lifecycle_value = (
        _text(part.get("Lifecycle") or part.get("lifecycle_status") or part.get("Lifecycle Status"))
        if _live(lifecycle) else ""
    )
    lifecycle_problem = any(
        term in lifecycle_value.casefold()
        for term in ("obsolete", "end of life", "eol", "discontinued", "nrnd", "not recommended")
    )
    if needs_verification:
        title = f"Verify supplier evidence for {mpn}"
        recommendation = (
            "Refresh exact-part checks from the configured authorized suppliers and confirm the "
            "lifecycle, complete inventory, and supplier coverage records before relying on this analysis."
        )
        why = "; ".join(reasons) or "The saved record does not contain enough verified evidence to score this component."
        category = "Evidence verification"
        priority = "Needs verification"
        action_route = "evidence"
        schedule = "Before relying on this report"
    else:
        title = f"Review verified supplier risk for {mpn}"
        if lifecycle_problem:
            recommendation = (
                "Review the exact-part lifecycle record and begin replacement qualification if the "
                "manufacturer status is confirmed."
            )
            category = "Lifecycle"
            action_route = "alternative"
        else:
            recommendation = (
                "Review the cited exact-part supplier evidence and record a sourcing or engineering "
                "mitigation before the release decision."
            )
            category = "Sourcing and engineering review"
            action_route = "component"
        why = "; ".join(reasons) or "A verified risk signal is present in the saved supplier evidence."
        priority = risk_level
        schedule = "Before release decision"

    signal_rows = [
        ("Exact-part identity", identity, _text(identity.get("source"), "No verified supplier identity")),
        ("Lifecycle", lifecycle, lifecycle_value or "No verified lifecycle value"),
        ("Inventory", stock, _text(stock.get("reported_value"), "No complete exact-part inventory total")),
        ("Supplier coverage", identity, "Complete checks recorded" if coverage_complete else "Supplier checks incomplete"),
        ("Lead time", lead, _text(part.get("Lead Time Weeks") or part.get("lead_time_weeks"), "No verified lead time")),
    ]
    signals = [
        {
            "name": name,
            "available": _live(evidence) and (name != "Supplier coverage" or coverage_complete),
            "detail": detail,
        }
        for name, evidence, detail in signal_rows
    ]
    score = assessment.get("risk_score")
    return {
        "part_number": mpn,
        "title": title,
        "category": category,
        "recommendation": recommendation,
        "why": why,
        "if_ignored": (
            "This component remains unverified; do not interpret missing values as safe, available, or compliant."
            if needs_verification
            else "The verified supplier risk remains unresolved until an engineer or buyer records a mitigation."
        ),
        "owner": "Component Engineer",
        "support_owner": "Procurement Specialist",
        "effort": "Not estimated",
        "effort_hours": None,
        "business_priority": priority,
        "schedule": schedule,
        "priority_bucket": "Do Before Production",
        "score": score,
        "confidence": None,
        "signals": signals,
        "signal_count": sum(1 for signal in signals if signal["available"]),
        "confidence_breakdown": [
            {"label": name, "available": signal["available"]}
            for name, signal in zip((row[0] for row in signal_rows), signals)
        ],
        "action_route": action_route,
        "impacts": {},
        "improvement": {},
        "decision_impact": {},
        "inaction_consequences": [
            "Resolve evidence gaps or review the cited verified risk before approving the release decision."
        ],
        "tradeoffs": [],
        "engineering_reasoning": reasons,
        "dependencies": ["Refresh supplier evidence", "Review source records", "Record engineering disposition"],
        "cross_component_impact": [],
        "decision_timeline": [],
    }


def build_engineering_supply_advisor(
    *,
    analysis: Dict[str, Any],
    parts: Iterable[Dict[str, Any]],
    alerts: Iterable[Dict[str, Any]] | None = None,
    alternatives: Iterable[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Summarize verified signals without inventing projections or approvals."""
    rows = [dict(part) for part in (parts or []) if isinstance(part, dict)]
    alert_rows = list(alerts or [])
    alternative_rows = list(alternatives or [])

    assessed: list[tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]] = []
    for part in rows:
        envelope = classify_part_evidence(part)
        fields = envelope.get("fields") if isinstance(envelope.get("fields"), dict) else {}
        risk = calculate_risk(part)
        assessed.append((part, risk, fields))

    high = sum(risk.get("risk_level") == "High" for _, risk, _ in assessed)
    medium = sum(risk.get("risk_level") == "Medium" for _, risk, _ in assessed)
    low = sum(risk.get("risk_level") == "Low" for _, risk, _ in assessed)
    needs_verification = sum(risk.get("risk_level") == "Needs verification" for _, risk, _ in assessed)
    lifecycle_concerns = 0
    no_stock = 0
    limited_sources = 0
    long_lead = 0

    for part, risk, fields in assessed:
        lifecycle = fields.get("lifecycle") if isinstance(fields.get("lifecycle"), dict) else {}
        stock = fields.get("stock") if isinstance(fields.get("stock"), dict) else {}
        lead = fields.get("lead_time") if isinstance(fields.get("lead_time"), dict) else {}
        identity = fields.get("identity") if isinstance(fields.get("identity"), dict) else {}
        if _live(lifecycle):
            value = _text(part.get("Lifecycle") or part.get("lifecycle_status") or part.get("Lifecycle Status")).casefold()
            lifecycle_concerns += any(
                term in value for term in ("obsolete", "end of life", "eol", "discontinued", "nrnd", "not recommended")
            )
        stock_total = parse_stock_total(stock.get("observed_total", stock.get("reported_value")))
        if _live(stock) and stock.get("complete") and stock_total == 0:
            no_stock += 1
        coverage_complete, _ = _coverage_complete(part)
        supplier_count = _numeric(part.get("Supplier Count", part.get("supplier_count")))
        if _live(identity) and coverage_complete and supplier_count is not None and supplier_count <= 1:
            limited_sources += 1
        lead_value = _numeric(part.get("Lead Time Weeks", part.get("lead_time_weeks")))
        if _live(lead) and lead_value is not None and lead_value >= 12:
            long_lead += 1

    action_candidates = []
    for part, risk, _ in assessed:
        action = _component_action(part, risk)
        if action:
            action_candidates.append(action)
    action_candidates.sort(
        key=lambda row: (
            row["business_priority"] != "High",
            row["business_priority"] != "Medium",
            row["business_priority"] != "Needs verification",
            -(row["score"] if isinstance(row.get("score"), (int, float)) else -1),
        )
    )
    actions = action_candidates[:5]

    if needs_verification:
        readiness = "Needs supplier evidence verification"
        tone = "warn"
        readiness_reason = f"{needs_verification} component(s) do not have complete evidence for a clean assessment."
    elif high:
        readiness = "Verified high-risk signals require engineering review"
        tone = "bad"
        readiness_reason = f"{high} component(s) have verified high-risk signals."
    elif medium:
        readiness = "Engineering release review required"
        tone = "warn"
        readiness_reason = f"{medium} component(s) have verified medium-risk signals."
    else:
        readiness = "Supplier checks complete; engineering release review required"
        tone = "warn"
        readiness_reason = "Supplier and lifecycle checks do not approve electrical, mechanical, compliance, or production release."

    if not actions:
        actions = [{
            "part_number": "BOM",
            "title": "Review the completed supplier evidence",
            "category": "Engineering release review",
            "recommendation": "Review the source records and complete the organization’s engineering release process.",
            "why": "Cadivor reports supplier and lifecycle evidence; it does not certify design fit or approve production release.",
            "if_ignored": "An engineering review is still required before release.",
            "owner": "Component Engineer",
            "support_owner": "Quality and Procurement",
            "effort": "Not estimated",
            "effort_hours": None,
            "business_priority": "Review",
            "schedule": "Before release decision",
            "priority_bucket": "Do Before Production",
            "score": None,
            "confidence": None,
            "signals": [],
            "signal_count": 0,
            "confidence_breakdown": [],
            "action_route": "component",
            "impacts": {},
            "improvement": {},
            "decision_impact": {},
            "inaction_consequences": [],
            "tradeoffs": [],
            "engineering_reasoning": [],
            "dependencies": [],
            "cross_component_impact": [],
            "decision_timeline": [],
        }]

    summary = (
        f"{len(rows)} component(s): {high} verified high risk, {medium} verified medium risk, "
        f"{low} verified low risk, and {needs_verification} needing verification."
    )
    recommendation = (
        f"Review {needs_verification} evidence gap(s) and {high + medium} verified risk signal(s). "
        "Cadivor does not approve engineering or production release."
    )

    return {
        "production_readiness": readiness,
        "readiness_tone": tone,
        "readiness_reason": readiness_reason,
        "confidence": None,
        "engineering_exposure_score": None,
        "supply_exposure_score": None,
        "executive_readiness": {key: None for key in ("overall", "engineering", "supply_chain", "manufacturing", "procurement", "documentation")},
        "priority_actions": actions,
        "estimated_total_effort": None,
        "projected_health": None,
        "projected_supply_exposure": None,
        "executive_recommendation": recommendation,
        "engineering_summary": summary,
        "procurement_summary": (
            f"Verified signals: {no_stock} complete checks reported zero inventory, "
            f"{limited_sources} components had one or fewer exact sources after complete checks, "
            f"and {long_lead} had verified lead time of at least 12 weeks."
        ),
        "supply_chain_summary": (
            "Supplier API data represents a timestamped catalog snapshot, not checkout confirmation. "
            f"{len(alert_rows)} saved alert(s) and {len(alternative_rows)} alternative record(s) are available for review."
        ),
        "metrics": {
            "lifecycle_concerns": int(lifecycle_concerns),
            "no_stock": no_stock,
            "limited_sources": limited_sources,
            "long_lead": long_lead,
            "active_alerts": len(alert_rows),
            "saved_alternatives": len(alternative_rows),
            "high_risk_count": high,
            "medium_risk_count": medium,
            "low_risk_count": low,
            "needs_verification_count": needs_verification,
            "assessed_parts": len(rows),
        },
    }

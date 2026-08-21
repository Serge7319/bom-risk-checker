"""Cadivor Engineering Decision Intelligence — Sprint 66 v1 / Sprint 67 v2."""
from __future__ import annotations

from html import escape
from typing import Any, Dict, Iterable, List, Mapping, Optional

import pandas as pd

from src.ai_advisor import build_engineering_supply_advisor
from src.bom_intelligence import analyze_bom_intelligence
from src.engineering_dependency_engine import (
    attach_dependency_to_actions,
    build_engineering_dependency_report,
)
from src.ui.decision_workspace import render_recommendation_workspace
from src.config import ENABLE_DECISION_ENGINE_V2, ENABLE_DECISION_WORKSPACE_V71
from src.ui.cadivor_design_system.icons import lucide

INSUFFICIENT_EVIDENCE = "Insufficient evidence"

FINDING_RANK = {
    "production_blocker": 0,
    "lifecycle": 1,
    "single_source": 2,
    "inventory": 3,
    "lead_time": 4,
    "cost": 5,
    "informational": 6,
}

ACTION_CATEGORY_RANK = {
    "Lifecycle": 0,
    "Engineering": 1,
    "Sourcing": 2,
    "Procurement": 3,
    "Supply Chain": 4,
    "Monitoring": 5,
    "Engineering Review": 6,
}


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    text = str(value).strip()
    return text or default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except Exception:
        return default


def _mpn(part: Mapping[str, Any]) -> str:
    return _text(
        part.get("mpn")
        or part.get("MPN")
        or part.get("part_number")
        or part.get("manufacturer_part_number")
        or part.get("Manufacturer Part Number"),
        "Part number unavailable",
    )


def decision_brief_cache_key(*, analysis_id: Any = None, session_key: str = "") -> str:
    if analysis_id:
        return f"analysis_{analysis_id}"
    return f"session_{session_key or 'live'}"


def get_cached_decision_brief(cache_key: str) -> Optional[Dict[str, Any]]:
    try:
        import streamlit as st

        return st.session_state.get(f"cv67_decision_brief_{cache_key}")
    except Exception:
        return None


def cache_decision_brief(cache_key: str, brief: Mapping[str, Any]) -> None:
    try:
        import streamlit as st

        st.session_state[f"cv67_decision_brief_{cache_key}"] = dict(brief)
    except Exception:
        return


def parts_to_results_df(parts: Iterable[Dict[str, Any]]) -> pd.DataFrame:
    """Normalize saved analysis parts into a BOM results frame for intelligence reuse."""
    rows: List[Dict[str, Any]] = []
    for part in parts or []:
        rows.append(
            {
                "MPN": _mpn(part),
                "Manufacturer": _text(part.get("manufacturer") or part.get("Manufacturer")),
                "Lifecycle Status": _text(
                    part.get("lifecycle_status") or part.get("Lifecycle Status"),
                    "Unknown",
                ),
                "Stock Available": int(
                    _number(part.get("stock_available") or part.get("Stock Available"), 0)
                ),
                "Supplier Count": int(
                    _number(part.get("supplier_count") or part.get("Supplier Count"), 0)
                ),
                "Lead Time Weeks": _number(
                    part.get("lead_time_weeks") or part.get("Lead Time Weeks"), 0
                ),
                "Risk Level": _text(part.get("risk_level") or part.get("Risk Level"), "Low"),
                "Risk Score": int(_number(part.get("risk_score") or part.get("Risk Score"), 0)),
            }
        )
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _results_to_parts(results_df: pd.DataFrame) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for _, row in results_df.iterrows():
        part_number = _text(
            row.get("MPN")
            or row.get("mpn")
            or row.get("part_number")
            or row.get("Manufacturer Part Number"),
            "Part number unavailable",
        )
        rows.append(
            {
                "mpn": part_number,
                "MPN": part_number,
                "manufacturer": _text(row.get("Manufacturer")),
                "Manufacturer": _text(row.get("Manufacturer")),
                "lifecycle_status": _text(row.get("Lifecycle Status"), "Unknown"),
                "Lifecycle Status": _text(row.get("Lifecycle Status"), "Unknown"),
                "stock_available": int(_number(row.get("Stock Available"), 0)),
                "Stock Available": int(_number(row.get("Stock Available"), 0)),
                "supplier_count": int(_number(row.get("Supplier Count"), 0)),
                "Supplier Count": int(_number(row.get("Supplier Count"), 0)),
                "lead_time_weeks": _number(row.get("Lead Time Weeks"), 0),
                "Lead Time Weeks": _number(row.get("Lead Time Weeks"), 0),
                "risk_level": _text(row.get("Risk Level"), "Low"),
                "Risk Level": _text(row.get("Risk Level"), "Low"),
                "risk_score": int(_number(row.get("Risk Score"), 0)),
                "Risk Score": int(_number(row.get("Risk Score"), 0)),
            }
        )
    return rows


def _analysis_from_results(results_df: pd.DataFrame, *, health_score: int = 0) -> Dict[str, Any]:
    high = int((results_df["Risk Level"].astype(str).str.lower() == "high").sum()) if "Risk Level" in results_df else 0
    medium = int((results_df["Risk Level"].astype(str).str.lower() == "medium").sum()) if "Risk Level" in results_df else 0
    low = int((results_df["Risk Level"].astype(str).str.lower() == "low").sum()) if "Risk Level" in results_df else 0
    return {
        "health_score": health_score
        or max(0, 100 - int(results_df["Risk Score"].mean()) if "Risk Score" in results_df else 0),
        "high_risk_count": high,
        "medium_risk_count": medium,
        "low_risk_count": low,
        "total_parts": len(results_df),
    }


def _has_sufficient_evidence(
    part_rows: List[Dict[str, Any]],
    metrics: Mapping[str, Any],
    intelligence: Mapping[str, Any],
) -> bool:
    if not part_rows:
        return False
    recorded_signals = 0
    for part in part_rows:
        lifecycle = _text(part.get("lifecycle_status") or part.get("Lifecycle Status")).lower()
        stock = _number(part.get("stock_available") or part.get("Stock Available"), -1)
        suppliers = _number(part.get("supplier_count") or part.get("Supplier Count"), -1)
        risk_score = _number(part.get("risk_score") or part.get("Risk Score"), 0)
        if lifecycle and lifecycle != "unknown":
            recorded_signals += 1
        if stock >= 0:
            recorded_signals += 1
        if suppliers >= 0:
            recorded_signals += 1
        if risk_score > 0:
            recorded_signals += 1
    aggregate = any(
        _number(metrics.get(key), 0) > 0
        for key in ("lifecycle_concerns", "no_stock", "limited_sources", "long_lead", "active_alerts")
    )
    return recorded_signals >= 2 or aggregate or intelligence.get("bom_health_score") is not None


def _map_production_readiness(
    raw: str,
    *,
    health: int,
    high: int,
    blocking_actions: int,
) -> tuple[str, str]:
    """Sprint 66 labels — used when v2 flag is disabled."""
    lowered = _text(raw).lower()
    if blocking_actions >= 1 or high >= 3 or health < 55 or "needs action" in lowered:
        return "Not Recommended for Release", "bad"
    if high > 0 or "review" in lowered or "prototype" in lowered:
        return "Engineering Review Required", "warn"
    if "monitoring" in lowered or health >= 85:
        return "Ready for Production", "good"
    return "Ready with Conditions", "warn"


def _map_production_readiness_v2(
    *,
    advisor: Mapping[str, Any],
    health: int,
    high: int,
    blocking_actions: int,
    insufficient: bool,
) -> tuple[str, str, str]:
    if insufficient:
        return INSUFFICIENT_EVIDENCE, "warn", (
            "Component lifecycle, inventory, supplier, or risk records are incomplete."
        )
    readiness = _text(advisor.get("production_readiness")).lower()
    if blocking_actions >= 1 or high >= 3 or health < 50 or "needs action" in readiness:
        return (
            "Not Ready",
            "bad",
            _text(
                advisor.get("readiness_reason"),
                "Production blockers remain before release can be considered.",
            ),
        )
    if "prototype" in readiness or (high > 0 and health < 70):
        return (
            "Prototype Ready",
            "warn",
            _text(
                advisor.get("readiness_reason"),
                "Appropriate for prototype builds; production release requires additional mitigation.",
            ),
        )
    if high > 0 or health < 80 or "review" in readiness:
        return (
            "Pilot Ready",
            "warn",
            _text(
                advisor.get("readiness_reason"),
                "Pilot builds are feasible with focused engineering review on remaining risks.",
            ),
        )
    if health >= 85 and high == 0:
        return (
            "Production Ready",
            "good",
            _text(
                advisor.get("readiness_reason"),
                "No production blocker dominates the recorded evidence.",
            ),
        )
    return (
        "Pilot Ready",
        "warn",
        _text(advisor.get("readiness_reason"), "Controlled release with ongoing monitoring."),
    )


def _confidence_label(score: int) -> str:
    if score >= 82:
        return "High"
    if score >= 68:
        return "Medium"
    return "Low"


def _impact_summary(impacts: Mapping[str, Any] | None) -> str:
    if not impacts:
        return INSUFFICIENT_EVIDENCE
    top = sorted(impacts.items(), key=lambda item: _number(item[1], 0), reverse=True)
    if not top or _number(top[0][1], 0) <= 1:
        return "Low operational impact"
    label, level = top[0]
    return f"{label.title()} impact level {int(_number(level, 1))}/5"


def _format_decision_impact_summary(impact: Mapping[str, Any]) -> str:
    if not impact:
        return INSUFFICIENT_EVIDENCE
    health = impact.get("health") or {}
    supply = impact.get("supply_risk") or {}
    lifecycle = impact.get("lifecycle_risk") or {}
    single = impact.get("single_source_exposure") or {}
    lines = [
        f"Health {int(_number(health.get('before'), 0))} → {int(_number(health.get('after'), 0))}",
        f"Supply risk {int(_number(supply.get('before'), 0))} → {int(_number(supply.get('after'), 0))}",
        f"Lifecycle risk { _text(lifecycle.get('before')) } → { _text(lifecycle.get('after')) }",
        f"Single-source exposure {int(_number(single.get('before'), 0))} → {int(_number(single.get('after'), 0))}",
        f"Schedule improvement ~{int(_number(impact.get('schedule_improvement_weeks'), 0))} week(s)",
        f"Procurement effort ~{int(_number(impact.get('procurement_effort_hours'), 0))} hour(s)",
    ]
    return " · ".join(lines)


def _build_priority_matrix(actions: Iterable[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    matrix: Dict[str, List[Dict[str, Any]]] = {
        "Do Now": [],
        "Do This Week": [],
        "Do Before Production": [],
        "Can Wait": [],
    }
    for action in actions or []:
        bucket = _text(action.get("priority_bucket"), "Can Wait")
        if bucket not in matrix:
            bucket = "Can Wait"
        matrix[bucket].append(
            {
                "part_number": _text(action.get("part_number")),
                "title": _text(action.get("title")),
                "owner": _text(action.get("owner")),
                "effort": _text(action.get("effort")),
                "score": int(_number(action.get("score"), 0)),
            }
        )
    return matrix


def _build_brief_confidence_breakdown(
    *,
    advisor: Mapping[str, Any],
    metrics: Mapping[str, Any],
    actions: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    top_action = next(iter(actions or []), {})
    action_breakdown = list(top_action.get("confidence_breakdown") or [])
    if action_breakdown:
        return action_breakdown
    return [
        {"label": "Lifecycle data", "available": _number(metrics.get("lifecycle_concerns"), -1) >= 0},
        {"label": "Supplier data", "available": metrics.get("limited_sources") is not None},
        {"label": "Inventory data", "available": metrics.get("no_stock") is not None},
        {"label": "Cross-BOM history", "available": len(advisor.get("priority_actions") or []) > 0},
        {"label": "Saved alternative evidence", "available": _number(metrics.get("saved_alternatives"), 0) > 0},
        {"label": "Monitoring alerts", "available": _number(metrics.get("active_alerts"), 0) > 0},
        {"label": "Customer usage history", "available": False},
    ]


def _build_executive_summary_v2(
    *,
    readiness_label: str,
    insufficient: bool,
    top_finding: Mapping[str, Any] | None,
    advisor: Mapping[str, Any],
) -> str:
    if insufficient:
        return (
            f"{INSUFFICIENT_EVIDENCE} — Cadivor cannot produce a reliable engineering release "
            "recommendation because lifecycle, inventory, supplier, and risk records are incomplete."
        )
    if readiness_label == "Not Ready":
        lead = _text((top_finding or {}).get("detail"), "Critical production blockers remain.")
        return (
            "This BOM should not be released to production until lifecycle and sourcing risks are mitigated. "
            f"{lead}"
        )
    if readiness_label == "Prototype Ready":
        return (
            "This BOM is appropriate for prototype builds but should not be released to production until "
            "lifecycle and sourcing risks are mitigated. "
            + _text(
                (top_finding or {}).get("detail"),
                _text(advisor.get("readiness_reason")),
            )
        )
    if readiness_label == "Pilot Ready":
        return (
            "This BOM can support pilot builds with focused engineering review. "
            "Close remaining lifecycle, inventory, and supplier gaps before full production release. "
            + _text((top_finding or {}).get("detail"), "")
        ).strip()
    if readiness_label == "Production Ready":
        return (
            "This BOM meets recorded production readiness criteria with no dominant blocker. "
            "Continue controlled monitoring of lifecycle, inventory, and supplier signals. "
            + _text((top_finding or {}).get("detail"), "")
        ).strip()
    return _text(advisor.get("executive_recommendation"), INSUFFICIENT_EVIDENCE)


def _build_critical_findings(
    *,
    parts: Iterable[Dict[str, Any]],
    intelligence: Mapping[str, Any],
    metrics: Mapping[str, Any],
    insufficient: bool,
) -> List[Dict[str, str]]:
    if insufficient:
        return [
            {
                "category": INSUFFICIENT_EVIDENCE,
                "detail": "Lifecycle, inventory, supplier, or risk data is incomplete for this analysis.",
                "impact": "medium",
                "rank": "informational",
                "evidence": INSUFFICIENT_EVIDENCE,
            }
        ]

    findings: List[Dict[str, str]] = []
    part_rows = list(parts or [])

    obsolete = [
        p
        for p in part_rows
        if any(
            term in _text(p.get("Lifecycle Status") or p.get("lifecycle_status")).lower()
            for term in ("obsolete", "eol", "end of life")
        )
    ]
    for part in obsolete[:2]:
        mpn = _mpn(part)
        findings.append(
            {
                "category": "Production blocker",
                "detail": f"Obsolete/EOL status on {mpn} blocks unrestricted production release.",
                "impact": "high",
                "rank": "production_blocker",
                "evidence": f"Lifecycle: {_text(part.get('Lifecycle Status') or part.get('lifecycle_status'))}",
            }
        )

    nrnd = [
        p
        for p in part_rows
        if any(
            term in _text(p.get("Lifecycle Status") or p.get("lifecycle_status")).lower()
            for term in ("nrnd", "not recommended", "replacement")
        )
    ]
    for part in nrnd[:2]:
        mpn = _mpn(part)
        findings.append(
            {
                "category": "Lifecycle risk",
                "detail": f"High lifecycle risk on {mpn}.",
                "impact": "high",
                "rank": "lifecycle",
                "evidence": f"Lifecycle: {_text(part.get('Lifecycle Status') or part.get('lifecycle_status'))}",
            }
        )

    single_source = [
        p for p in part_rows if _number(p.get("Supplier Count") or p.get("supplier_count"), 0) <= 1
    ]
    for part in single_source[:2]:
        mpn = _mpn(part)
        findings.append(
            {
                "category": "Single-source exposure",
                "detail": f"Single-source supplier creates procurement risk for {mpn}.",
                "impact": "high",
                "rank": "single_source",
                "evidence": f"Supplier count: {int(_number(part.get('Supplier Count') or part.get('supplier_count'), 0))}",
            }
        )

    no_stock = [p for p in part_rows if _number(p.get("Stock Available") or p.get("stock_available"), 0) <= 0]
    for part in no_stock[:2]:
        mpn = _mpn(part)
        findings.append(
            {
                "category": "Inventory shortage",
                "detail": f"Inventory insufficient for production on {mpn}.",
                "impact": "high" if len(no_stock) >= 3 else "medium",
                "rank": "inventory",
                "evidence": f"Stock available: {int(_number(part.get('Stock Available') or part.get('stock_available'), 0))}",
            }
        )

    long_lead = [
        p for p in part_rows if _number(p.get("Lead Time Weeks") or p.get("lead_time_weeks"), 0) >= 12
    ]
    for part in long_lead[:2]:
        mpn = _mpn(part)
        weeks = _number(part.get("Lead Time Weeks") or part.get("lead_time_weeks"), 0)
        findings.append(
            {
                "category": "Schedule risk",
                "detail": f"Long lead time on {mpn} may delay production.",
                "impact": "medium",
                "rank": "lead_time",
                "evidence": f"Lead time: {weeks:g} weeks",
            }
        )

    alt_count = _number(metrics.get("saved_alternatives"), 0)
    if alt_count and single_source:
        sample = _mpn(single_source[0])
        findings.append(
            {
                "category": "Alternate available",
                "detail": f"Alternate evidence exists that may reduce exposure on {sample}.",
                "impact": "low",
                "rank": "informational",
                "evidence": f"{int(alt_count)} saved alternative record(s)",
            }
        )

    if metrics.get("active_alerts"):
        findings.append(
            {
                "category": "Monitoring alert",
                "detail": f"{metrics['active_alerts']} active monitoring alert(s) affect this BOM.",
                "impact": "medium",
                "rank": "informational",
                "evidence": f"Monitoring alerts: {metrics['active_alerts']}",
            }
        )

    high_risk = intelligence.get("risk_distribution", {}).get("High", 0)
    if high_risk and len(findings) < 3:
        findings.append(
            {
                "category": "High-risk components",
                "detail": f"{high_risk} component(s) exceed the high-risk threshold in the BOM risk engine.",
                "impact": "high",
                "rank": "production_blocker",
                "evidence": f"High-risk count: {high_risk}",
            }
        )

    findings.sort(
        key=lambda item: (
            FINDING_RANK.get(_text(item.get("rank"), "informational"), 9),
            {"high": 0, "medium": 1, "low": 2}.get(_text(item.get("impact"), "medium"), 9),
        )
    )
    return findings[:8] if findings else [
        {
            "category": "No critical blocker",
            "detail": "No prioritized engineering exception is currently recorded in available evidence.",
            "impact": "low",
            "rank": "informational",
            "evidence": "BOM risk engine and advisor signals agree.",
        }
    ]


def _format_recommended_action(action: Mapping[str, Any], *, insufficient: bool) -> Dict[str, Any]:
    signals = list(action.get("signals") or [])
    evidence_parts = [
        _text(signal.get("detail"))
        for signal in signals
        if signal.get("available") and _text(signal.get("detail"))
    ]
    evidence = "; ".join(evidence_parts) if evidence_parts else INSUFFICIENT_EVIDENCE
    improvement = action.get("improvement") or {}
    health_gain = _number(improvement.get("health_gain"), 0)
    supply_reduction = _number(improvement.get("supply_risk_reduction"), 0)
    decision_impact = action.get("decision_impact") or {}
    if insufficient or not evidence_parts:
        expected = INSUFFICIENT_EVIDENCE
    elif decision_impact:
        expected = _format_decision_impact_summary(decision_impact)
    elif health_gain or supply_reduction:
        expected = (
            f"Projected BOM health +{int(health_gain)} and supply exposure reduction of "
            f"approximately {int(supply_reduction)} points when completed."
        )
    else:
        expected = _text(action.get("if_ignored"), INSUFFICIENT_EVIDENCE)

    confidence_score = int(_number(action.get("confidence"), 0))
    return {
        "priority": _text(action.get("business_priority"), "Moderate"),
        "priority_bucket": _text(action.get("priority_bucket"), "Can Wait"),
        "action": _text(action.get("recommendation") or action.get("title"), INSUFFICIENT_EVIDENCE),
        "effort": _text(action.get("effort"), "—"),
        "impact": _impact_summary(action.get("impacts")),
        "owner": _text(action.get("owner"), "Component Engineering"),
        "reason": _text(action.get("why"), INSUFFICIENT_EVIDENCE),
        "evidence": evidence,
        "confidence": f"{confidence_score}%" if confidence_score else INSUFFICIENT_EVIDENCE,
        "expected_result": expected,
        "part_number": _text(action.get("part_number"), "—"),
        "title": _text(action.get("title"), "Engineering action"),
        "category": _text(action.get("category"), "Engineering Review"),
        "score": int(_number(action.get("score"), 0)),
        "decision_impact": decision_impact,
        "inaction_consequences": list(action.get("inaction_consequences") or []),
        "confidence_breakdown": list(action.get("confidence_breakdown") or []),
        "tradeoffs": list(action.get("tradeoffs") or []),
        "engineering_reasoning": list(action.get("engineering_reasoning") or []),
        "dependencies": list(action.get("dependencies") or []),
        "cross_component_impact": list(action.get("cross_component_impact") or []),
        "decision_timeline": list(action.get("decision_timeline") or []),
        "if_ignored": _text(action.get("if_ignored"), INSUFFICIENT_EVIDENCE),
    }


def _rank_recommended_actions(actions: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        list(actions),
        key=lambda action: (
            ACTION_CATEGORY_RANK.get(_text(action.get("category")), 9),
            -int(_number(action.get("score"), 0)),
        ),
    )


def _primary_recommendation(advisor: Mapping[str, Any], actions: List[Mapping[str, Any]]) -> str:
    if actions:
        top = actions[0]
        part = _text(top.get("part_number"), "the highest-risk component")
        rec = _text(top.get("recommendation") or top.get("action"), "Complete the prioritized engineering action.")
        return (
            f"Cadivor recommends addressing {part} first. {rec} "
            f"{_text(advisor.get('readiness_reason'))}"
        ).strip()
    return _text(
        advisor.get("executive_recommendation"),
        "Continue controlled monitoring while confirming lifecycle, inventory, and supplier evidence before release.",
    )


def _confidence_explanation(
    *,
    confidence: int,
    metrics: Mapping[str, Any],
    intelligence: Mapping[str, Any],
    insufficient: bool,
) -> str:
    if insufficient:
        return (
            f"{INSUFFICIENT_EVIDENCE} — confidence cannot be validated until lifecycle, inventory, "
            "supplier, and risk records are complete."
        )
    drivers: List[str] = []
    if metrics.get("saved_alternatives"):
        drivers.append(f"{metrics['saved_alternatives']} saved alternative record(s)")
    if metrics.get("active_alerts"):
        drivers.append(f"{metrics['active_alerts']} monitoring alert(s)")
    if intelligence.get("bom_health_score") is not None:
        drivers.append("BOM risk engine enrichment")
    if metrics.get("lifecycle_concerns"):
        drivers.append(f"{metrics['lifecycle_concerns']} lifecycle signal(s)")
    if metrics.get("no_stock") is not None and metrics.get("limited_sources") is not None:
        drivers.append("supplier, lifecycle, stock, and alternate data")
    if not drivers:
        drivers.append("component-level BOM health and risk scoring")
    return (
        f"Confidence is {_confidence_label(confidence)} ({confidence}%) because Cadivor synthesized "
        + ", ".join(drivers[:4])
        + "."
    )


def _build_business_impact(
    *,
    advisor: Mapping[str, Any],
    metrics: Mapping[str, Any],
    production_label: str,
    insufficient: bool,
) -> Dict[str, str]:
    if insufficient:
        blank = INSUFFICIENT_EVIDENCE
        return {
            "schedule": blank,
            "cost": blank,
            "manufacturing": blank,
            "procurement": blank,
            "supply_chain": blank,
        }
    long_lead = int(_number(metrics.get("long_lead"), 0))
    no_stock = int(_number(metrics.get("no_stock"), 0))
    return {
        "schedule": (
            f"{long_lead} long-lead component(s) may compress the production schedule."
            if long_lead
            else "No long-lead schedule pressure recorded in available evidence."
        ),
        "cost": (
            f"{no_stock} no-stock and {long_lead} long-lead component(s) may increase expedite "
            "or buffer inventory cost."
            if no_stock or long_lead
            else "No material cost escalation is indicated from current inventory and lead-time evidence."
        ),
        "manufacturing": (
            f"Production readiness is {production_label.lower()}. "
            f"{no_stock} no-stock component(s) may affect build continuity."
        ),
        "procurement": _text(advisor.get("procurement_summary"), INSUFFICIENT_EVIDENCE),
        "supply_chain": _text(advisor.get("supply_chain_summary"), INSUFFICIENT_EVIDENCE),
    }


def build_engineering_decision_brief(
    *,
    results_df: pd.DataFrame | None = None,
    analysis: Dict[str, Any] | None = None,
    parts: Iterable[Dict[str, Any]] | None = None,
    alerts: Iterable[Dict[str, Any]] | None = None,
    alternatives: Iterable[Dict[str, Any]] | None = None,
    health_score: int | None = None,
    advisor: Mapping[str, Any] | None = None,
    intelligence: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Synthesize an executive engineering decision from existing Cadivor intelligence."""
    intelligence_data: Dict[str, Any] = dict(intelligence or {})
    part_rows = list(parts or [])

    if results_df is not None and not results_df.empty:
        if not intelligence_data:
            from src.ui.performance_cache import cached_bom_intelligence

            analysis_key = (analysis or {}).get("id") or (analysis or {}).get("analysis_id") or "live"
            intelligence_data = cached_bom_intelligence(
                analysis_key,
                results_df,
                analyzer=analyze_bom_intelligence,
            )
        if not part_rows:
            part_rows = _results_to_parts(results_df)
        if analysis is None:
            analysis = _analysis_from_results(
                results_df,
                health_score=health_score or intelligence_data.get("bom_health_score", 0),
            )

    analysis = dict(analysis or {})
    if health_score is not None:
        analysis["health_score"] = health_score
    if not analysis.get("health_score") and intelligence_data:
        analysis["health_score"] = intelligence_data.get("bom_health_score", 0)

    if advisor is None:
        advisor = build_engineering_supply_advisor(
            analysis=analysis,
            parts=part_rows,
            alerts=alerts,
            alternatives=alternatives,
        )
    else:
        advisor = dict(advisor)

    health = int(_number(analysis.get("health_score"), intelligence_data.get("bom_health_score", 0)))
    high = int(_number(analysis.get("high_risk_count"), 0))
    metrics = advisor.get("metrics") or {}
    insufficient = not _has_sufficient_evidence(part_rows, metrics, intelligence_data)
    raw_actions = list(advisor.get("priority_actions") or [])
    blocking_actions = [action for action in raw_actions if _number(action.get("score"), 0) >= 80]

    if ENABLE_DECISION_ENGINE_V2:
        production_label, production_tone, production_explanation = _map_production_readiness_v2(
            advisor=advisor,
            health=health,
            high=high,
            blocking_actions=len(blocking_actions),
            insufficient=insufficient,
        )
    else:
        production_label, production_tone = _map_production_readiness(
            _text(advisor.get("production_readiness")),
            health=health,
            high=high,
            blocking_actions=len(blocking_actions),
        )
        production_explanation = _text(advisor.get("readiness_reason"))

    critical_findings = _build_critical_findings(
        parts=part_rows,
        intelligence=intelligence_data,
        metrics=metrics,
        insufficient=insufficient,
    )
    ranked_raw = _rank_recommended_actions(raw_actions)
    recommended_actions = [
        _format_recommended_action(action, insufficient=insufficient) for action in ranked_raw[:8]
    ]
    dependency_report = build_engineering_dependency_report(
        raw_actions=ranked_raw[:8],
        parts=part_rows,
        intelligence=intelligence_data,
        advisor=advisor,
    )
    recommended_actions = attach_dependency_to_actions(
        recommended_actions,
        dependency_report,
        raw_actions=ranked_raw[:8],
    )

    confidence = int(_number(advisor.get("confidence"), 70))
    business_impact = _build_business_impact(
        advisor=advisor,
        metrics=metrics,
        production_label=production_label,
        insufficient=insufficient,
    )

    if ENABLE_DECISION_ENGINE_V2:
        executive_summary = _build_executive_summary_v2(
            readiness_label=production_label,
            insufficient=insufficient,
            top_finding=critical_findings[0] if critical_findings else None,
            advisor=advisor,
        )
    else:
        executive_summary = _text(
            intelligence_data.get("executive_summary"),
            advisor.get("executive_recommendation"),
        )

    evidence = []
    if insufficient:
        evidence.append(INSUFFICIENT_EVIDENCE)
    # The saved analysis score is the report's canonical score.  Intelligence
    # can independently derive a score from enriched component data, but that
    # derived value must never contradict the score shown on the BOM, Dashboard,
    # or report header.
    evidence.append(f"BOM health score: {health}/100")
    if metrics.get("lifecycle_concerns"):
        evidence.append(f"Lifecycle signals on {metrics['lifecycle_concerns']} component(s)")
    if metrics.get("no_stock"):
        evidence.append(f"Inventory gap on {metrics['no_stock']} component(s)")
    if metrics.get("limited_sources"):
        evidence.append(f"Limited supplier coverage on {metrics['limited_sources']} component(s)")
    if metrics.get("saved_alternatives"):
        evidence.append(f"{metrics['saved_alternatives']} saved alternative record(s)")
    if metrics.get("active_alerts"):
        evidence.append(f"{metrics['active_alerts']} active monitoring alert(s)")
    if intelligence_data.get("recommendations"):
        evidence.append(f"{len(intelligence_data['recommendations'])} BOM risk engine recommendation(s)")

    lifecycle_impact = (
        f"{metrics.get('lifecycle_concerns', 0)} lifecycle concern(s) recorded. "
        f"{_text(intelligence_data.get('executive_summary') or advisor.get('engineering_summary'))}"
    ).strip()
    cost_impact = business_impact["cost"]
    executive_readiness = dict(advisor.get("executive_readiness") or {})
    if not executive_readiness:
        executive_readiness = {
            "overall": health,
            "engineering": max(0, min(100, health - high * 3)),
            "supply_chain": max(0, min(100, 100 - int(_number(metrics.get("limited_sources"), 0)) * 5)),
            "manufacturing": max(0, min(100, health - int(_number(metrics.get("no_stock"), 0)) * 4)),
            "procurement": max(0, min(100, 100 - int(_number(metrics.get("long_lead"), 0)) * 4)),
            "documentation": max(0, min(100, 60 + int(_number(metrics.get("saved_alternatives"), 0)) * 8)),
        }
    confidence_breakdown = _build_brief_confidence_breakdown(
        advisor=advisor,
        metrics=metrics,
        actions=ranked_raw,
    )
    priority_matrix = _build_priority_matrix(ranked_raw)

    brief: Dict[str, Any] = {
        "version": 2 if ENABLE_DECISION_ENGINE_V2 else 1,
        "insufficient_evidence": insufficient,
        "executive_summary": executive_summary,
        "executive_readiness": executive_readiness,
        "priority_matrix": priority_matrix,
        "production_readiness": {
            "label": production_label,
            "score": int(_number(executive_readiness.get("overall"), health)),
            "explanation": production_explanation,
            "tone": production_tone,
            "domains": executive_readiness,
        },
        "critical_findings": critical_findings,
        "primary_recommendation": _primary_recommendation(advisor, recommended_actions or ranked_raw),
        "procurement_impact": business_impact["procurement"],
        "manufacturing_impact": business_impact["manufacturing"],
        "lifecycle_impact": lifecycle_impact,
        "cost_impact": cost_impact,
        "recommended_actions": recommended_actions if ENABLE_DECISION_ENGINE_V2 else [
            {
                "title": _text(action.get("title"), "Engineering action"),
                "part_number": _text(action.get("part_number"), "—"),
                "recommendation": _text(action.get("recommendation") or action.get("action")),
                "effort": _text(action.get("effort"), "—"),
                "score": int(_number(action.get("score"), 0)),
            }
            for action in recommended_actions[:5]
        ],
        "business_impact": business_impact,
        "confidence": {
            "label": _confidence_label(confidence),
            "score": confidence,
            "explanation": _confidence_explanation(
                confidence=confidence,
                metrics=metrics,
                intelligence=intelligence_data,
                insufficient=insufficient,
            ),
            "breakdown": confidence_breakdown,
        },
        "supporting_evidence": evidence[:8] or [INSUFFICIENT_EVIDENCE],
        "intelligence": intelligence_data,
        "advisor": advisor,
        "engineering_dependency_report": dependency_report,
    }
    return brief


def format_decision_brief_for_report(brief: Mapping[str, Any]) -> Dict[str, Any]:
    """Plain-text sections for PDF/CSV export."""
    readiness = brief.get("production_readiness") or {}
    confidence = brief.get("confidence") or {}
    business = brief.get("business_impact") or {}
    findings_lines = [
        f"• {_text(item.get('category'))}: {_text(item.get('detail'))} (Evidence: {_text(item.get('evidence'), '—')})"
        for item in (brief.get("critical_findings") or [])
    ]
    action_lines = []
    for action in brief.get("recommended_actions") or []:
        if brief.get("version") == 2:
            action_lines.append(
                f"• Priority: {_text(action.get('priority'))} | Owner: {_text(action.get('owner'))}\n"
                f"  Action: {_text(action.get('action'))}\n"
                f"  Reason: {_text(action.get('reason'))}\n"
                f"  Evidence: {_text(action.get('evidence'))}\n"
                f"  Confidence: {_text(action.get('confidence'))}\n"
                f"  Expected result: {_text(action.get('expected_result'))}\n"
                f"  Effort: {_text(action.get('effort'))} | Impact: {_text(action.get('impact'))}"
            )
            dep = action.get("dependency") or {}
            if dep:
                domains = ", ".join(
                    _text(item.get("domain"))
                    for item in (dep.get("engineering_impact") or [])
                )
                validation = ", ".join(
                    _text(item.get("step"))
                    for item in (dep.get("validation_required") or [])
                )
                health = dep.get("projected_bom_health") or {}
                roi = dep.get("engineering_roi") or {}
                action_lines.append(
                    f"  Engineering impact: {domains or '—'}\n"
                    f"  Validation required: {validation or '—'}\n"
                    f"  Change difficulty: {_text(dep.get('change_difficulty'))}\n"
                    f"  Schedule impact: {_text(dep.get('schedule_impact'))}\n"
                    f"  Engineering ROI: {_text(roi.get('label'))} ({_number(roi.get('score'), 0):g})\n"
                    f"  Projected BOM health: {int(_number(health.get('before'), 0))} → "
                    f"{int(_number(health.get('after'), 0))} (+{int(_number(health.get('gain'), 0))})"
                )
        else:
            action_lines.append(
                f"• {_text(action.get('part_number'))}: "
                f"{_text(action.get('recommendation') or action.get('title'))} "
                f"({_text(action.get('effort'))})"
            )
    evidence_lines = [f"• {_text(item)}" for item in (brief.get("supporting_evidence") or [])]
    return {
        "executive_summary": _text(brief.get("executive_summary")),
        "production_readiness": (
            f"{_text(readiness.get('label'))} — {_text(readiness.get('explanation'))} "
            f"({int(_number(readiness.get('score'), 0))}/100)"
        ),
        "critical_findings": "\n".join(findings_lines) or INSUFFICIENT_EVIDENCE,
        "recommended_actions": "\n\n".join(action_lines) or INSUFFICIENT_EVIDENCE,
        "business_impact": (
            f"Schedule: {_text(business.get('schedule'))}\n"
            f"Cost: {_text(business.get('cost'))}\n"
            f"Manufacturing: {_text(business.get('manufacturing'))}\n"
            f"Procurement: {_text(business.get('procurement'))}\n"
            f"Supply chain: {_text(business.get('supply_chain'))}"
        ),
        "confidence": (
            f"{_text(confidence.get('label'))} ({int(_number(confidence.get('score'), 0))}%) — "
            f"{_text(confidence.get('explanation'))}"
        ),
        "supporting_evidence": "\n".join(evidence_lines) or INSUFFICIENT_EVIDENCE,
        "primary_recommendation": _text(brief.get("primary_recommendation")),
    }


def render_engineering_decision_brief(
    brief: Mapping[str, Any],
    *,
    mode: str = "default",
) -> None:
    """Render the executive decision brief.

    mode="workspace" — Sprint 67.1 Executive Decision Workspace (Analysis Detail only).
    mode="default" — Sprint 67 v2 or Sprint 66 v1 for BOM Analyzer and fallback paths.
    """
    if mode == "workspace":
        if ENABLE_DECISION_WORKSPACE_V71 and brief.get("version") == 2:
            _render_decision_brief_workspace(brief)
        elif ENABLE_DECISION_ENGINE_V2 and brief.get("version") == 2:
            _render_engineering_decision_brief_v2(brief)
        else:
            _render_engineering_decision_brief_v1(brief)
        return
    if ENABLE_DECISION_ENGINE_V2 and brief.get("version") == 2:
        _render_engineering_decision_brief_v2(brief)
    else:
        _render_engineering_decision_brief_v1(brief)


def render_engineering_decision_workspace(brief: Mapping[str, Any]) -> None:
    """Sprint 67.1 — Engineering Intelligence tab presentation only."""
    render_engineering_decision_brief(brief, mode="workspace")


def _decision_icon(name: str, size: int = 16) -> str:
    markup = lucide(name, size)
    if not markup:
        return ""
    return f'<span class="cv671-icon" aria-hidden="true">{markup}</span>'


def _finding_component_label(finding: Mapping[str, Any]) -> str:
    for key in ("part_number", "mpn", "component", "affected_part"):
        value = _text(finding.get(key))
        if value and value not in {"—", "Component"}:
            return value
    return ""


def _finding_action_hint(finding: Mapping[str, Any], actions: Iterable[Mapping[str, Any]]) -> str:
    component = _finding_component_label(finding)
    if not component:
        return "See prioritized actions below."
    for action in actions:
        if _text(action.get("part_number")) == component:
            return _text(action.get("action") or action.get("title"), "See prioritized actions below.")
    return "See prioritized actions below."


def _severity_icon(impact: str) -> str:
    level = _text(impact, "medium").lower()
    if level == "high":
        return _decision_icon("octagon-alert", 16)
    if level == "low":
        return _decision_icon("badge-check", 16)
    return _decision_icon("alert-circle", 16)


def _tone_css_class(tone: str) -> str:
    return {"good": "good", "bad": "bad", "warn": "warn"}.get(_text(tone, "warn"), "warn")


def _header_top_action(actions: Iterable[Mapping[str, Any]]) -> tuple[str, str]:
    rows = list(actions or [])
    if not rows:
        return "—", "No prioritized action recorded"
    action = rows[0]
    return _text(action.get("part_number"), "—"), _text(action.get("title"), "Review required")


def _header_effort_display(brief: Mapping[str, Any]) -> tuple[str, str]:
    advisor = brief.get("advisor") or {}
    total = advisor.get("estimated_total_effort")
    if total is not None and int(_number(total, 0)) > 0:
        return "Total estimated effort", f"{int(_number(total, 0))} hours"
    actions = list(brief.get("recommended_actions") or [])
    if actions:
        return "Top action effort", _text(actions[0].get("effort"), INSUFFICIENT_EVIDENCE)
    return "Estimated effort", INSUFFICIENT_EVIDENCE


def _confidence_bar_html(score: int) -> str:
    pct = max(0, min(100, int(score)))
    return (
        f'<div class="cv671-confidence-bar" role="progressbar" aria-valuenow="{pct}" '
        f'aria-valuemin="0" aria-valuemax="100">'
        f'<i style="width:{pct}%"></i></div>'
    )


def _evidence_checklist_html(metrics: Mapping[str, Any], insufficient: bool) -> str:
    if insufficient:
        return f'<p class="cv671-muted">{escape(INSUFFICIENT_EVIDENCE)}</p>'
    checks = [
        ("Supplier data", metrics.get("limited_sources") is not None or metrics.get("no_stock") is not None),
        ("Lifecycle", _number(metrics.get("lifecycle_concerns"), -1) >= 0),
        ("Inventory", _number(metrics.get("no_stock"), -1) >= 0),
        ("Alternates", _number(metrics.get("saved_alternatives"), 0) > 0),
    ]
    items = []
    for label, ok in checks:
        icon = _decision_icon("badge-check" if ok else "circle-x", 14)
        state = "available" if ok else "missing"
        items.append(
            f'<li class="cv671-evidence-check cv671-evidence-check--{state}">'
            f'{icon}<span>{escape(label)}</span></li>'
        )
    return f'<ul class="cv671-evidence-checks">{"".join(items)}</ul>'


def _html_readiness_panel(readiness: Mapping[str, Any], *, premium: bool) -> str:
    tone = _tone_css_class(_text(readiness.get("tone"), "warn"))
    score = int(_number(readiness.get("score"), 0))
    label = _text(readiness.get("label"), INSUFFICIENT_EVIDENCE)
    explanation = _text(readiness.get("explanation"), INSUFFICIENT_EVIDENCE)
    if not premium:
        return (
            f'<article class="cv66-card cv66-card--{escape(tone)}">'
            f"<span>Production Readiness</span>"
            f"<strong>{escape(label)}</strong>"
            f"<small>{score}/100 · {escape(explanation)}</small>"
            f"</article>"
        )
    return (
        f'<article class="cv671-readiness cv671-readiness--{escape(tone)}">'
        f'<div class="cv671-readiness-head">'
        f'{_decision_icon("shield", 18)}'
        f"<div><span>Production Readiness</span>"
        f'<span class="cv671-badge cv671-badge--{escape(tone)}">{escape(label)}</span></div>'
        f"</div>"
        f'<p class="cv671-readiness-copy">{escape(explanation)}</p>'
        f'<div class="cv671-readiness-meter" role="progressbar" aria-valuenow="{score}" '
        f'aria-valuemin="0" aria-valuemax="100"><i style="width:{score}%"></i></div>'
        f'<small class="cv671-readiness-score">{score}/100 production-readiness evidence score</small>'
        f'<small class="cv671-readiness-score">Includes evidence completeness, supply continuity, '
        f'and release blockers; may differ from BOM Health.</small>'
        f"</article>"
    )


def _html_confidence_panel(
    confidence: Mapping[str, Any],
    metrics: Mapping[str, Any],
    *,
    insufficient: bool,
    premium: bool,
) -> str:
    score = int(_number(confidence.get("score"), 0))
    label = _text(confidence.get("label"), INSUFFICIENT_EVIDENCE)
    explanation = _text(confidence.get("explanation"), INSUFFICIENT_EVIDENCE)
    if not premium:
        return (
            f'<article class="cv66-card cv66-card--confidence">'
            f"<span>Engineering Confidence</span>"
            f"<strong>{score}%</strong>"
            f"<small>{escape(explanation)}</small>"
            f"</article>"
        )
    return (
        f'<article class="cv671-confidence">'
        f'<div class="cv671-section-label">{_decision_icon("gauge", 16)} Engineering Confidence</div>'
        f'<div class="cv671-confidence-score">{score}%</div>'
        f"{_confidence_bar_html(score)}"
        f'<div class="cv671-confidence-label">{escape(label)} confidence</div>'
        f'<p class="cv671-muted">{escape(explanation)}</p>'
        f"<div class=\"cv671-based-on\"><strong>Based on:</strong>"
        f"{_confidence_breakdown_html(confidence.get('breakdown') or []) or _evidence_checklist_html(metrics, insufficient)}"
        f"</div></article>"
    )


def _html_findings_list(findings: Iterable[Mapping[str, Any]], actions: Iterable[Mapping[str, Any]]) -> str:
    rows = list(findings or [])
    if not rows:
        return (
            '<li class="cv66-finding cv66-finding--low"><strong>No critical blocker</strong>'
            "<span>No prioritized engineering exception is currently recorded.</span></li>"
        )
    return "".join(
        f'<li class="cv66-finding cv66-finding--{escape(_text(item.get("impact"), "medium"))}">'
        f'<strong>{escape(_text(item.get("category")))}</strong>'
        f'<span>{escape(_text(item.get("detail")))}</span>'
        f'<small class="cv67-evidence-ref">Evidence: {escape(_text(item.get("evidence"), INSUFFICIENT_EVIDENCE))}</small></li>'
        for item in rows
    )


def _html_findings_cards(findings: Iterable[Mapping[str, Any]], actions: Iterable[Mapping[str, Any]]) -> str:
    rows = list(findings or [])
    if not rows:
        return '<p class="cv671-muted">No critical findings recorded.</p>'
    cards = []
    for item in rows:
        component = _finding_component_label(item)
        component_html = (
            f'<div class="cv671-finding-part">{escape(component)}</div>' if component else ""
        )
        cards.append(
            f'<article class="cv671-finding cv671-finding--{escape(_text(item.get("impact"), "medium"))}">'
            f'<div class="cv671-finding-head">{_severity_icon(_text(item.get("impact"), "medium"))}'
            f'<div><div class="cv671-finding-title">{escape(_text(item.get("category")))}</div>'
            f"{component_html}</div></div>"
            f'<p class="cv671-finding-copy">{escape(_text(item.get("detail")))}</p>'
            f'<div class="cv671-finding-meta"><strong>Evidence:</strong> '
            f'{escape(_text(item.get("evidence"), INSUFFICIENT_EVIDENCE))}</div>'
            f'<div class="cv671-finding-meta"><strong>Action:</strong> '
            f'{escape(_finding_action_hint(item, actions))}</div>'
            f"</article>"
        )
    return f'<div class="cv671-findings-grid">{"".join(cards)}</div>'


def _html_business_impact(
    business: Mapping[str, Any],
    *,
    workspace: bool,
) -> str:
    items = [
        ("Schedule", "calendar-clock", business.get("schedule")),
        ("Cost", "dollar-sign", business.get("cost")),
        ("Manufacturing", "factory", business.get("manufacturing")),
        ("Procurement", "shopping-cart", business.get("procurement")),
        ("Supply Chain", "package", business.get("supply_chain")),
    ]
    if workspace:
        cards = []
        for title, icon, copy in items:
            cards.append(
                f'<article class="cv671-impact-card">'
                f'<div class="cv671-impact-head">{_decision_icon(icon, 16)}<span>{escape(title)}</span></div>'
                f'<div class="cv671-impact-level">Impact summary</div>'
                f'<p class="cv671-impact-copy">{escape(_text(copy, INSUFFICIENT_EVIDENCE))}</p>'
                f"</article>"
            )
        return f'<div class="cv671-impact-grid">{"".join(cards)}</div>'
    blocks = []
    for title, _icon, copy in items:
        blocks.append(f"<div><h4>{escape(title)}</h4><p>{escape(_text(copy, INSUFFICIENT_EVIDENCE))}</p></div>")
    return f'<div class="cv66-impact-grid">{"".join(blocks)}</div>'


def _confidence_breakdown_html(breakdown: Iterable[Mapping[str, Any]]) -> str:
    rows = list(breakdown or [])
    if not rows:
        return ""
    items = []
    for row in rows:
        available = bool(row.get("available"))
        icon = "✔" if available else "✖"
        state = "available" if available else "missing"
        items.append(
            f'<li class="cv68-confidence-item cv68-confidence-item--{state}">'
            f'<span class="cv68-confidence-icon">{icon}</span>'
            f'<span>{escape(_text(row.get("label")))}</span></li>'
        )
    return f'<ul class="cv68-confidence-breakdown">{"".join(items)}</ul>'


def _html_executive_readiness(readiness: Mapping[str, Any]) -> str:
    domains = [
        ("Production Readiness", "overall"),
        ("Engineering", "engineering"),
        ("Supply Chain", "supply_chain"),
        ("Manufacturing", "manufacturing"),
        ("Procurement", "procurement"),
        ("Documentation", "documentation"),
    ]
    cards = []
    for label, key in domains:
        score = int(_number(readiness.get(key), 0))
        cards.append(
            f'<article class="cv68-readiness-card">'
            f'<div class="cv68-readiness-label">{escape(label)}</div>'
            f'<div class="cv68-readiness-value">{score}%</div>'
            f'<div class="cv68-readiness-meter"><i style="width:{score}%"></i></div>'
            f"</article>"
        )
    return f'<div class="cv68-readiness-grid">{"".join(cards)}</div>'


def _html_priority_matrix(matrix: Mapping[str, Any]) -> str:
    if not matrix:
        return ""
    sections = []
    for bucket in ("Do Now", "Do This Week", "Do Before Production", "Can Wait"):
        rows = list(matrix.get(bucket) or [])
        if not rows:
            continue
        items = "".join(
            f'<li><strong>{escape(_text(row.get("part_number")))}</strong> '
            f'{escape(_text(row.get("title")))} '
            f'<span>{escape(_text(row.get("owner")))} · {escape(_text(row.get("effort")))}</span></li>'
            for row in rows[:4]
        )
        sections.append(
            f'<section class="cv68-priority-bucket">'
            f'<h4>{escape(bucket)}</h4><ul>{items}</ul></section>'
        )
    if not sections:
        return f'<p class="cv671-muted">{escape(INSUFFICIENT_EVIDENCE)}</p>'
    return f'<div class="cv68-priority-matrix">{"".join(sections)}</div>'


def _html_action_intelligence(action: Mapping[str, Any]) -> str:
    impact_rows = _action_projected_improvement_rows(action)
    impact_html = "".join(
        f"<div><span>{escape(label)}</span><strong>{escape(value)}</strong></div>"
        for label, value in impact_rows
    )
    inaction = list(action.get("inaction_consequences") or [])
    inaction_html = "".join(f"<li>{escape(_text(item))}</li>" for item in inaction[:4])
    reasoning = list(action.get("engineering_reasoning") or [])
    reasoning_html = "".join(f"<li>{escape(_text(item))}</li>" for item in reasoning[:5])
    tradeoffs = list(action.get("tradeoffs") or [])
    tradeoff_html = "".join(
        f'<article class="cv68-tradeoff-card"><strong>{escape(_text(item.get("option")))}</strong>'
        f'<span>{escape(_text(item.get("summary")))}</span>'
        f'<p>{escape(_text(item.get("detail")))}</p></article>'
        for item in tradeoffs[:3]
    )
    dependencies = list(action.get("dependencies") or [])
    dependency_html = ""
    if dependencies:
        chain = " ↓ ".join(escape(_text(step)) for step in dependencies)
        dependency_html = f'<div class="cv68-dependency-chain">{chain}</div>'
    cross = list(action.get("cross_component_impact") or [])
    cross_html = "".join(
        f'<li><strong>{escape(_text(item.get("component")))}</strong> '
        f'{escape(_text(item.get("relationship")))}</li>'
        for item in cross[:4]
    )
    timeline = list(action.get("decision_timeline") or [])
    timeline_html = "".join(
        f'<div class="cv68-timeline-step"><span>{escape(_text(item.get("phase")))}</span>'
        f'<strong>{escape(_text(item.get("owner")))}</strong>'
        f'<small>{escape(_text(item.get("detail")))}</small></div>'
        for item in timeline
    )
    confidence_breakdown = _confidence_breakdown_html(action.get("confidence_breakdown") or [])

    blocks = []
    if impact_html:
        blocks.append(
            f'<div class="cv68-action-block"><h4>Expected result if completed</h4>'
            f'<div class="cv68-impact-grid">{impact_html}</div></div>'
        )
    if inaction_html:
        blocks.append(
            f'<div class="cv68-action-block"><h4>If no action is taken</h4><ul>{inaction_html}</ul></div>'
        )
    if reasoning_html:
        blocks.append(
            f'<div class="cv68-action-block"><h4>Why this recommendation</h4><ul>{reasoning_html}</ul></div>'
        )
    if tradeoff_html:
        blocks.append(
            f'<div class="cv68-action-block"><h4>Trade-off analysis</h4><div class="cv68-tradeoff-grid">{tradeoff_html}</div></div>'
        )
    if dependency_html:
        blocks.append(
            f'<div class="cv68-action-block"><h4>Dependency chain</h4>{dependency_html}</div>'
        )
    if cross_html:
        blocks.append(
            f'<div class="cv68-action-block"><h4>Cross-component impact</h4><ul>{cross_html}</ul></div>'
        )
    if timeline_html:
        blocks.append(
            f'<div class="cv68-action-block"><h4>Decision timeline</h4><div class="cv68-timeline">{timeline_html}</div></div>'
        )
    if confidence_breakdown:
        blocks.append(
            f'<div class="cv68-action-block"><h4>Confidence basis</h4>{confidence_breakdown}</div>'
        )
    if not blocks:
        return ""
    return f'<div class="cv68-action-intelligence">{"".join(blocks)}</div>'


def _action_projected_improvement_rows(action: Mapping[str, Any]) -> List[tuple[str, str]]:
    impact = action.get("decision_impact") or {}
    if not impact:
        return []
    health = impact.get("health") or {}
    supply = impact.get("supply_risk") or {}
    lifecycle = impact.get("lifecycle_risk") or {}
    single = impact.get("single_source_exposure") or {}
    return [
        ("Health", f"{int(_number(health.get('before'), 0))} → {int(_number(health.get('after'), 0))}"),
        ("Supply risk", f"{int(_number(supply.get('before'), 0))} → {int(_number(supply.get('after'), 0))}"),
        ("Lifecycle risk", f"{_text(lifecycle.get('before'))} → {_text(lifecycle.get('after'))}"),
        (
            "Single-source exposure",
            f"{int(_number(single.get('before'), 0))} → {int(_number(single.get('after'), 0))}",
        ),
        ("Schedule improvement", f"~{int(_number(impact.get('schedule_improvement_weeks'), 0))} week(s)"),
        ("Procurement effort", f"~{int(_number(impact.get('procurement_effort_hours'), 0))} hour(s)"),
    ]


def _html_action_dependency_fields(action: Mapping[str, Any]) -> str:
    dep = action.get("dependency") or {}
    if not dep:
        return ""

    impact_items = dep.get("engineering_impact") or []
    impact_html = "".join(
        f'<li><strong>{escape(_text(item.get("domain")))}</strong> — '
        f'{escape(_text(item.get("explanation")))}</li>'
        for item in impact_items
    )
    validation_items = dep.get("validation_required") or []
    validation_html = ", ".join(
        escape(_text(item.get("step"))) for item in validation_items
    ) or "—"
    roi = dep.get("engineering_roi") or {}
    health = dep.get("projected_bom_health") or {}
    health_html = (
        f"{int(_number(health.get('before'), 0))} → "
        f"{int(_number(health.get('after'), 0))} "
        f"(+{int(_number(health.get('gain'), 0))})"
    )
    roi_html = f"{escape(_text(roi.get('label')))} ({_number(roi.get('score'), 0):g})"

    return (
        f'<div><dt>Engineering impact</dt>'
        f'<dd><ul class="cv68-dep-domains">{impact_html}</ul></dd></div>'
        f'<div><dt>Validation required</dt><dd>{validation_html}</dd></div>'
        f'<div><dt>Change difficulty</dt><dd>{escape(_text(dep.get("change_difficulty")))}</dd></div>'
        f'<div><dt>Schedule impact</dt><dd>{escape(_text(dep.get("schedule_impact")))}</dd></div>'
        f'<div><dt>Estimated engineering effort</dt><dd>{escape(_text(dep.get("estimated_effort")))}</dd></div>'
        f'<div><dt>Engineering ROI</dt><dd>{roi_html}</dd></div>'
        f'<div><dt>Projected BOM health</dt><dd>{health_html}</dd></div>'
    )


def _html_actions(actions: Iterable[Mapping[str, Any]], *, workspace: bool) -> str:
    rows = list(actions or [])
    if not rows:
        return f'<p class="cv671-muted">{escape(INSUFFICIENT_EVIDENCE)}</p>'
    if workspace:
        cards = []
        for action in rows:
            cards.append(
                f'<article class="cv671-action-card">'
                f'<div class="cv671-action-badges">'
                f'<span class="cv671-badge cv671-badge--priority">{escape(_text(action.get("priority")))}</span>'
                f'<span class="cv671-badge cv671-badge--owner">{escape(_text(action.get("owner")))}</span>'
                f'<span class="cv671-badge cv671-badge--effort">{escape(_text(action.get("effort")))}</span>'
                f'<span class="cv671-badge cv671-badge--result">{escape(_text(action.get("priority_bucket")))}</span>'
                f"</div>"
                f'<p class="cv671-action-title">{escape(_text(action.get("action")))}</p>'
                f'<dl class="cv671-action-body">'
                f'<div><dt>Reason</dt><dd>{escape(_text(action.get("reason")))}</dd></div>'
                f'<div><dt>Evidence</dt><dd>{escape(_text(action.get("evidence")))}</dd></div>'
                f'<div><dt>Confidence</dt><dd>{escape(_text(action.get("confidence")))}</dd></div>'
                f'<div><dt>Expected result</dt><dd>{escape(_text(action.get("expected_result")))}</dd></div>'
                f'<div><dt>Impact</dt><dd>{escape(_text(action.get("impact")))}</dd></div>'
                f"{_html_action_dependency_fields(action)}"
                f"</dl>"
                f'{_html_action_intelligence(action)}'
                f"</article>"
            )
        return f'<div class="cv671-actions">{"".join(cards)}</div>'
    return "".join(
        f"""
        <article class="cv67-action-card">
          <div class="cv67-action-head">
            <span class="cv67-priority">{escape(_text(action.get("priority")))}</span>
            <span class="cv67-owner">{escape(_text(action.get("owner")))}</span>
          </div>
          <p class="cv67-action-title">{escape(_text(action.get("action")))}</p>
          <dl class="cv67-action-meta">
            <div><dt>Reason</dt><dd>{escape(_text(action.get("reason")))}</dd></div>
            <div><dt>Evidence</dt><dd>{escape(_text(action.get("evidence")))}</dd></div>
            <div><dt>Confidence</dt><dd>{escape(_text(action.get("confidence")))}</dd></div>
            <div><dt>Expected result</dt><dd>{escape(_text(action.get("expected_result")))}</dd></div>
            <div><dt>Effort</dt><dd>{escape(_text(action.get("effort")))}</dd></div>
            <div><dt>Impact</dt><dd>{escape(_text(action.get("impact")))}</dd></div>
            {_html_action_dependency_fields(action)}
          </dl>
        </article>
        """
        for action in rows
    )


def _html_evidence_panel(
    evidence: Iterable[Any],
    *,
    insufficient: bool,
    workspace: bool,
) -> str:
    rows = [ _text(item) for item in (evidence or []) if _text(item) ]
    if insufficient or not rows or (len(rows) == 1 and rows[0] == INSUFFICIENT_EVIDENCE):
        return f'<div class="cv671-evidence-panel cv671-evidence-panel--empty">{escape(INSUFFICIENT_EVIDENCE)}</div>'
    if workspace:
        chips = "".join(f'<span class="cv671-evidence-chip">{escape(item)}</span>' for item in rows)
        return f'<div class="cv671-evidence-panel">{chips}</div>'
    return "".join(f"<li>{escape(item)}</li>" for item in rows)


def _html_workspace_strip(brief: Mapping[str, Any]) -> str:
    readiness = brief.get("production_readiness") or {}
    confidence = brief.get("confidence") or {}
    actions = brief.get("recommended_actions") or []
    top_part, top_title = _header_top_action(actions)
    effort_label, effort_value = _header_effort_display(brief)
    conf_score = int(_number(confidence.get("score"), 0))
    return f"""
        <header class="cv671-exec-header cv672-exec-strip">
          <div class="cv671-exec-kicker">{_decision_icon("target", 16)} Executive Engineering Decision</div>
          <div class="cv671-exec-grid">
            <div class="cv671-exec-stat">
              <span>Production Status</span>
              <strong>{escape(_text(readiness.get("label"), INSUFFICIENT_EVIDENCE))}</strong>
            </div>
            <div class="cv671-exec-stat">
              <span>Engineering Confidence</span>
              <strong>{conf_score}%</strong>
            </div>
            <div class="cv671-exec-stat cv671-exec-stat--action">
              <span>Top Engineering Action</span>
              <strong>{escape(top_part)}</strong>
              <small>{escape(top_title)}</small>
            </div>
            <div class="cv671-exec-stat">
              <span>{escape(effort_label)}</span>
              <strong>{escape(effort_value)}</strong>
            </div>
          </div>
        </header>
    """


WORKSPACE_CATEGORIES: tuple[str, ...] = (
    "Decision Overview",
    "Critical Findings",
    "Recommended Actions",
    "Business Impact",
    "Evidence",
    "Risk Analytics",
)


def render_engineering_workspace_strip(brief: Mapping[str, Any]) -> None:
    """Sprint 67.2 — executive summary strip only."""
    import streamlit as st

    st.markdown(
        f'<section class="cv671-workspace cv672-workspace-shell">{_html_workspace_strip(brief)}</section>',
        unsafe_allow_html=True,
    )


def render_engineering_workspace_overview(brief: Mapping[str, Any]) -> None:
    import streamlit as st

    readiness = brief.get("production_readiness") or {}
    confidence = brief.get("confidence") or {}
    actions = brief.get("recommended_actions") or []
    metrics = (brief.get("advisor") or {}).get("metrics") or {}
    insufficient = bool(brief.get("insufficient_evidence"))
    top_part, top_title = _header_top_action(actions)
    release_copy = _text(readiness.get("explanation"), INSUFFICIENT_EVIDENCE)
    executive_readiness = brief.get("executive_readiness") or readiness.get("domains") or {}

    st.markdown(
        f"""
        <section class="cv672-category">
          <p class="cv671-summary">{escape(_text(brief.get("executive_summary")))}</p>
          <div class="cv671-status-row">
            {_html_readiness_panel(readiness, premium=True)}
            {_html_confidence_panel(confidence, metrics, insufficient=insufficient, premium=True)}
          </div>
          <div class="cv68-section">
            <h4 class="cv672-subheading">{_decision_icon("shield", 14)} Executive readiness score</h4>
            {_html_executive_readiness(executive_readiness)}
          </div>
          <article class="cv672-overview-action">
            <div class="cv672-section-label">{_decision_icon("target", 16)} Top action</div>
            <strong>{escape(top_part)}</strong>
            <span>{escape(top_title)}</span>
          </article>
          <article class="cv672-release-note">
            <div class="cv672-section-label">{_decision_icon("shield", 16)} Release explanation</div>
            <p>{escape(release_copy)}</p>
          </article>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_engineering_workspace_findings(brief: Mapping[str, Any]) -> None:
    import streamlit as st

    findings = brief.get("critical_findings") or []
    actions = brief.get("recommended_actions") or []
    st.markdown(
        f"""
        <section class="cv672-category">
          <h3 class="cv671-heading">{_decision_icon("triangle-alert", 16)} Critical Findings</h3>
          {_html_findings_cards(findings, actions)}
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_engineering_workspace_actions(brief: Mapping[str, Any]) -> None:
    import streamlit as st

    actions = brief.get("recommended_actions") or []
    priority_matrix = brief.get("priority_matrix") or {}
    st.html(
        f"""
        <section class="cv672-category">
          <h3 class="cv671-heading">{_decision_icon("list-checks", 16)} Recommended Actions</h3>
          <div class="cv68-section cv69-matrix-section">
            <h4 class="cv672-subheading">{_decision_icon("target", 14)} Decision priority matrix</h4>
            {_html_priority_matrix(priority_matrix)}
          </div>
        </section>
        """
    )
    render_recommendation_workspace(actions, brief)


def render_engineering_workspace_impact(brief: Mapping[str, Any]) -> None:
    import streamlit as st

    business = brief.get("business_impact") or {}
    st.markdown(
        f"""
        <section class="cv672-category">
          <h3 class="cv671-heading">{_decision_icon("briefcase-business", 16)} Business Impact</h3>
          {_html_business_impact(business, workspace=True)}
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_engineering_workspace_evidence(brief: Mapping[str, Any]) -> None:
    import streamlit as st

    confidence = brief.get("confidence") or {}
    evidence = brief.get("supporting_evidence") or []
    metrics = (brief.get("advisor") or {}).get("metrics") or {}
    insufficient = bool(brief.get("insufficient_evidence"))
    st.markdown(
        f"""
        <section class="cv672-category">
          <h3 class="cv671-heading">{_decision_icon("clipboard-check", 16)} Supporting Evidence</h3>
          {_html_evidence_panel(evidence, insufficient=insufficient, workspace=True)}
          <div class="cv672-evidence-confidence">
            <h4 class="cv672-subheading">{_decision_icon("gauge", 14)} Confidence explanation</h4>
            <p class="cv671-muted">{escape(_text(confidence.get("explanation"), INSUFFICIENT_EVIDENCE))}</p>
            <div class="cv672-based-on"><strong>Evidence availability</strong>
            {_evidence_checklist_html(metrics, insufficient)}</div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def workspace_category_counts(brief: Mapping[str, Any]) -> Dict[str, int]:
    return {
        "findings": len(brief.get("critical_findings") or []),
        "actions": len(brief.get("recommended_actions") or []),
    }


def _render_decision_brief_workspace(brief: Mapping[str, Any]) -> None:
    """Legacy full-page workspace layout — kept for fallback paths."""
    import streamlit as st

    render_engineering_workspace_strip(brief)
    render_engineering_workspace_overview(brief)
    render_engineering_workspace_findings(brief)
    render_engineering_workspace_impact(brief)
    render_engineering_workspace_actions(brief)
    render_engineering_workspace_evidence(brief)


def _render_engineering_decision_brief_v1(brief: Mapping[str, Any]) -> None:
    import streamlit as st

    readiness = brief.get("production_readiness") or {}
    confidence = brief.get("confidence") or {}
    findings = brief.get("critical_findings") or []
    actions = brief.get("recommended_actions") or []
    evidence = brief.get("supporting_evidence") or []

    findings_html = "".join(
        f'<li class="cv66-finding cv66-finding--{escape(_text(item.get("impact"), "medium"))}">'
        f'<strong>{escape(_text(item.get("category")))}</strong>'
        f'<span>{escape(_text(item.get("detail")))}</span></li>'
        for item in findings
    ) or (
        '<li class="cv66-finding cv66-finding--low"><strong>No critical blocker</strong>'
        "<span>No prioritized engineering exception is currently recorded.</span></li>"
    )

    actions_html = "".join(
        f'<li><strong>{escape(_text(action.get("part_number")))}</strong> — '
        f'{escape(_text(action.get("recommendation") or action.get("title")))} '
        f'<em>({escape(_text(action.get("effort")))})</em></li>'
        for action in actions
    )

    evidence_html = "".join(f"<li>{escape(_text(item))}</li>" for item in evidence)

    st.markdown(
        f"""
        <section class="cv66-decision-brief">
          <div class="cv66-decision-kicker">Engineering Decision Intelligence</div>
          <h2 class="cv66-decision-title">Executive Engineering Summary</h2>
          <p class="cv66-decision-copy">{escape(_text(brief.get("executive_summary")))}</p>
          <div class="cv66-decision-grid">
            <article class="cv66-card cv66-card--{escape(_text(readiness.get('tone'), 'warn'))}">
              <span>Production Readiness</span>
              <strong>{escape(_text(readiness.get('label')))}</strong>
              <small>{int(_number(readiness.get('score'), 0))}/100 · {escape(_text(readiness.get('explanation')))}</small>
            </article>
            <article class="cv66-card cv66-card--confidence">
              <span>Confidence</span>
              <strong>{escape(_text(confidence.get('label')))}</strong>
              <small>{escape(_text(confidence.get('explanation')))}</small>
            </article>
          </div>
          <div class="cv66-section">
            <h3>Critical Findings</h3>
            <ul class="cv66-findings">{findings_html}</ul>
          </div>
          <div class="cv66-section cv66-section--highlight">
            <h3>Engineering Recommendation</h3>
            <p>{escape(_text(brief.get("primary_recommendation")))}</p>
          </div>
          <div class="cv66-impact-grid">
            <div><h4>Procurement Impact</h4><p>{escape(_text(brief.get("procurement_impact")))}</p></div>
            <div><h4>Manufacturing Impact</h4><p>{escape(_text(brief.get("manufacturing_impact")))}</p></div>
            <div><h4>Lifecycle Impact</h4><p>{escape(_text(brief.get("lifecycle_impact")))}</p></div>
            <div><h4>Cost Impact</h4><p>{escape(_text(brief.get("cost_impact")))}</p></div>
          </div>
          <div class="cv66-section">
            <h3>Recommended Actions</h3>
            <ol class="cv66-actions">{actions_html}</ol>
          </div>
          <div class="cv66-section">
            <h3>Supporting Evidence</h3>
            <ul class="cv66-evidence">{evidence_html}</ul>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _render_engineering_decision_brief_v2(brief: Mapping[str, Any]) -> None:
    import streamlit as st

    readiness = brief.get("production_readiness") or {}
    confidence = brief.get("confidence") or {}
    findings = brief.get("critical_findings") or []
    actions = brief.get("recommended_actions") or []
    evidence = brief.get("supporting_evidence") or []
    business = brief.get("business_impact") or {}
    metrics = (brief.get("advisor") or {}).get("metrics") or {}
    insufficient = bool(brief.get("insufficient_evidence"))

    findings_html = _html_findings_list(findings, actions)
    actions_html = _html_actions(actions, workspace=False)
    evidence_html = _html_evidence_panel(evidence, insufficient=insufficient, workspace=False)

    st.markdown(
        f"""
        <section class="cv66-decision-brief cv67-decision-brief">
          <div class="cv66-decision-kicker">Engineering Decision Intelligence v2</div>
          <h2 class="cv66-decision-title">Executive Engineering Summary</h2>
          <p class="cv66-decision-copy">{escape(_text(brief.get("executive_summary")))}</p>
          <div class="cv66-decision-grid">
            {_html_readiness_panel(readiness, premium=False)}
            {_html_confidence_panel(confidence, metrics, insufficient=insufficient, premium=False)}
          </div>
          <div class="cv66-section">
            <h3>Critical Findings</h3>
            <ul class="cv66-findings">{findings_html}</ul>
          </div>
          <div class="cv66-section">
            <h3>Business Impact</h3>
            {_html_business_impact(business, workspace=False)}
          </div>
          <div class="cv66-section">
            <h3>Recommended Actions</h3>
            <div class="cv67-actions">{actions_html}</div>
          </div>
          <div class="cv66-section">
            <h3>Supporting Evidence</h3>
            <ul class="cv66-evidence">{evidence_html}</ul>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

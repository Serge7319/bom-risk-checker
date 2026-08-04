"""Cadivor Engineering Decision Intelligence — Sprint 66 v1 / Sprint 67 v2."""
from __future__ import annotations

from html import escape
from typing import Any, Dict, Iterable, List, Mapping, Optional

import pandas as pd

from src.ai_advisor import build_engineering_supply_advisor
from src.bom_intelligence import analyze_bom_intelligence
from src.config import ENABLE_DECISION_ENGINE_V2

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
    return _text(part.get("mpn") or part.get("MPN") or part.get("part_number"), "Component")


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
        rows.append(
            {
                "mpn": _text(row.get("MPN"), "Component"),
                "MPN": _text(row.get("MPN"), "Component"),
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
    if insufficient or not evidence_parts:
        expected = INSUFFICIENT_EVIDENCE
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
            intelligence_data = analyze_bom_intelligence(results_df)
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
    if intelligence_data.get("bom_health_score") is not None:
        evidence.append(f"BOM health score: {intelligence_data['bom_health_score']}/100")
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

    brief: Dict[str, Any] = {
        "version": 2 if ENABLE_DECISION_ENGINE_V2 else 1,
        "insufficient_evidence": insufficient,
        "executive_summary": executive_summary,
        "production_readiness": {
            "label": production_label,
            "score": health,
            "explanation": production_explanation,
            "tone": production_tone,
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
        },
        "supporting_evidence": evidence[:8] or [INSUFFICIENT_EVIDENCE],
        "intelligence": intelligence_data,
        "advisor": advisor,
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


def render_engineering_decision_brief(brief: Mapping[str, Any]) -> None:
    """Render the executive decision brief; v2 layout gated by ENABLE_DECISION_ENGINE_V2."""
    if ENABLE_DECISION_ENGINE_V2 and brief.get("version") == 2:
        _render_engineering_decision_brief_v2(brief)
    else:
        _render_engineering_decision_brief_v1(brief)


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

    findings_html = "".join(
        f'<li class="cv66-finding cv66-finding--{escape(_text(item.get("impact"), "medium"))}">'
        f'<strong>{escape(_text(item.get("category")))}</strong>'
        f'<span>{escape(_text(item.get("detail")))}</span>'
        f'<small class="cv67-evidence-ref">Evidence: {escape(_text(item.get("evidence"), INSUFFICIENT_EVIDENCE))}</small></li>'
        for item in findings
    )

    actions_html = "".join(
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
          </dl>
        </article>
        """
        for action in actions
    ) or f'<p class="cv67-empty">{escape(INSUFFICIENT_EVIDENCE)}</p>'

    evidence_html = "".join(f"<li>{escape(_text(item))}</li>" for item in evidence)

    st.markdown(
        f"""
        <section class="cv66-decision-brief cv67-decision-brief">
          <div class="cv66-decision-kicker">Engineering Decision Intelligence v2</div>
          <h2 class="cv66-decision-title">Executive Engineering Summary</h2>
          <p class="cv66-decision-copy">{escape(_text(brief.get("executive_summary")))}</p>
          <div class="cv66-decision-grid">
            <article class="cv66-card cv66-card--{escape(_text(readiness.get('tone'), 'warn'))}">
              <span>Production Readiness</span>
              <strong>{escape(_text(readiness.get('label')))}</strong>
              <small>{int(_number(readiness.get('score'), 0))}/100 · {escape(_text(readiness.get('explanation')))}</small>
            </article>
            <article class="cv66-card cv66-card--confidence">
              <span>Engineering Confidence</span>
              <strong>{int(_number(confidence.get('score'), 0))}%</strong>
              <small>{escape(_text(confidence.get('explanation')))}</small>
            </article>
          </div>
          <div class="cv66-section">
            <h3>Critical Findings</h3>
            <ul class="cv66-findings">{findings_html}</ul>
          </div>
          <div class="cv66-section">
            <h3>Business Impact</h3>
            <div class="cv66-impact-grid">
              <div><h4>Schedule</h4><p>{escape(_text(business.get("schedule")))}</p></div>
              <div><h4>Cost</h4><p>{escape(_text(business.get("cost")))}</p></div>
              <div><h4>Manufacturing</h4><p>{escape(_text(business.get("manufacturing")))}</p></div>
              <div><h4>Procurement</h4><p>{escape(_text(business.get("procurement")))}</p></div>
              <div><h4>Supply Chain</h4><p>{escape(_text(business.get("supply_chain")))}</p></div>
            </div>
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

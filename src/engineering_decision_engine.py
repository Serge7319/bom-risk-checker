"""Cadivor Sprint 66 — Engineering Decision Intelligence v1."""
from __future__ import annotations

from html import escape
from typing import Any, Dict, Iterable, List, Mapping, Optional

import pandas as pd

from src.ai_advisor import build_engineering_supply_advisor
from src.bom_intelligence import analyze_bom_intelligence


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
        "health_score": health_score or max(0, 100 - int(results_df["Risk Score"].mean()) if "Risk Score" in results_df else 0),
        "high_risk_count": high,
        "medium_risk_count": medium,
        "low_risk_count": low,
        "total_parts": len(results_df),
    }


def _map_production_readiness(raw: str, *, health: int, high: int) -> tuple[str, str]:
    lowered = _text(raw).lower()
    if high >= 3 or health < 55 or "needs action" in lowered:
        return "Not Recommended for Release", "bad"
    if high > 0 or "review needed" in lowered or "prototype" in lowered:
        return "Engineering Review Required", "warn"
    if "monitoring" in lowered or health >= 85:
        return "Ready for Production", "good"
    return "Ready with Conditions", "warn"


def _confidence_label(score: int) -> str:
    if score >= 82:
        return "High"
    if score >= 68:
        return "Medium"
    return "Low"


def _build_critical_findings(
    *,
    parts: Iterable[Dict[str, Any]],
    intelligence: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    part_rows = list(parts or [])

    single_source = [
        p for p in part_rows if _number(p.get("Supplier Count") or p.get("supplier_count"), 0) <= 1
    ]
    if single_source:
        sample = _text(single_source[0].get("MPN") or single_source[0].get("mpn"), "component")
        findings.append(
            {
                "category": "Single-source exposure",
                "detail": f"{len(single_source)} component(s) rely on one or fewer qualified suppliers (e.g. {sample}).",
                "impact": "high",
            }
        )

    nrnd = [
        p
        for p in part_rows
        if any(term in _text(p.get("Lifecycle Status") or p.get("lifecycle_status")).lower() for term in ("nrnd", "not recommended"))
    ]
    if nrnd:
        sample = _text(nrnd[0].get("MPN") or nrnd[0].get("mpn"), "component")
        findings.append(
            {
                "category": "NRND component",
                "detail": f"{len(nrnd)} NRND or not-recommended component(s) require lifecycle validation (e.g. {sample}).",
                "impact": "high",
            }
        )

    obsolete = [
        p
        for p in part_rows
        if any(term in _text(p.get("Lifecycle Status") or p.get("lifecycle_status")).lower() for term in ("obsolete", "eol", "end of life"))
    ]
    if obsolete:
        sample = _text(obsolete[0].get("MPN") or obsolete[0].get("mpn"), "component")
        findings.append(
            {
                "category": "Obsolete component",
                "detail": f"{len(obsolete)} obsolete/EOL component(s) need replacement planning (e.g. {sample}).",
                "impact": "high",
            }
        )

    no_stock = [p for p in part_rows if _number(p.get("Stock Available") or p.get("stock_available"), 0) <= 0]
    if no_stock:
        sample = _text(no_stock[0].get("MPN") or no_stock[0].get("mpn"), "component")
        findings.append(
            {
                "category": "Stock shortage",
                "detail": f"{len(no_stock)} component(s) show no recorded inventory (e.g. {sample}).",
                "impact": "high" if len(no_stock) >= 3 else "medium",
            }
        )

    long_lead = [
        p for p in part_rows if _number(p.get("Lead Time Weeks") or p.get("lead_time_weeks"), 0) >= 12
    ]
    if long_lead:
        sample = _text(long_lead[0].get("MPN") or long_lead[0].get("mpn"), "component")
        findings.append(
            {
                "category": "Long lead time",
                "detail": f"{len(long_lead)} component(s) exceed a 12-week lead-time threshold (e.g. {sample}).",
                "impact": "medium",
            }
        )

    high_risk = intelligence.get("risk_distribution", {}).get("High", 0)
    if high_risk and not findings:
        findings.append(
            {
                "category": "High-risk components",
                "detail": f"{high_risk} component(s) exceed the high-risk threshold in the BOM risk engine.",
                "impact": "high",
            }
        )

    if metrics.get("active_alerts"):
        findings.append(
            {
                "category": "Monitoring alerts",
                "detail": f"{metrics['active_alerts']} active monitoring alert(s) affect this BOM.",
                "impact": "medium",
            }
        )

    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda item: order.get(item["impact"], 9))
    return findings[:6]


def _primary_recommendation(advisor: Mapping[str, Any], actions: List[Mapping[str, Any]]) -> str:
    if actions:
        top = actions[0]
        part = _text(top.get("part_number"), "the highest-risk component")
        rec = _text(top.get("recommendation"), "Complete the prioritized engineering action.")
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
) -> str:
    drivers: List[str] = []
    if metrics.get("saved_alternatives"):
        drivers.append(f"{metrics['saved_alternatives']} saved alternative record(s)")
    if metrics.get("active_alerts"):
        drivers.append(f"{metrics['active_alerts']} monitoring alert(s)")
    total_parts = intelligence.get("bom_health_score") is not None
    if total_parts:
        drivers.append("BOM risk engine enrichment")
    if metrics.get("lifecycle_concerns"):
        drivers.append(f"{metrics['lifecycle_concerns']} lifecycle signal(s)")
    if not drivers:
        drivers.append("component-level BOM health and risk scoring")
    return (
        f"Confidence is {_confidence_label(confidence)} ({confidence}%) because Cadivor synthesized "
        + ", ".join(drivers[:4])
        + "."
    )


def build_engineering_decision_brief(
    *,
    results_df: pd.DataFrame | None = None,
    analysis: Dict[str, Any] | None = None,
    parts: Iterable[Dict[str, Any]] | None = None,
    alerts: Iterable[Dict[str, Any]] | None = None,
    alternatives: Iterable[Dict[str, Any]] | None = None,
    health_score: int | None = None,
) -> Dict[str, Any]:
    """Synthesize an executive engineering decision from existing Cadivor intelligence."""
    intelligence: Dict[str, Any] = {}
    part_rows = list(parts or [])

    if results_df is not None and not results_df.empty:
        intelligence = analyze_bom_intelligence(results_df)
        if not part_rows:
            part_rows = _results_to_parts(results_df)
        if analysis is None:
            analysis = _analysis_from_results(
                results_df,
                health_score=health_score or intelligence.get("bom_health_score", 0),
            )

    analysis = dict(analysis or {})
    if health_score is not None:
        analysis["health_score"] = health_score
    if not analysis.get("health_score") and intelligence:
        analysis["health_score"] = intelligence.get("bom_health_score", 0)

    advisor = build_engineering_supply_advisor(
        analysis=analysis,
        parts=part_rows,
        alerts=alerts,
        alternatives=alternatives,
    )

    health = int(_number(analysis.get("health_score"), intelligence.get("bom_health_score", 0)))
    high = int(_number(analysis.get("high_risk_count"), 0))
    production_label, production_tone = _map_production_readiness(
        _text(advisor.get("production_readiness")),
        health=health,
        high=high,
    )

    metrics = advisor.get("metrics") or {}
    actions = list(advisor.get("priority_actions") or [])
    critical_findings = _build_critical_findings(
        parts=part_rows,
        intelligence=intelligence,
        metrics=metrics,
    )

    confidence = int(_number(advisor.get("confidence"), 70))
    lifecycle_impact = (
        f"{metrics.get('lifecycle_concerns', 0)} lifecycle concern(s) recorded. "
        f"{intelligence.get('executive_summary') or advisor.get('engineering_summary', '')}"
    ).strip()
    cost_impact = (
        f"{metrics.get('no_stock', 0)} no-stock and {metrics.get('long_lead', 0)} long-lead component(s) "
        "may increase expedite cost or schedule buffer requirements."
    )

    ranked_actions = [
        {
            "title": _text(action.get("title"), "Engineering action"),
            "part_number": _text(action.get("part_number"), "—"),
            "recommendation": _text(action.get("recommendation")),
            "effort": _text(action.get("effort"), "—"),
            "score": int(_number(action.get("score"), 0)),
        }
        for action in actions[:5]
    ]

    evidence = []
    if intelligence.get("bom_health_score") is not None:
        evidence.append(f"BOM health score: {intelligence['bom_health_score']}/100")
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
    if intelligence.get("recommendations"):
        evidence.append(f"{len(intelligence['recommendations'])} BOM risk engine recommendation(s)")

    return {
        "executive_summary": _text(
            intelligence.get("executive_summary"),
            advisor.get("executive_recommendation"),
        ),
        "production_readiness": {
            "label": production_label,
            "score": health,
            "explanation": _text(advisor.get("readiness_reason")),
            "tone": production_tone,
        },
        "critical_findings": critical_findings,
        "primary_recommendation": _primary_recommendation(advisor, actions),
        "procurement_impact": _text(advisor.get("procurement_summary")),
        "manufacturing_impact": (
            f"Production readiness is {production_label.lower()}. "
            f"{metrics.get('no_stock', 0)} no-stock component(s) and "
            f"{metrics.get('long_lead', 0)} long-lead item(s) may affect build continuity."
        ),
        "lifecycle_impact": lifecycle_impact,
        "cost_impact": cost_impact,
        "recommended_actions": ranked_actions,
        "confidence": {
            "label": _confidence_label(confidence),
            "score": confidence,
            "explanation": _confidence_explanation(
                confidence=confidence,
                metrics=metrics,
                intelligence=intelligence,
            ),
        },
        "supporting_evidence": evidence[:8],
        "intelligence": intelligence,
        "advisor": advisor,
    }


def render_engineering_decision_brief(brief: Mapping[str, Any]) -> None:
    """Render the Sprint 66 executive decision brief as trusted HTML."""
    import streamlit as st

    readiness = brief.get("production_readiness") or {}
    confidence = brief.get("confidence") or {}
    findings = brief.get("critical_findings") or []
    actions = brief.get("recommended_actions") or []
    evidence = brief.get("supporting_evidence") or []

    findings_html = "".join(
        f'<li class="cv66-finding cv66-finding--{escape(item.get("impact", "medium"))}">'
        f'<strong>{escape(_text(item.get("category")))}</strong>'
        f'<span>{escape(_text(item.get("detail")))}</span></li>'
        for item in findings
    ) or '<li class="cv66-finding cv66-finding--low"><strong>No critical blocker</strong><span>No prioritized engineering exception is currently recorded.</span></li>'

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

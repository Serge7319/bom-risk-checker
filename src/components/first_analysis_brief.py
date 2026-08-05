"""Launch Sprint 30.1: first-analysis engineering briefing."""
from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

from src.ui.navigation import navigate_to
from src.ui.cadivor_design_system import cadivor_button_wrap, cadivor_button_wrap_end


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    try:
        if pd.isna(value):
            return fallback
    except Exception:
        pass
    text = str(value).strip()
    return text or fallback


def _risk_reason(row: pd.Series) -> str:
    reasons: list[str] = []
    lifecycle = _text(row.get("Lifecycle Status"), "Unknown")
    lifecycle_lower = lifecycle.lower()
    stock = int(_number(row.get("Stock Available"), 0))
    suppliers = int(_number(row.get("Supplier Count"), 0))
    lead_time = _number(row.get("Lead Time Weeks"), 0)
    raw_reason = _text(row.get("Risk Reasons"))

    if "obsolete" in lifecycle_lower or "eol" in lifecycle_lower:
        reasons.append("lifecycle status requires replacement planning")
    elif "replacement" in lifecycle_lower:
        reasons.append("a replacement is already suggested")
    elif "unknown" in lifecycle_lower:
        reasons.append("lifecycle evidence is incomplete")
    if stock <= 0:
        reasons.append("no recorded stock is available")
    if suppliers <= 1:
        reasons.append("sourcing is concentrated with one or fewer suppliers")
    if lead_time >= 12:
        reasons.append(f"lead time is approximately {lead_time:g} weeks")
    if not reasons and raw_reason:
        reasons.append(raw_reason.rstrip("."))
    return "; ".join(reasons[:3]) or "recorded evidence indicates elevated component risk"


def _recommended_action(row: pd.Series) -> str:
    lifecycle = _text(row.get("Lifecycle Status")).lower()
    stock = int(_number(row.get("Stock Available"), 0))
    suppliers = int(_number(row.get("Supplier Count"), 0))
    has_alternates = bool(row.get("Has Alternates", False))

    if "obsolete" in lifecycle or "eol" in lifecycle or "replacement" in lifecycle:
        return "Validate and qualify a replacement before the next release."
    if stock <= 0:
        return "Confirm availability and open an alternate-source review."
    if suppliers <= 1:
        return "Approve a second source or document the single-source exception."
    if not has_alternates:
        return "Run Alternative Finder and record an engineering recommendation."
    return "Review the supporting evidence and record a component decision."


def _portfolio_message(*, health_score: int, high_count: int, medium_count: int) -> tuple[str, str]:
    if high_count > 0:
        return (
            "Focused intervention required",
            f"{high_count} high-risk component{'s' if high_count != 1 else ''} should be resolved before release. "
            "Start with the ranked priorities below, then document the engineering decision.",
        )
    if medium_count > 0:
        return (
            "Controlled review recommended",
            f"No critical exposure is recorded, but {medium_count} component{'s' if medium_count != 1 else ''} need focused review. "
            "Cadivor recommends closing these evidence gaps before approval.",
        )
    if health_score >= 85:
        return (
            "Ready for a controlled release",
            "No elevated component risk is currently recorded. Confirm the remaining checklist evidence and enable monitoring for future changes.",
        )
    return (
        "Review evidence before release",
        "The BOM is not currently blocked by a critical component, but its overall evidence coverage should be reviewed before approval.",
    )


def render_first_analysis_brief(
    results_df: pd.DataFrame,
    *,
    health_score: int,
    analysis_id: str | None = None,
    project_name: str | None = None,
) -> None:
    """Render an outcome-first briefing before the detailed analysis table."""
    if results_df is None or results_df.empty:
        return

    data = results_df.copy()
    if "Risk Score" not in data.columns:
        data["Risk Score"] = 0
    if "Risk Level" not in data.columns:
        data["Risk Level"] = "Low"

    high_count = int((data["Risk Level"].astype(str).str.lower() == "high").sum())
    medium_count = int((data["Risk Level"].astype(str).str.lower() == "medium").sum())
    attention_count = high_count + medium_count
    no_stock_count = int((pd.to_numeric(data.get("Stock Available", 0), errors="coerce").fillna(0) <= 0).sum())
    single_source_count = int((pd.to_numeric(data.get("Supplier Count", 0), errors="coerce").fillna(0) <= 1).sum())
    title, summary = _portfolio_message(
        health_score=int(health_score or 0),
        high_count=high_count,
        medium_count=medium_count,
    )

    ranked = data.sort_values(by="Risk Score", ascending=False).head(5)
    project = html.escape(_text(project_name, "BOM analysis"))

    st.markdown(
        """
        <style id="cadivor-first-brief-301">
        .cv301-shell{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff 0%,#f8fbff 62%,#eef6ff 100%);border-radius:24px;padding:22px;margin:12px 0 18px;box-shadow:0 18px 45px rgba(15,23,42,.065)}
        .cv301-kicker{font-size:10px;font-weight:950;letter-spacing:.1em;text-transform:uppercase;color:#2563eb!important;margin-bottom:7px}
        .cv301-title{font-size:28px;line-height:1.08;font-weight:950;letter-spacing:-.035em;color:#0f172a!important;margin:0 0 8px}
        .cv301-copy{font-size:13px;font-weight:620;line-height:1.55;color:#475569!important;max-width:900px;margin:0}
        .cv301-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:17px}
        .cv301-stat{border:1px solid #dbeafe;background:rgba(255,255,255,.92);border-radius:15px;padding:13px}
        .cv301-stat span{display:block;font-size:9px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;color:#64748b!important;margin-bottom:5px}
        .cv301-stat strong{display:block;font-size:22px;line-height:1;font-weight:950;color:#0f172a!important}
        .cv301-priority{border:1px solid #e2e8f0;background:#fff;border-radius:16px;padding:13px 14px;margin:8px 0}
        .cv301-priority-top{display:flex;align-items:center;justify-content:space-between;gap:12px}
        .cv301-mpn{font-size:13px;font-weight:950;color:#0f172a!important}
        .cv301-score{font-size:10px;font-weight:900;color:#b45309!important;background:#fffbeb;border:1px solid #fde68a;border-radius:999px;padding:5px 8px;white-space:nowrap}
        .cv301-meta{font-size:10px;font-weight:750;color:#64748b!important;margin-top:3px}
        .cv301-reason{font-size:11px;font-weight:650;color:#334155!important;line-height:1.45;margin-top:8px}
        .cv301-action{font-size:11px;font-weight:850;color:#1d4ed8!important;line-height:1.4;margin-top:6px}
        @media(max-width:900px){.cv301-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <section class="cv301-shell">
          <div class="cv301-kicker">Cadivor engineering brief · {project}</div>
          <h2 class="cv301-title">{html.escape(title)}</h2>
          <p class="cv301-copy">{html.escape(summary)}</p>
          <div class="cv301-grid">
            <div class="cv301-stat"><span>Health</span><strong>{int(health_score or 0)}/100</strong></div>
            <div class="cv301-stat"><span>Needs review</span><strong>{attention_count}</strong></div>
            <div class="cv301-stat"><span>No-stock parts</span><strong>{no_stock_count}</strong></div>
            <div class="cv301-stat"><span>Single-source</span><strong>{single_source_count}</strong></div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("Review these components first")
    st.caption("Ranked by recorded risk score and release impact.")

    if attention_count == 0:
        st.success("No high- or medium-risk components are recorded. Continue monitoring lifecycle, stock, and supplier changes.")
    else:
        for index, (_, row) in enumerate(ranked.iterrows(), start=1):
            risk_level = _text(row.get("Risk Level"), "Review")
            if risk_level.lower() == "low" and index > attention_count:
                continue
            mpn = html.escape(_text(row.get("MPN"), "Unknown part"))
            manufacturer = html.escape(_text(row.get("Manufacturer"), "Manufacturer not recorded"))
            score = int(round(_number(row.get("Risk Score"), 0)))
            reason = html.escape(_risk_reason(row))
            action = html.escape(_recommended_action(row))
            st.markdown(
                f"""
                <div class="cv301-priority">
                  <div class="cv301-priority-top">
                    <div><div class="cv301-mpn">{index}. {mpn}</div><div class="cv301-meta">{manufacturer} · {html.escape(risk_level)} risk</div></div>
                    <div class="cv301-score">{score}/100</div>
                  </div>
                  <div class="cv301-reason"><strong>Why it matters:</strong> {reason}.</div>
                  <div class="cv301-action">Recommended next step: {action}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    action_left, action_mid, action_right = st.columns([1.1, 1.1, 2.2])
    with action_left:
        cadivor_button_wrap("primary")
        if st.button("Start engineering review", type="primary", use_container_width=True, key="first_brief_review"):
            if analysis_id:
                try:
                    st.query_params["page"] = "Analysis Detail"
                    st.query_params["analysis_id"] = str(analysis_id)
                except Exception:
                    st.experimental_set_query_params(page="Analysis Detail", analysis_id=str(analysis_id))
                st.rerun()
            else:
                st.info("Save the analysis to begin the engineering review.")
        cadivor_button_wrap_end()
    with action_mid:
        cadivor_button_wrap("secondary")
        if st.button("Open Alternative Finder", use_container_width=True, key="first_brief_alternatives"):
            navigate_to("Alternative Finder")
        cadivor_button_wrap_end()

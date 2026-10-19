"""Launch Sprint 30.1: first-analysis engineering briefing."""
from __future__ import annotations

import html
from typing import Any

import pandas as pd
import streamlit as st

from src.ui.navigation import navigate_to_alternative_finder


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
    if _text(row.get("Risk Level")).casefold() == "needs verification":
        recorded_reason = _text(row.get("Risk Reasons"))
        return recorded_reason.rstrip(".") or (
            "Supplier evidence is insufficient to rate this component; confirm the part match."
        )

    reasons: list[str] = []
    lifecycle = _text(row.get("Lifecycle Status"), "Unknown")
    lifecycle_lower = lifecycle.lower()
    stock_value = row.get("Stock Available")
    stock_known = pd.notna(stock_value) and bool(row.get("Supplier Data Verified", True))
    stock = int(_number(stock_value, 0)) if stock_known else None
    supplier_value = row.get("Supplier Count")
    suppliers = int(_number(supplier_value, 0)) if pd.notna(supplier_value) else None
    lead_value = row.get("Lead Time Weeks")
    lead_time = _number(lead_value, 0) if pd.notna(lead_value) else None
    raw_reason = _text(row.get("Risk Reasons"))

    if "obsolete" in lifecycle_lower or "eol" in lifecycle_lower:
        reasons.append("lifecycle status requires replacement planning")
    elif "replacement" in lifecycle_lower:
        reasons.append("a replacement is already suggested")
    elif "unknown" in lifecycle_lower:
        reasons.append("lifecycle evidence is incomplete")
    if stock == 0:
        reasons.append("checked suppliers reported no on-hand stock")
    elif stock is None:
        reasons.append("on-hand stock was not reported")
    if suppliers == 1:
        reasons.append("only one checked supplier lists the part")
    if lead_time is not None and lead_time >= 12:
        reasons.append(f"lead time is approximately {lead_time:g} weeks")
    if not reasons and raw_reason:
        reasons.append(raw_reason.rstrip("."))
    return "; ".join(reasons[:3]) or "recorded evidence indicates elevated component risk"


def _recommended_action(row: pd.Series) -> str:
    lifecycle = _text(row.get("Lifecycle Status")).lower()
    stock_value = row.get("Stock Available")
    stock = int(_number(stock_value, 0)) if pd.notna(stock_value) else None
    supplier_value = row.get("Supplier Count")
    suppliers = int(_number(supplier_value, 0)) if pd.notna(supplier_value) else None
    has_alternates = _text(row.get("Has Alternates")).casefold() in {"true", "1", "yes"}

    if "obsolete" in lifecycle or "eol" in lifecycle or "replacement" in lifecycle:
        return "Validate and qualify a replacement before the next release."
    if not bool(row.get("Supplier Data Verified", True)):
        return "Verify the part match and supplier evidence before making a sourcing decision."
    if stock == 0:
        return "Confirm availability and open an alternate-source review."
    if suppliers == 1:
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
    health_score: int | None,
    analysis_id: str | None = None,
    project_name: str | None = None,
) -> set[str]:
    """Render ranked parts with their supporting evidence in the same card."""
    if results_df is None or results_df.empty:
        return set()

    data = results_df.copy()
    if "Risk Score" not in data.columns:
        data["Risk Score"] = 0
    if "Risk Level" not in data.columns:
        data["Risk Level"] = "Low"

    normalized_levels = data["Risk Level"].astype(str).str.casefold()
    high_count = int((normalized_levels == "high").sum())
    medium_count = int((normalized_levels == "medium").sum())
    needs_verification_count = int((normalized_levels == "needs verification").sum())
    attention_count = high_count + medium_count
    stock_values = pd.to_numeric(
        data.get("Stock Available", pd.Series(index=data.index, dtype=float)),
        errors="coerce",
    )
    stock_verified = data.get(
        "Supplier Data Verified",
        pd.Series(False, index=data.index),
    ).fillna(False).astype(str).str.casefold().isin({"true", "1", "yes"})
    no_stock_count = int((stock_values.eq(0) & stock_verified).sum())

    title, summary = _portfolio_message(
        health_score=int(health_score or 0),
        high_count=high_count,
        medium_count=medium_count,
    )
    if needs_verification_count:
        total_count = len(data)
        assessed_count = max(0, total_count - needs_verification_count)
        component_label = "component" if total_count == 1 else "components"
        unassessed_verb = "remains" if needs_verification_count == 1 else "remain"
        title = "Supplier evidence incomplete"
        if high_count:
            rated_risk = (
                f"{high_count} assessed component{'s' if high_count != 1 else ''} "
                f"{'are' if high_count != 1 else 'is'} high risk"
                + (f" and {medium_count} need focused review" if medium_count else "")
                + ". "
            )
        elif medium_count:
            rated_risk = (
                f"{medium_count} assessed component{'s' if medium_count != 1 else ''} "
                f"{'need' if medium_count != 1 else 'needs'} focused review. "
            )
        else:
            rated_risk = ""
        summary = (
            f"{rated_risk}Enough matched supplier evidence is available to rate "
            f"{assessed_count} of {total_count} BOM {component_label}; "
            f"{needs_verification_count} {unassessed_verb} unassessed. "
            "The BOM's overall exposure cannot be confirmed until those evidence gaps are resolved."
        )

    risk_health_display = (
        "Needs verification"
        if needs_verification_count
        else f"{int(health_score)}/100" if health_score is not None else "—"
    )
    project = html.escape(_text(project_name, "BOM analysis"))
    priority_rows = data.loc[
        normalized_levels.isin({"high", "medium", "needs verification"})
    ].sort_values(by="Risk Score", ascending=False).head(5)

    st.markdown(
        """
        <style id="cadivor-first-brief-301" data-cadivor-layout-style="true">
        .cv301-shell{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff 0%,#f8fbff 62%,#eef6ff 100%);border-radius:24px;padding:22px;margin:12px 0 18px;box-shadow:0 18px 45px rgba(15,23,42,.065)}
        .cv301-kicker{font-size:10px;font-weight:950;letter-spacing:.1em;text-transform:uppercase;color:#2563eb!important;margin-bottom:7px}
        .cv301-title{font-size:28px;line-height:1.08;font-weight:950;letter-spacing:-.035em;color:#0f172a!important;margin:0 0 8px}
        .cv301-copy{font-size:13px;font-weight:620;line-height:1.55;color:#475569!important;max-width:900px;margin:0}
        .cv301-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:17px}
        .cv301-stat{border:1px solid #dbeafe;background:rgba(255,255,255,.92);border-radius:15px;padding:13px}
        .cv301-stat span{display:block;font-size:9px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;color:#64748b!important;margin-bottom:5px}
        .cv301-stat strong{display:block;font-size:22px;line-height:1;font-weight:950;color:#0f172a!important;overflow-wrap:anywhere}
        .cv301-priority{border:1px solid #e2e8f0;background:#fff;border-radius:16px;padding:14px 15px;margin:9px 0}
        .cv301-priority-top{display:flex;align-items:center;justify-content:space-between;gap:12px}
        .cv301-mpn{font-size:13px;font-weight:850;color:#0f172a!important;overflow-wrap:anywhere}
        .cv301-score{font-size:10px;font-weight:800;color:#334155!important;background:#f8fafc;border:1px solid #dbe3ed;border-radius:999px;padding:5px 8px;white-space:nowrap}
        .cv301-score.high{color:#b91c1c!important;background:#fef2f2;border-color:#fecaca}
        .cv301-score.medium{color:#a16207!important;background:#fffbeb;border-color:#fde68a}
        .cv301-score.unverified{color:#92400e!important;background:#fff7ed;border-color:#fed7aa}
        .cv301-meta{font-size:10px;font-weight:700;color:#64748b!important;margin-top:3px}
        .cv301-reason{font-size:11px;font-weight:600;color:#334155!important;line-height:1.45;margin-top:8px}
        .cv301-action{font-size:11px;font-weight:750;color:#1d4ed8!important;line-height:1.4;margin-top:6px}
        .cv301-details{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:12px}
        .cv301-detail{min-width:0;padding:8px 9px;background:#f8fafc;border:1px solid #edf1f6;border-radius:9px}
        .cv301-detail span{display:block;color:#64748b!important;font-size:9px;font-weight:750;letter-spacing:.035em;text-transform:uppercase;margin-bottom:3px}
        .cv301-detail strong{display:block;color:#334155!important;font-size:10px;font-weight:650;line-height:1.35;overflow-wrap:anywhere}
        .st-key-cv301_actions [data-testid="stColumn"]:last-child [data-testid="stVerticalBlock"]{align-items:flex-end!important}
        .st-key-cv301_actions [data-testid="stColumn"]:last-child [data-testid="stElementContainer"]{display:flex!important;justify-content:flex-end!important;width:100%!important}
        @media(max-width:900px){.cv301-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.cv301-details{grid-template-columns:repeat(2,minmax(0,1fr))}}
        @media(max-width:560px){.cv301-shell{padding:18px}.cv301-title{font-size:23px}.cv301-details{grid-template-columns:1fr}}
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
            <div class="cv301-stat"><span>Health</span><strong>{html.escape(risk_health_display)}</strong></div>
            <div class="cv301-stat"><span>{"Rated risks to review" if needs_verification_count else "Needs review"}</span><strong>{attention_count}</strong></div>
            <div class="cv301-stat"><span>No-stock parts</span><strong>{no_stock_count}</strong></div>
            <div class="cv301-stat"><span>Needs verification</span><strong>{needs_verification_count}</strong></div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("Review these components first")
    st.caption("Each card combines the part, the evidence behind its rating, and the recommended next step.")

    if needs_verification_count:
        st.warning(
            f"{needs_verification_count} component(s) cannot be risk-rated yet. "
            "Verify the manufacturer part number and supplier match before relying on the BOM health summary."
        )
    elif attention_count == 0:
        st.success(
            "No high- or medium-risk components are recorded. Continue monitoring lifecycle, stock, and supplier changes."
        )

    reviewed_component_keys: set[str] = set()

    def _component_key(value: Any) -> str:
        return "".join(_text(value).casefold().split())

    for index, (_, row) in enumerate(priority_rows.iterrows(), start=1):
        raw_mpn = _text(row.get("MPN"), "Unknown part")
        for identity_value in (row.get("MPN"), row.get("Normalized MPN")):
            key = _component_key(identity_value)
            if key:
                reviewed_component_keys.add(key)

        risk_level = _text(row.get("Risk Level"), "Review")
        manufacturer = html.escape(_text(row.get("Manufacturer"), "Manufacturer not recorded"))
        risk_score = _number(row.get("Risk Score"), default=None)
        score_label = (
            f"{int(round(risk_score))}/100"
            if risk_score is not None and risk_level.casefold() != "needs verification"
            else "Not assessed"
        )
        score_class = (
            "unverified" if risk_level.casefold() == "needs verification"
            else "high" if risk_level.casefold() == "high"
            else "medium" if risk_level.casefold() == "medium"
            else ""
        )
        reason = html.escape(_risk_reason(row))
        action = html.escape(_recommended_action(row))

        is_verified = _text(row.get("Supplier Data Verified")).casefold() in {"true", "1", "yes"}
        stock_value = _number(row.get("Stock Available"), default=None)
        stock_detail = (
            f"{stock_value:g} units reported"
            if is_verified and stock_value is not None
            else "Not reported by matched supplier"
            if is_verified
            else "Not verified"
        )
        lead_time = _number(row.get("Lead Time Weeks"), default=None)
        lead_time_detail = f"{lead_time:g} weeks" if lead_time is not None else "Not reported"
        supplier_count = _number(row.get("Supplier Count"), default=None)
        supplier_detail = (
            f"{int(supplier_count)} supplier(s)"
            if supplier_count is not None
            else "Not verified"
        )
        alternates = _text(row.get("Alternative Part Numbers"))
        alternate_status = _text(row.get("Alternate Search Status"))
        if alternates.casefold() not in {"", "not recorded", "nan", "none", "—"}:
            alternate_detail = f"Candidates: {alternates}"
        else:
            alternate_detail = alternate_status or (
                "Candidates found" if bool(row.get("Has Alternates", False)) else "Not searched"
            )

        quantity_detail = _text(
            row.get("Quantity", row.get("Qty")),
            "Not recorded",
        )
        lifecycle_evidence = _text(
            row.get("Lifecycle Evidence Summary", row.get("Lifecycle Evidence")),
            "Not reported",
        )
        stock_evidence = _text(
            row.get("Stock Evidence", row.get("Sources Available")),
            "Not reported",
        )
        details = (
            ("Lifecycle", _text(row.get("Lifecycle Status"), "Not reported")),
            ("Lifecycle evidence", lifecycle_evidence),
            ("Stock", stock_detail),
            ("Stock source", stock_evidence),
            ("Lead time", lead_time_detail),
            ("Supplier coverage", _text(row.get("Supplier Coverage"), "Not reported")),
            ("Supplier matches", supplier_detail),
            ("Quantity", quantity_detail),
            ("Alternatives", alternate_detail),
        )
        detail_html = "".join(
            f'<div class="cv301-detail"><span>{html.escape(label)}</span>'
            f"<strong>{html.escape(value)}</strong></div>"
            for label, value in details
        )
        st.markdown(
            f"""
            <section class="cv301-priority">
              <div class="cv301-priority-top">
                <div><div class="cv301-mpn">{index}. {html.escape(raw_mpn)}</div>
                <div class="cv301-meta">{manufacturer} · {html.escape(risk_level)}</div></div>
                <div class="cv301-score {score_class}">{html.escape(score_label)}</div>
              </div>
              <div class="cv301-reason"><strong>Why it matters:</strong> {reason}.</div>
              <div class="cv301-action">Recommended next step: {action}</div>
              <div class="cv301-details">{detail_html}</div>
            </section>
            """,
            unsafe_allow_html=True,
        )

    with st.container(key="cv301_actions"):
        spacer, action_col = st.columns([4, 2], vertical_alignment="center")
        with action_col:
            if st.button(
                "Open Alternative Finder",
                key="first_brief_alternatives",
                type="secondary",
                use_container_width=True,
            ):
                navigate_to_alternative_finder(source_page="first_analysis_brief")

    return reviewed_component_keys

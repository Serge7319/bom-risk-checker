"""Concise BOM analysis result summary for the first review screen."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st


def render_first_analysis_brief(
    results_df: pd.DataFrame,
    *,
    health_score: int | None,
    analysis_id: str | None = None,
    project_name: str | None = None,
) -> set[str]:
    """Render the approved two-group summary without changing analysis data.

    Detailed supplier, lifecycle, and stock evidence remains in the existing
    component register and its expanders below this summary.
    """
    del health_score, analysis_id, project_name  # retained for caller compatibility
    if results_df is None or results_df.empty:
        return set()

    levels = results_df.get(
        "Risk Level", pd.Series("Needs verification", index=results_df.index)
    ).astype(str).str.strip().str.casefold()
    total = len(results_df)
    verify_count = int((levels == "needs verification").sum())
    rated_count = max(0, total - verify_count)
    high_count = int((levels == "high").sum())
    medium_count = int((levels == "medium").sum())
    low_count = int((levels == "low").sum())

    badges: list[str] = []
    for count, label, style in (
        (high_count, "high risk", "high"),
        (medium_count, "medium risk", "medium"),
        (low_count, "low risk", "low"),
    ):
        if count:
            badges.append(
                f'<span class="cvres-badge {style}">{count} {label}</span>'
            )
    if not badges:
        badges.append('<span class="cvres-badge neutral">No rated components</span>')

    rated_detail = (
        f"{rated_count} component{'s' if rated_count != 1 else ''} "
        f"{'have' if rated_count != 1 else 'has'} matched supplier data"
    )
    verify_detail = (
        f"{verify_count} component{'s' if verify_count != 1 else ''} "
        f"{'need' if verify_count != 1 else 'needs'} verification"
        if verify_count
        else "No components currently need verification"
    )
    rated_evidence = (
        f"Supplier data is available for {rated_count} component"
        f"{'s' if rated_count != 1 else ''}"
        if rated_count
        else "No matched supplier data is available yet"
    )
    verification_evidence = (
        "Supplier or part-number match incomplete"
        if verify_count
        else "Supplier evidence is available for every component"
    )
    verification_badge = (
        f'<span class="cvres-badge neutral">{verify_count} not rated</span>'
        if verify_count
        else '<span class="cvres-badge low">All rated</span>'
    )
    verification_action = "Verify part data" if verify_count else "Review component evidence"

    st.markdown(
        """
        <style id="cadivor-bom-results-summary" data-cadivor-layout-style="true">
        .cvres-section{margin:5px 0 0}
        .cvres-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin:0 0 12px}
        .cvres-head h2{margin:0;color:#172438!important;font-size:18px;font-weight:650;letter-spacing:-.02em}
        .cvres-head p{margin:4px 0 0;color:#66758b!important;font-size:12px}
        .cvres-count{display:inline-flex;align-items:center;min-height:26px;padding:0 9px;border:1px solid #e1e7f0;border-radius:7px;color:#46566e!important;background:#fff;font-size:12px;white-space:nowrap}
        .cvres-table-wrap{overflow:hidden;border:1px solid #e1e7f0;border-radius:12px;background:#fff}
        .cvres-table{width:100%;border-collapse:collapse;text-align:left}
        .cvres-table th{padding:12px 16px;color:#617087!important;background:#f8fafd;font-size:11px;font-weight:650;letter-spacing:.055em;text-transform:uppercase}
        .cvres-table td{padding:15px 16px;border-top:1px solid #e9edf3;color:#40516a!important;font-size:13px;vertical-align:middle}
        .cvres-table td:first-child{color:#172438!important}
        .cvres-group{display:flex;align-items:center;gap:11px;font-weight:650}
        .cvres-icon{display:grid;flex:0 0 34px;width:34px;height:34px;place-items:center;border-radius:9px;color:#496b9f!important;background:#edf3fc;font-size:17px}
        .cvres-group small{display:block;margin-top:3px;color:#66758b!important;font-size:12px;font-weight:400}
        .cvres-badges{display:flex;align-items:center;gap:5px;flex-wrap:wrap}
        .cvres-badge{display:inline-flex;align-items:center;min-height:26px;padding:0 9px;border-radius:7px;font-size:12px;font-weight:650;white-space:nowrap}
        .cvres-badge.high{color:#b42318!important;background:#fff0ed}
        .cvres-badge.medium{color:#9a5c08!important;background:#fff7e7}
        .cvres-badge.low{color:#187145!important;background:#eaf7ef}
        .cvres-badge.neutral{color:#58677c!important;background:#eef1f5}
        .cvres-link{display:inline-flex;align-items:center;gap:6px;color:#1f56d3!important;text-decoration:none!important;font-size:13px;font-weight:650;white-space:nowrap}
        .cvres-link:hover{text-decoration:underline!important}
        .cvres-foot{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:12px 16px;border-top:1px solid #e1e7f0;color:#66758b!important;background:#fbfcfe;font-size:12px}
        .cvres-foot strong{color:#172438!important;font-weight:650}
        .cvres-foot-note{display:flex;align-items:flex-start;gap:8px;margin-top:14px;color:#66758b!important;font-size:12px;line-height:1.5}
        @media(max-width:800px){.cvres-table-wrap{overflow-x:auto}.cvres-table{min-width:740px}.cvres-foot{align-items:flex-start;flex-direction:column}}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <section class="cvres-section" aria-labelledby="cvres-title">
          <div class="cvres-head">
            <div><h2 id="cvres-title">Component review</h2>
              <p>Prioritized by the action needed to complete this analysis.</p></div>
            <span class="cvres-count">{total} components</span>
          </div>
          <div class="cvres-table-wrap">
            <table class="cvres-table" aria-label="BOM component review summary">
              <thead><tr><th>Component group</th><th>Supplier evidence</th><th>Risk status</th><th>Recommended next step</th></tr></thead>
              <tbody>
                <tr>
                  <td><div class="cvres-group"><span class="cvres-icon" aria-hidden="true">▦</span><span>Rated components<small>{html.escape(rated_detail)}</small></span></div></td>
                  <td>{html.escape(rated_evidence)}</td>
                  <td><div class="cvres-badges">{''.join(badges)}</div></td>
                  <td><a class="cvres-link" href="#detailed-risk-report">Review evidence <span aria-hidden="true">→</span></a></td>
                </tr>
                <tr>
                  <td><div class="cvres-group"><span class="cvres-icon" aria-hidden="true">⌕</span><span>Components needing verification<small>{html.escape(verify_detail)}</small></span></div></td>
                  <td>{html.escape(verification_evidence)}</td>
                  <td>{verification_badge}</td>
                  <td><a class="cvres-link" href="#detailed-risk-report">{verification_action} <span aria-hidden="true">→</span></a></td>
                </tr>
              </tbody>
            </table>
            <div class="cvres-foot"><span>Supplier evidence is shown at the component level in <strong>Engineering Intelligence</strong>.</span><span>2 review groups</span></div>
          </div>
          <div class="cvres-foot-note"><span aria-hidden="true">ⓘ</span><span>The saved analysis remains available while you verify supplier data and update the BOM.</span></div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    return set()

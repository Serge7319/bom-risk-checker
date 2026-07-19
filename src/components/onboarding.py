"""Launch-focused first-time experience components for Cadivor Sprint 29.0B."""
from __future__ import annotations

import html
from typing import Any

import pandas as pd

import streamlit as st

from src.services.customer_progress import build_activation_progress, next_activation_action


def _first_name(current_user: dict[str, Any] | None) -> str:
    current_user = current_user or {}
    name = str(current_user.get("full_name") or current_user.get("name") or "").strip()
    if name:
        return name.split()[0]
    email = str(current_user.get("email") or "").strip()
    return email.split("@")[0].replace(".", " ").title() if email else "there"


def _go_to(page: str) -> None:
    """Navigate through Cadivor's query-parameter router."""
    try:
        st.query_params["page"] = page
    except Exception:
        st.experimental_set_query_params(page=page)
    st.rerun()


def _render_setup_checklist(*, analyses_count: int = 0, has_review: bool = False, has_report: bool = False) -> None:
    """Render live activation progress with compact, reliably aligned action links."""
    from urllib.parse import quote

    progress = build_activation_progress(analyses_count=analyses_count, has_review=has_review, has_report=has_report)
    rows = [
        ("Create account", progress.account_created, None, None),
        ("Upload first BOM", progress.first_bom, "Upload", "BOM Analyzer"),
        ("Complete first analysis", progress.first_analysis, "Analyze", "BOM Analyzer"),
        ("Review a recommendation", progress.first_review, "Review", "Engineering Decisions"),
        ("Export first report", progress.first_report, "Export", "Reports"),
    ]

    row_html = []
    for label, done, action_label, page in rows:
        status_class = "done" if done else "open"
        icon = "✓" if done else "○"
        action = ""
        if not done and action_label and page:
            href = f"?page={quote(str(page))}"
            action = f'<a class="cv30b-check-action" href="{href}" target="_self">{html.escape(action_label)}</a>'
        row_html.append(
            f'<div class="cv30b-check-row {status_class}">'
            f'<div class="cv30b-check-label"><span class="cv30b-check-icon">{icon}</span><span>{html.escape(label)}</span></div>'
            f'{action}</div>'
        )

    st.markdown(
        f"""
        <style id="cadivor-checklist-30b-fix">
        .cv30b-check-head{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}}
        .cv30b-check-head strong{{color:#0f172a!important;font-size:13px;font-weight:850}}
        .cv30b-check-head span{{color:#64748b!important;font-size:11px;font-weight:750}}
        .cv30b-check-track{{height:7px;background:#eef2f7;border-radius:999px;overflow:hidden;margin-bottom:12px}}
        .cv30b-check-fill{{height:100%;width:{max(0,min(100,progress.percent))}%;background:#2563eb;border-radius:999px}}
        .cv30b-check-list{{display:flex;flex-direction:column;gap:8px}}
        .cv30b-check-row{{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:42px;padding:7px 8px 7px 3px;border-bottom:1px solid #eef2f7}}
        .cv30b-check-row:last-child{{border-bottom:0}}
        .cv30b-check-label{{display:flex;align-items:center;gap:8px;min-width:0;color:#0f172a!important;font-size:12px;font-weight:720;line-height:1.25}}
        .cv30b-check-icon{{width:20px;height:20px;flex:0 0 20px;border-radius:7px;display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:900}}
        .cv30b-check-row.done .cv30b-check-icon{{background:#dcfce7;color:#15803d!important}}
        .cv30b-check-row.open .cv30b-check-icon{{background:#f8fafc;border:1px solid #cbd5e1;color:#64748b!important}}
        .cv30b-check-action{{display:inline-flex!important;align-items:center;justify-content:center;flex:0 0 auto;min-width:82px;height:34px;padding:0 13px;border:1px solid #93a8c5;border-radius:10px;background:#fff;color:#1d4ed8!important;text-decoration:none!important;font-size:12px;font-weight:800;box-sizing:border-box}}
        .cv30b-check-action:hover{{border-color:#2563eb;background:#eff6ff;color:#1d4ed8!important}}
        @media(max-width:700px){{.cv30b-check-row{{align-items:flex-start}}.cv30b-check-action{{min-width:72px}}}}
        </style>
        <div class="cv30b-check-head"><strong>Setup progress</strong><span>{progress.completed}/{progress.total} complete</span></div>
        <div class="cv30b-check-track"><div class="cv30b-check-fill"></div></div>
        <div class="cv30b-check-list">{''.join(row_html)}</div>
        """,
        unsafe_allow_html=True,
    )


def render_first_run_dashboard(*, current_user: dict[str, Any] | None, workspace_name: str | None = None) -> None:
    """Render the launch onboarding and a live customer-activation checklist."""
    name = _first_name(current_user)
    workspace = str(workspace_name or "Cadivor Workspace")
    st.markdown(
        """
        <style id="cadivor-ftue-native-30a">
        .cv30-eyebrow{display:inline-flex;border:1px solid #bfdbfe;background:#eff6ff;color:#1d4ed8!important;border-radius:999px;padding:7px 11px;font-size:11px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;margin-bottom:12px}
        .cv30-hero [data-testid="stVerticalBlockBorderWrapper"]{border:1px solid #bfdbfe!important;border-radius:24px!important;background:linear-gradient(135deg,#fff 0%,#f8fbff 58%,#eaf3ff 100%)!important;box-shadow:0 20px 50px rgba(15,23,42,.07)!important;padding:18px!important}
        .cv30-step [data-testid="stVerticalBlockBorderWrapper"]{min-height:146px;border-radius:17px!important;border:1px solid #e2e8f0!important;background:#fff!important;transition:transform .16s ease,box-shadow .16s ease}
        .cv30-step [data-testid="stVerticalBlockBorderWrapper"]:hover{transform:translateY(-2px);box-shadow:0 12px 28px rgba(15,23,42,.07)}
        .cv30-number{width:30px;height:30px;border-radius:10px;background:#eff6ff;border:1px solid #bfdbfe;color:#1d4ed8!important;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:950;margin-bottom:10px}
        [data-testid="stHeaderActionElements"], a.header-anchor, .stMarkdown h1 a, .stMarkdown h2 a, .stMarkdown h3 a{display:none!important}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="cv30-hero">', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="cv30-eyebrow">Engineering Decision Intelligence</div>', unsafe_allow_html=True)
        st.title(f"Welcome, {name}.")
        st.markdown("Upload a BOM and identify lifecycle, inventory, supplier, and engineering risks—then move directly into a guided decision workflow.")
        primary, secondary, _ = st.columns([1.05, 1, 2.1])
        with primary:
            if st.button("Upload my first BOM →", type="primary", use_container_width=True, key="ftue_upload_first_bom"):
                _go_to("BOM Analyzer")
        with secondary:
            if st.button("See how it works", use_container_width=True, key="ftue_explore_workflow"):
                st.session_state["show_ftue_workflow"] = not st.session_state.get("show_ftue_workflow", False)
    st.markdown('</div>', unsafe_allow_html=True)

    if st.session_state.get("show_ftue_workflow"):
        with st.expander("Cadivor workflow", expanded=True):
            st.write("**1. Upload** a CSV or XLSX BOM.")
            st.write("**2. Analyze** lifecycle, stock, supplier, and lead-time evidence.")
            st.write("**3. Review** priority components and record engineering decisions.")
            st.write("**4. Share** an executive-ready report and enable monitoring.")

    st.subheader("Your first decision in four steps")
    steps = [
        ("1", "Upload", "Import a CSV or XLSX BOM."),
        ("2", "Understand risk", "See the evidence that matters first."),
        ("3", "Make decisions", "Review alternatives and record approvals."),
        ("4", "Share the outcome", "Export an executive-ready report."),
    ]
    for column, (number, title, copy) in zip(st.columns(4), steps):
        with column:
            st.markdown('<div class="cv30-step">', unsafe_allow_html=True)
            with st.container(border=True):
                st.markdown(f'<div class="cv30-number">{number}</div>', unsafe_allow_html=True)
                st.markdown(f"**{title}**")
                st.caption(copy)
            st.markdown('</div>', unsafe_allow_html=True)

    left, right = st.columns([1.7, 1])
    with left:
        with st.container(border=True):
            st.subheader("Get your first result in under five minutes")
            st.write("Use your production BOM or start with a small Cadivor sample. Your analysis is saved so you can return to it later.")
            st.caption("Supported formats: CSV and XLSX · Typical first analysis: under 5 minutes")
            primary_action, sample_action = st.columns([1.1, 1])
            with primary_action:
                if st.button("Upload my BOM", type="primary", key="ftue_start_analysis", use_container_width=True):
                    _go_to("BOM Analyzer")
            with sample_action:
                sample_bom = pd.DataFrame([
                    {"Part Number": "LM2596S-5.0", "Manufacturer": "Texas Instruments", "Quantity": 2},
                    {"Part Number": "PC817", "Manufacturer": "Sharp", "Quantity": 4},
                    {"Part Number": "MCP2551", "Manufacturer": "Microchip", "Quantity": 1},
                    {"Part Number": "PIC18F46K22", "Manufacturer": "Microchip", "Quantity": 1},
                    {"Part Number": "BZXS5C5V1", "Manufacturer": "Diodes Incorporated", "Quantity": 3},
                ])
                st.download_button(
                    "Download sample BOM",
                    data=sample_bom.to_csv(index=False).encode("utf-8"),
                    file_name="cadivor_sample_bom.csv",
                    mime="text/csv",
                    key="ftue_download_sample_bom",
                    use_container_width=True,
                )
    with right:
        with st.container(border=True):
            st.subheader(workspace)
            _render_setup_checklist()


def render_activation_strip(*, analyses_count: int, has_review: bool = False, has_report: bool = False) -> None:
    """Show a live activation card with the next recommended customer action."""
    progress = build_activation_progress(analyses_count=analyses_count, has_review=has_review, has_report=has_report)
    action = next_activation_action(progress)
    with st.container(border=True):
        left, right = st.columns([3, 1])
        with left:
            st.markdown(f"### {action['title']}")
            st.caption(action["copy"])
            st.progress(progress.percent / 100, text=f"Customer setup · {progress.completed}/{progress.total} complete")
        with right:
            st.write("")
            if st.button(action["button"], type="primary", use_container_width=True, key="activation_next_action"):
                _go_to(action["page"])
        with st.expander("View setup checklist"):
            _render_setup_checklist(analyses_count=analyses_count, has_review=has_review, has_report=has_report)

def render_upload_detected(*, filename: str, component_count: int, deduplicated_count: int | None = None) -> None:
    """Confirm that the uploaded BOM was parsed before analysis starts."""
    original = max(0, int(component_count or 0))
    unique = max(0, int(deduplicated_count if deduplicated_count is not None else original))
    duplicate_note = (
        f"{original - unique} duplicate row(s) consolidated"
        if original > unique
        else "No duplicate part numbers detected"
    )
    st.markdown(
        f"""
        <style id="cadivor-upload-detected-29b">
        .cv29b-detected{{display:grid;grid-template-columns:auto 1fr auto;gap:14px;align-items:center;border:1px solid #BBF7D0;background:linear-gradient(135deg,#FFFFFF,#F0FDF4);border-radius:17px;padding:14px 16px;margin:10px 0 16px}}
        .cv29b-detected-icon{{width:38px;height:38px;border-radius:12px;background:#DCFCE7;color:#15803D!important;display:flex;align-items:center;justify-content:center;font-size:19px;font-weight:950}}
        .cv29b-detected strong{{display:block;color:#0F172A!important;font-size:14px;font-weight:900}}
        .cv29b-detected small{{display:block;color:#64748B!important;font-size:11px;font-weight:650;margin-top:3px}}
        .cv29b-detected-count{{text-align:right}}.cv29b-detected-count b{{display:block;color:#15803D!important;font-size:23px;font-weight:950;line-height:1}}.cv29b-detected-count span{{color:#64748B!important;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.07em}}
        </style>
        <section class="cv29b-detected"><div class="cv29b-detected-icon">✓</div><div><strong>{html.escape(str(filename or 'Uploaded BOM'))} is ready</strong><small>{html.escape(duplicate_note)}. Review the preview, then run the analysis.</small></div><div class="cv29b-detected-count"><b>{unique}</b><span>components</span></div></section>
        """,
        unsafe_allow_html=True,
    )


def render_analysis_success(*, project_name: str, total_parts: int, high_count: int, medium_count: int, health_score: int, analysis_id: str) -> None:
    """Render an outcome-focused transition after a BOM is analyzed and saved."""
    review_count = max(0, int(high_count or 0)) + max(0, int(medium_count or 0))
    estimated_minutes = max(2, min(15, review_count * 2 if review_count else 2))
    recommendation = (
        "Resolve critical components before release." if high_count else
        "Complete a focused review before release." if medium_count else
        "No elevated component risks were detected."
    )
    detail_url = f"?page=Analysis%20Detail&analysis_id={html.escape(str(analysis_id), quote=True)}"
    st.markdown(
        f"""
        <style id="cadivor-analysis-success-29b">
        .cv29b-success{{position:relative;overflow:hidden;border:1px solid #A7F3D0;background:linear-gradient(135deg,#FFFFFF 0%,#F0FDF4 58%,#ECFDF5 100%);border-radius:25px;padding:24px;box-shadow:0 20px 48px rgba(5,150,105,.09);margin:12px 0 18px}}
        .cv29b-success-top{{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}}
        .cv29b-success-kicker{{color:#047857!important;font-size:10px;font-weight:950;letter-spacing:.1em;text-transform:uppercase;margin-bottom:7px}}
        .cv29b-success h2{{color:#0F172A!important;font-size:27px;font-weight:950;letter-spacing:-.035em;margin:0 0 7px}}
        .cv29b-success p{{color:#475569!important;font-size:13px;font-weight:650;line-height:1.55;margin:0}}
        .cv29b-success-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:17px 0}}
        .cv29b-success-stat{{border:1px solid #D1FAE5;background:rgba(255,255,255,.92);border-radius:15px;padding:13px}}
        .cv29b-success-stat span{{display:block;color:#64748B!important;font-size:9px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;margin-bottom:6px}}
        .cv29b-success-stat strong{{display:block;color:#0F172A!important;font-size:22px;font-weight:950}}
        .cv29b-success-actions{{display:flex;gap:9px;flex-wrap:wrap}}
        .cv29b-success-btn{{display:inline-flex;text-decoration:none!important;border-radius:12px;padding:11px 14px;border:1px solid #059669;background:#059669;color:#FFFFFF!important;font-size:12px;font-weight:900}}
        .cv29b-success-btn.secondary{{background:#FFFFFF;color:#047857!important;border-color:#A7F3D0}}
        @media(max-width:780px){{.cv29b-success-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.cv29b-success-top{{display:block}}}}
        </style>
        <section class="cv29b-success"><div class="cv29b-success-top"><div><div class="cv29b-success-kicker">Analysis complete</div><h2>{html.escape(str(project_name or 'BOM analysis'))}</h2><p>{html.escape(recommendation)}</p></div></div><div class="cv29b-success-grid"><div class="cv29b-success-stat"><span>Health</span><strong>{int(health_score or 0)}/100</strong></div><div class="cv29b-success-stat"><span>Components</span><strong>{int(total_parts or 0)}</strong></div><div class="cv29b-success-stat"><span>Needs review</span><strong>{review_count}</strong></div><div class="cv29b-success-stat"><span>Estimated review</span><strong>{estimated_minutes} min</strong></div></div><div class="cv29b-success-actions"><a class="cv29b-success-btn" href="{detail_url}" target="_self">Open engineering review →</a><a class="cv29b-success-btn secondary" href="?page=Reports&analysis_id={html.escape(str(analysis_id), quote=True)}" target="_self">Generate report</a></div></section>
        """,
        unsafe_allow_html=True,
    )

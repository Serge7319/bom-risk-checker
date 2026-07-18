"""Launch-focused first-time experience components for Cadivor Sprint 29.0B."""
from __future__ import annotations

import html
from typing import Any

import streamlit as st


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


def render_first_run_dashboard(*, current_user: dict[str, Any] | None, workspace_name: str | None = None) -> None:
    """Render a reliable native-Streamlit first-run experience.

    Native Streamlit elements are used here intentionally so global application
    CSS cannot hide the onboarding content.
    """
    name = _first_name(current_user)
    workspace = str(workspace_name or "Your workspace")

    st.markdown(
        """
        <style id="cadivor-ftue-native-29e">
        .cv29e-eyebrow{display:inline-flex;border:1px solid #bfdbfe;background:#eff6ff;color:#1d4ed8!important;border-radius:999px;padding:7px 11px;font-size:11px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;margin-bottom:10px}
        .cv29e-welcome [data-testid="stVerticalBlockBorderWrapper"]{border:1px solid #bfdbfe!important;border-radius:26px!important;background:linear-gradient(135deg,#fff 0%,#f8fbff 58%,#eaf3ff 100%)!important;box-shadow:0 24px 60px rgba(15,23,42,.08)!important;padding:14px!important}
        .cv29e-step [data-testid="stVerticalBlockBorderWrapper"]{min-height:154px;border-radius:18px!important;border:1px solid #e2e8f0!important;background:#fff!important}
        .cv29e-number{width:30px;height:30px;border-radius:10px;background:#eff6ff;border:1px solid #bfdbfe;color:#1d4ed8!important;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:950;margin-bottom:10px}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="cv29e-welcome">', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="cv29e-eyebrow">Engineering Decision Intelligence</div>', unsafe_allow_html=True)
        st.title(f"Welcome, {name}.")
        st.markdown(
            "Upload a BOM and Cadivor will identify lifecycle, inventory, supplier, "
            "and engineering risks—then guide your team toward the next decision."
        )
        primary, secondary, spacer = st.columns([1.05, 1, 2.2])
        with primary:
            if st.button("Upload my first BOM →", type="primary", use_container_width=True, key="ftue_upload_first_bom"):
                _go_to("BOM Analyzer")
        with secondary:
            if st.button("Explore the workflow", use_container_width=True, key="ftue_explore_workflow"):
                _go_to("Alternative Finder")
    st.markdown('</div>', unsafe_allow_html=True)

    st.subheader("Your first decision in four steps")
    steps = [
        ("1", "Upload", "Import a CSV or XLSX BOM in a few seconds."),
        ("2", "Understand risk", "See the components and evidence that matter first."),
        ("3", "Make decisions", "Review alternatives, assign actions, and record approvals."),
        ("4", "Share the outcome", "Export an executive-ready engineering report."),
    ]
    columns = st.columns(4)
    for column, (number, title, copy) in zip(columns, steps):
        with column:
            st.markdown('<div class="cv29e-step">', unsafe_allow_html=True)
            with st.container(border=True):
                st.markdown(f'<div class="cv29e-number">{number}</div>', unsafe_allow_html=True)
                st.markdown(f"**{title}**")
                st.caption(copy)
            st.markdown('</div>', unsafe_allow_html=True)

    left, right = st.columns([1.35, 0.65])
    with left:
        with st.container(border=True):
            st.subheader("Get your first result in under five minutes")
            st.write(
                "Start with a production BOM or a smaller design sample. Cadivor will "
                "preserve the analysis so you can return to it later."
            )
            if st.button("Start a new analysis", type="primary", key="ftue_start_analysis"):
                _go_to("BOM Analyzer")
    with right:
        with st.container(border=True):
            st.subheader(workspace)
            st.write("Your analyses, reviews, monitoring, and reports will appear here as your workspace grows.")
            if st.button("Open setup checklist", key="ftue_setup_checklist"):
                _go_to("Onboarding")


def render_activation_strip(*, analyses_count: int, has_review: bool = False, has_report: bool = False) -> None:
    """Show a compact outcome-based setup path for activated accounts."""
    steps = [
        ("Upload BOM", analyses_count > 0),
        ("Review risks", has_review),
        ("Export report", has_report),
    ]
    completed = sum(1 for _, done in steps if done)
    items = "".join(
        f'<div class="cv29-mini-step {"done" if done else "open"}"><span>{"✓" if done else index}</span><strong>{html.escape(label)}</strong></div>'
        for index, (label, done) in enumerate(steps, 1)
    )
    st.markdown(
        f"""
        <style id="cadivor-activation-strip-29a">
        .cv29-activation{{display:grid;grid-template-columns:auto 1fr;gap:18px;align-items:center;border:1px solid #DBEAFE;background:linear-gradient(135deg,#FFFFFF,#F8FBFF);border-radius:19px;padding:15px 17px;margin:0 0 16px;box-shadow:0 12px 30px rgba(15,23,42,.045)}}
        .cv29-activation-copy strong{{display:block;color:#0F172A!important;font-size:14px;font-weight:900}}.cv29-activation-copy small{{display:block;color:#64748B!important;font-size:11px;font-weight:650;margin-top:3px}}
        .cv29-mini-steps{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}}.cv29-mini-step{{display:flex;align-items:center;gap:8px;border:1px solid #E2E8F0;background:#FFFFFF;border-radius:12px;padding:9px 10px}}.cv29-mini-step span{{width:22px;height:22px;border-radius:7px;display:flex;align-items:center;justify-content:center;background:#F1F5F9;color:#64748B!important;font-size:10px;font-weight:950}}.cv29-mini-step strong{{color:#334155!important;font-size:11px;font-weight:850}}.cv29-mini-step.done span{{background:#DCFCE7;color:#15803D!important}}.cv29-mini-step.done{{border-color:#BBF7D0}}
        @media(max-width:800px){{.cv29-activation{{grid-template-columns:1fr}}}}
        </style>
        <section class="cv29-activation"><div class="cv29-activation-copy"><strong>Launch your first decision workflow</strong><small>{completed}/3 activation steps complete</small></div><div class="cv29-mini-steps">{items}</div></section>
        """,
        unsafe_allow_html=True,
    )


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

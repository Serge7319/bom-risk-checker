"""Launch-focused first-time experience components for Cadivor Sprint 29.0B."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import streamlit as st

from src.services.customer_progress import build_activation_progress, next_activation_action
from src.ui.navigation import navigate_to


def _first_name(current_user: dict[str, Any] | None) -> str:
    """Resolve the same user-facing identity used by the Cadivor shell.

    `current_user` is normally the normalized profile returned by
    `get_user_profile()`, but the fallbacks keep onboarding safe for older
    accounts and authentication-only sessions.
    """
    current_user = current_user or {}

    name_candidates = (
        current_user.get("full_name"),
        current_user.get("display_name"),
        current_user.get("name"),
        " ".join(
            part
            for part in (
                str(current_user.get("first_name") or "").strip(),
                str(current_user.get("last_name") or "").strip(),
            )
            if part
        ),
    )
    for candidate in name_candidates:
        name = str(candidate or "").strip()
        if name:
            return name.split()[0]

    email = str(current_user.get("email") or "").strip()
    if email:
        local_part = email.split("@")[0].replace(".", " ").replace("_", " ").strip()
        if local_part:
            return local_part.title()

    return "Engineer"


def _go_to(page: str, **params: Any) -> None:
    """Use Cadivor's session router for authenticated navigation.

    Query-string navigation is deliberately consumed only once after sign-in.
    The onboarding buttons must therefore use the same state-driven router as
    the sidebar; otherwise subsequent clicks leave the user on Dashboard.
    """
    navigate_to(page, **params)


def _render_setup_checklist(*, analyses_count: int = 0, has_review: bool = False, has_report: bool = False) -> None:
    """Render the premium Sprint 30.0C activation checklist."""
    progress = build_activation_progress(
        analyses_count=analyses_count,
        has_review=has_review,
        has_report=has_report,
    )

    rows = [
        {
            "label": "Workspace created",
            "detail": "Your Cadivor account and workspace are ready.",
            "time": "Ready",
            "done": progress.account_created,
            "action": None,
            "page": None,
            "enabled": False,
            "icon": "✓",
        },
        {
            "label": "Upload your first BOM",
            "detail": "Import a CSV or XLSX component list.",
            "time": "About 30 seconds",
            "done": progress.first_bom,
            "action": "Upload BOM",
            "page": "BOM Analyzer",
            "enabled": True,
            "icon": "↥",
        },
        {
            "label": "Analyze the BOM",
            "detail": "Generate lifecycle, inventory, and supplier intelligence.",
            "time": "About 1 minute",
            "done": progress.first_analysis,
            "action": "Analyze BOM",
            "page": "BOM Analyzer",
            "enabled": progress.first_bom,
            "icon": "◇",
        },
        {
            "label": "Review the results",
            "detail": "Record a component decision and supporting evidence.",
            "time": "About 2 minutes",
            "done": progress.first_review,
            "action": "Review Results",
            "page": "Engineering Decisions",
            "enabled": progress.first_analysis,
            "icon": "✓",
        },
        {
            "label": "Generate a report",
            "detail": "Create an executive-ready engineering report.",
            "time": "About 15 seconds",
            "done": progress.first_report,
            "action": "Generate Report",
            "page": "Reports",
            "enabled": progress.first_analysis,
            "icon": "▤",
        },
    ]

    st.markdown(
        """
        <style id="cadivor-activation-checklist-30c" data-cadivor-layout-style="true">
        .cv30c-header{margin:0 0 10px}
        .cv30c-title{font-size:18px;font-weight:950;color:#0f172a!important;line-height:1.15;margin:0 0 4px}
        .cv30c-subtitle{font-size:11px;font-weight:650;color:#64748b!important;line-height:1.45;margin:0 0 10px}
        .cv30c-progress-copy{font-size:11px;font-weight:850;color:#334155!important;margin:0 0 7px}
        .cv30c-kicker{font-size:9px;font-weight:900;letter-spacing:.08em;text-transform:uppercase;color:#64748b!important;margin:0 0 5px}
        .cv30c-row-title{font-size:13px;font-weight:900;color:#0f172a!important;line-height:1.25;margin:0}
        .cv30c-row-detail{font-size:10px;font-weight:620;color:#64748b!important;line-height:1.4;margin:4px 0 0}
        .cv30c-icon{width:30px;height:30px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:950;flex:0 0 auto}
        .cv30c-icon.done{background:#dcfce7;color:#15803d!important;border:1px solid #bbf7d0}
        .cv30c-icon.active{background:#dbeafe;color:#1d4ed8!important;border:1px solid #93c5fd}
        .cv30c-icon.locked{background:#f1f5f9;color:#94a3b8!important;border:1px solid #e2e8f0}
        .cv30c-copy{min-width:0}
        .cv30c-state{font-size:9px;font-weight:900;border-radius:999px;padding:4px 7px;white-space:nowrap}
        .cv30c-state.done{background:#ecfdf5;color:#047857!important;border:1px solid #a7f3d0}
        .cv30c-state.active{background:#eff6ff;color:#1d4ed8!important;border:1px solid #bfdbfe}
        .cv30c-state.locked{background:#f8fafc;color:#94a3b8!important;border:1px solid #e2e8f0}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv30c-card){padding:12px!important;border-radius:15px!important;transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv30c-card-active){border-color:#93c5fd!important;background:linear-gradient(135deg,#ffffff 0%,#eff6ff 100%)!important;box-shadow:0 10px 24px rgba(37,99,235,.08)!important}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv30c-card-done){border-color:#bbf7d0!important;background:#fbfffd!important}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv30c-card-locked){background:#fafafa!important;opacity:.86}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv30c-card):hover{transform:translateY(-1px);box-shadow:0 8px 20px rgba(15,23,42,.06)}
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.cv30c-card) [data-testid="stButton"] button{min-height:36px!important;height:36px!important;border-radius:10px!important;font-size:11px!important;font-weight:900!important;margin-top:8px!important}
        .cv302-locked-note{margin-top:9px;border:1px dashed #cbd5e1;background:#f8fafc;border-radius:10px;padding:9px 10px;color:#64748b!important;font-size:10px;font-weight:750;line-height:1.35}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="cv30c-header">'
        '<div class="cv30c-title">Getting Started</div>'
        '<div class="cv30c-subtitle">Complete these steps to unlock your engineering workspace.</div>'
        f'<div class="cv30c-progress-copy">{progress.completed} of {progress.total} complete</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.progress(progress.percent / 100)

    first_incomplete_seen = False
    for index, row in enumerate(rows):
        is_current = not row["done"] and not first_incomplete_seen
        if is_current:
            first_incomplete_seen = True

        card_state = "done" if row["done"] else ("active" if is_current else "locked")
        state_label = "Ready" if row["done"] else ("Next step" if is_current else "Locked")
        icon_state = "done" if row["done"] else ("active" if is_current else "locked")
        icon = "✓" if row["done"] else row["icon"]

        with st.container(border=True):
            st.markdown(f'<span class="cv30c-card cv30c-card-{card_state}"></span>', unsafe_allow_html=True)
            icon_col, copy_col, state_col = st.columns([0.38, 3.3, 0.85], vertical_alignment="center")
            with icon_col:
                st.markdown(f'<div class="cv30c-icon {icon_state}">{html.escape(icon)}</div>', unsafe_allow_html=True)
            with copy_col:
                st.markdown(
                    '<div class="cv30c-copy">'
                    f'<div class="cv30c-row-title">{html.escape(row["label"])}</div>'
                    f'<div class="cv30c-row-detail">{html.escape(row["detail"])}</div>'
                    f'<div class="cv30c-kicker" style="margin-top:7px">{html.escape(row["time"])}</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )
            with state_col:
                st.markdown(f'<div class="cv30c-state {card_state}">{state_label}</div>', unsafe_allow_html=True)

            if is_current and row["action"] and row["page"]:
                if st.button(
                    row["action"],
                    key=f"ftue_30c_action_{index}",
                    use_container_width=True,
                    type="primary",
                ):
                    if row["label"] == "Upload your first BOM":
                        _go_to(row["page"], new_analysis="1")
                    else:
                        _go_to(row["page"])
            elif not row["done"]:
                prerequisite = {
                    "Analyze the BOM": "Unlocks after your first BOM is uploaded.",
                    "Review the results": "Unlocks after your first analysis is complete.",
                    "Generate a report": "Unlocks after your first analysis is complete.",
                }.get(row["label"], "Complete the previous step to unlock this action.")
                st.markdown(
                    f'<div class="cv302-locked-note">🔒 {html.escape(prerequisite)}</div>',
                    unsafe_allow_html=True,
                )


def render_first_run_dashboard(*, current_user: dict[str, Any] | None, workspace_name: str | None = None) -> None:
    """Render the approved first-run Home mockup without changing upload behavior."""
    del current_user, workspace_name  # The approved empty state is the same for every workspace.

    css_path = Path(__file__).resolve().parents[1] / "assets" / "css" / "first_run_home.css"
    try:
        first_run_css = css_path.read_text(encoding="utf-8")
    except OSError:
        first_run_css = ""
    if first_run_css:
        st.markdown(
            f'<style id="cadivor-first-run-home">{first_run_css}</style>',
            unsafe_allow_html=True,
        )

    with st.container(border=True):
        copy_col, artwork_col = st.columns([1.08, 0.92], gap="large", vertical_alignment="center")
        with copy_col:
            st.markdown(
                """
                <div class="cv-home-first-run-marker"></div>
                <div class="cv-home-first-run-copy">
                  <div class="cv-home-first-run-eyebrow">CADIVOR ENGINEERING DECISION INTELLIGENCE</div>
                  <h1>Start your first BOM review</h1>
                  <p>Upload a BOM to identify component risk, review evidence, and document the next engineering action.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(
                "Upload a BOM",
                type="primary",
                key="ftue_upload_first_bom",
                icon=":material/upload:",
            ):
                _go_to("BOM Analyzer", new_analysis="1")
        with artwork_col:
            st.markdown(
                """
                <div class="cv-home-first-run-art" role="img" aria-label="CSV and XLSX files flow into a BOM risk review">
                  <svg viewBox="0 0 640 300" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <defs>
                      <linearGradient id="cvBOMArtBg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#E8F2FF"/><stop offset="1" stop-color="#DCEBFF"/></linearGradient>
                      <filter id="cvBOMArtShadow" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="8" stdDeviation="9" flood-color="#173B72" flood-opacity=".12"/></filter>
                    </defs>
                    <circle cx="431" cy="151" r="145" fill="url(#cvBOMArtBg)" opacity=".88"/>
                    <circle cx="434" cy="150" r="120" fill="none" stroke="#BBD3F8" stroke-width="2" stroke-dasharray="3 9"/>
                    <g filter="url(#cvBOMArtShadow)">
                      <rect x="23" y="34" width="234" height="232" rx="18" fill="#FFFFFF" stroke="#D4E2F3"/>
                      <path d="M47 67h43m-43 11h69" stroke="#D7E2F0" stroke-width="6" stroke-linecap="round"/>
                      <rect x="47" y="99" width="78" height="112" rx="13" fill="#EFF8F2"/>
                      <rect x="60" y="113" width="52" height="52" rx="12" fill="#16A765"/>
                      <path d="M72 128h28M72 136h28M72 144h18" stroke="#FFFFFF" stroke-width="2.5" stroke-linecap="round"/>
                      <text x="86" y="185" fill="#137342" font-family="Inter,Arial,sans-serif" font-size="13" font-weight="800" text-anchor="middle">CSV</text>
                      <rect x="145" y="122" width="87" height="112" rx="13" fill="#F0F6FF"/>
                      <rect x="162" y="136" width="53" height="52" rx="12" fill="#2868E8"/>
                      <path d="M174 151h28M174 159h28M174 167h18" stroke="#FFFFFF" stroke-width="2.5" stroke-linecap="round"/>
                      <text x="188" y="208" fill="#1D4ED8" font-family="Inter,Arial,sans-serif" font-size="12" font-weight="800" text-anchor="middle">XLSX</text>
                      <rect x="389" y="28" width="226" height="244" rx="18" fill="#FFFFFF" stroke="#D1DFF0"/>
                      <rect x="407" y="47" width="31" height="31" rx="10" fill="#EAF2FF"/>
                      <path d="M415 62l5 5 10-11" fill="none" stroke="#2868E8" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
                      <text x="449" y="61" fill="#192C49" font-family="Inter,Arial,sans-serif" font-size="12" font-weight="800">BOM RISK REVIEW</text>
                      <path d="M407 91h190" stroke="#E7EEF7" stroke-width="2"/>
                      <rect x="407" y="108" width="190" height="43" rx="10" fill="#F8FAFD"/>
                      <circle cx="424" cy="129" r="7" fill="#FDE8E7"/><path d="M424 125v5m0 3h.1" stroke="#C93F3A" stroke-width="2" stroke-linecap="round"/>
                      <path d="M442 123h108m-108 10h74" stroke="#AAB8CA" stroke-width="5" stroke-linecap="round"/>
                      <rect x="407" y="162" width="190" height="43" rx="10" fill="#F8FAFD"/>
                      <circle cx="424" cy="183" r="7" fill="#FFF1D5"/><path d="M424 179v5m0 3h.1" stroke="#B77811" stroke-width="2" stroke-linecap="round"/>
                      <path d="M442 177h108m-108 10h74" stroke="#AAB8CA" stroke-width="5" stroke-linecap="round"/>
                      <rect x="407" y="216" width="190" height="43" rx="10" fill="#F8FAFD"/>
                      <circle cx="424" cy="237" r="7" fill="#DFF5E8"/><path d="M421 237l2 3 5-6" fill="none" stroke="#16834B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                      <path d="M442 231h108m-108 10h74" stroke="#AAB8CA" stroke-width="5" stroke-linecap="round"/>
                    </g>
                    <path d="M274 153C310 153 323 112 366 112" fill="none" stroke="#3979E5" stroke-width="3" stroke-linecap="round" stroke-dasharray="2 10"/>
                    <path d="M356 104l12 8-12 8" fill="none" stroke="#2868E8" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                    <circle cx="285" cy="151" r="4" fill="#3979E5"/><circle cx="304" cy="143" r="4" fill="#3979E5"/><circle cx="324" cy="131" r="4" fill="#3979E5"/>
                  </svg>
                </div>
                """,
                unsafe_allow_html=True,
            )

    step_icons = {
        "upload": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V3m0 0-4 4m4-4 4 4M4 14v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5"/></svg>',
        "risk": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3.5h9l5 5V14M14 3.5v5h5M8 13h6M8 16.5h4"/><circle cx="16.5" cy="17" r="3.5"/><path d="m19 19.5 2 2"/></svg>',
        "decision": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m8 12 2.6 2.6L16.5 9"/></svg>',
        "report": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4v13H6a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2Z"/><path d="M14 3.5v4h4M8 12h7M8 15.5h7"/></svg>',
    }
    steps = (
        ("1", "Upload", "Import a CSV or XLSX BOM.", "upload"),
        ("2", "Understand risk", "See the evidence that matters first.", "risk"),
        ("3", "Make decisions", "Review alternatives and record approvals.", "decision"),
        ("4", "Share the outcome", "Export an executive-ready report.", "report"),
    )
    items = "".join(
        f'<li><span class="cv-home-step-num">{number}</span>'
        f'<span class="cv-home-step-icon">{step_icons[icon]}</span>'
        f'<strong>{html.escape(title)}</strong><p>{html.escape(copy)}</p></li>'
        for number, title, copy, icon in steps
    )
    st.markdown(
        f"""
        <section class="cv-home-first-run-steps" aria-label="A first review in four steps">
          <div class="cv-home-first-run-section-heading">
            <h2>A first review in four steps</h2>
          </div>
          <ol>{items}</ol>
        </section>
        <section class="cv-home-first-run-empty" aria-label="No analyses yet">
          <div class="cv-home-first-run-empty-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M7 3.75h7l4 4v12.5H7a2 2 0 0 1-2-2v-12.5a2 2 0 0 1 2-2Z"/><path d="M14 3.75v4h4M8.5 12h7M8.5 15.5h7"/></svg>
          </div>
          <strong>No analyses yet</strong>
          <p>Your first review will appear here after upload.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


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


def _analysis_health_display(
    health_score: int | None,
    needs_verification_count: int = 0,
) -> str:
    """Never present a partial BOM score as an overall health result."""
    if health_score is None or int(needs_verification_count or 0) > 0:
        return "Needs verification"
    return f"{int(health_score)}/100"


def render_analysis_success(
    *,
    project_name: str,
    total_parts: int,
    high_count: int,
    medium_count: int,
    health_score: int | None,
    analysis_id: str,
    needs_verification_count: int = 0,
    source_filename: str = "",
) -> None:
    """Render the approved result-page metadata, evidence status, and actions."""
    del medium_count, health_score  # calculations remain in the analysis/report layers
    total_parts = max(0, int(total_parts or 0))
    high_count = max(0, int(high_count or 0))
    needs_verification_count = max(0, int(needs_verification_count or 0))
    project = html.escape(str(project_name or "BOM analysis"))
    filename = html.escape(str(source_filename or "Uploaded BOM"))
    if needs_verification_count:
        status_title = "Overall BOM risk needs verification"
        status_copy = (
            "Supplier evidence is incomplete. Review the component statuses below "
            "before relying on an overall exposure assessment."
        )
        status_class = "verify"
    elif high_count:
        status_title = "High-risk components need review"
        status_copy = "Review supplier and lifecycle evidence for the flagged components."
        status_class = "risk"
    else:
        status_title = "Analysis complete"
        status_copy = "Review component-level supplier evidence and recommended next steps below."
        status_class = "clear"
    icon = "⚠" if status_class != "clear" else "✓"
    st.markdown(
        f"""
        <style id="cadivor-analysis-success-29b" data-cadivor-layout-style="true">
        .cvres-meta{{display:flex;align-items:center;flex-wrap:wrap;gap:8px 12px;margin:1px 0 15px;color:#66758b!important;font-size:12px}}
        .cvres-meta strong{{color:#172438!important;font-weight:700}}
        .cvres-meta .dot{{color:#b5c0ce!important}}
        .cvres-status{{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(350px,.9fr);align-items:center;gap:18px;border:1px solid #e1e7f0;border-radius:13px;padding:17px 19px;margin:0 0 15px;background:#fff}}
        .cvres-status.verify{{border-color:#efd9a8;background:#fffaf0}}
        .cvres-status.risk{{border-color:#fecaca;background:#fff7f6}}
        .cvres-status.clear{{border-color:#b8e4c7;background:#f5fcf7}}
        .cvres-status-copy{{display:flex;align-items:flex-start;gap:12px;min-width:0}}
        .cvres-status-icon{{display:grid;flex:0 0 34px;width:34px;height:34px;place-items:center;border-radius:10px;color:#9a5c08;background:#ffedc2;font-size:18px;font-weight:800}}
        .cvres-status.risk .cvres-status-icon{{color:#b42318;background:#ffe3de}}
        .cvres-status.clear .cvres-status-icon{{color:#187145;background:#dff4e6}}
        .cvres-status h2{{margin:0;color:#172438!important;font-size:15px;line-height:1.35;font-weight:700}}
        .cvres-status p{{max-width:670px;margin:5px 0 0;color:#715a32!important;font-size:12px;line-height:1.5}}
        .cvres-status.risk p{{color:#7b4540!important}}
        .cvres-status.clear p{{color:#4c6e58!important}}
        .cvres-counts{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-left:1px solid #ead8b4}}
        .cvres-stat{{padding:0 11px;text-align:center}}
        .cvres-stat+.cvres-stat{{border-left:1px solid #ead8b4}}
        .cvres-stat strong{{display:block;color:#172438!important;font-size:20px;line-height:1.1;font-weight:650;font-variant-numeric:tabular-nums}}
        .cvres-stat span{{display:block;margin-top:5px;color:#715a32!important;font-size:11px;line-height:1.25}}
        div.st-key-cvres_actions{{margin:0 0 23px}}
        div.st-key-cvres_actions [data-testid="stHorizontalBlock"]{{align-items:center;gap:10px}}
        div.st-key-cvres_actions [data-testid="stButton"]{{width:auto}}
        div.st-key-cvres_actions [data-testid="stButton"] button{{min-height:40px;border-radius:9px;font-size:13px;font-weight:700}}
        @media(max-width:780px){{.cvres-status{{grid-template-columns:1fr}}.cvres-counts{{border-top:1px solid #ead8b4;border-left:0;padding-top:14px}}.cvres-stat:first-child{{padding-left:0}}}}
        @media(max-width:520px){{div.st-key-cvres_actions [data-testid="stHorizontalBlock"]{{align-items:stretch;flex-direction:column}}}}
        </style>
        <div class="cvres-meta" aria-label="Analysis details">
          <strong>{project}</strong><span class="dot">•</span><span>▤ &nbsp;{filename}</span>
          <span class="dot">•</span><span>{total_parts} components</span>
          <span class="dot">•</span><span>Analysis complete</span>
        </div>
        <section class="cvres-status {status_class}" aria-label="BOM evidence status">
          <div class="cvres-status-copy"><div class="cvres-status-icon" aria-hidden="true">{icon}</div>
            <div><h2>{html.escape(status_title)}</h2><p>{html.escape(status_copy)}</p></div></div>
          <div class="cvres-counts" aria-label="Analysis counts">
            <div class="cvres-stat"><strong>{total_parts}</strong><span>components</span></div>
            <div class="cvres-stat"><strong>{high_count}</strong><span>rated high risk</span></div>
            <div class="cvres-stat"><strong>{needs_verification_count}</strong><span>need verification</span></div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    from src.ui.navigation import open_saved_bom

    with st.container(key="cvres_actions"):
        review_col, report_col = st.columns([0.25, 0.22], vertical_alignment="center")
        with review_col:
            if st.button(
                "↗  Open Engineering Intelligence",
                key="cv29b_open_engineering_review",
                type="primary",
            ):
                open_saved_bom(str(analysis_id or ""), arm_opening=False, _rerun=True)
        with report_col:
            if st.button(
                "Generate detailed report",
                key="cv29b_generate_report",
            ):
                navigate_to("Reports",
                    analysis_id=str(analysis_id or ""),
                    arm_opening=False,
                )


import html
from io import BytesIO

import pandas as pd
import streamlit as st

from src.ui.cadivor_design_system import MetricCard, cadivor_button_wrap, cadivor_button_wrap_end, render_kpi_row_safe
from src.ui.navigation import ALTERNATIVE_FINDER_PAGE, internal_nav_button


def _safe_text(value, fallback="—"):
    if value is None:
        return fallback
    text = str(value).strip()
    return html.escape(text if text else fallback)


def _as_int(value, fallback=0):
    try:
        if value is None:
            return fallback
        return int(float(value))
    except Exception:
        return fallback


def _date_text(value):
    if not value:
        return "Not dated"
    text = str(value)
    if "T" in text:
        return text.split("T")[0]
    return text[:10]


def _load_recent_analyses(current_user, supabase, load_analysis_history):
    try:
        history = load_analysis_history(current_user["id"])
        if history is None:
            return []
        if isinstance(history, pd.DataFrame):
            return history.to_dict("records")
        return list(history)
    except Exception:
        try:
            response = (
                supabase.table("analyses")
                .select("*")
                .eq("user_id", current_user["id"])
                .order("created_at", desc=True)
                .limit(12)
                .execute()
            )
            return response.data or []
        except Exception:
            return []


def _download_csv(records):
    if not records:
        return "Project,File,Date,Health,High Risk,Medium Risk,Parts\n".encode("utf-8")
    rows = []
    for row in records:
        rows.append(
            {
                "Project": row.get("project_name") or row.get("name") or "Saved BOM",
                "File": row.get("filename") or row.get("uploaded_file") or row.get("file_name") or "—",
                "Date": _date_text(row.get("created_at") or row.get("date")),
                "Health": _as_int(row.get("health_score")),
                "High Risk": _as_int(row.get("high_risk_count") or row.get("high_risk_parts")),
                "Medium Risk": _as_int(row.get("medium_risk_count") or row.get("medium_risk_parts")),
                "Parts": _as_int(row.get("part_count") or row.get("total_parts") or row.get("parts_count")),
            }
        )
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


def render_reports_center(current_user, supabase, load_analysis_history, _qp_value=None):
    """Milestone 5.4.3: self-contained premium Reports Center."""
    records = _load_recent_analyses(current_user, supabase, load_analysis_history)
    total_reports = len(records)
    total_parts = sum(_as_int(r.get("part_count") or r.get("total_parts") or r.get("parts_count")) for r in records)
    high_risk = sum(_as_int(r.get("high_risk_count") or r.get("high_risk_parts")) for r in records)
    avg_health = round(
        sum(_as_int(r.get("health_score")) for r in records) / total_reports
    ) if total_reports else 0

    st.markdown(
        """
        <style id="cadivor-reports-center-v543">
        .cv-report-shell{max-width:1680px;margin:0 auto 64px auto;}
        .cv-report-hero{border:1px solid #BFDBFE;border-radius:26px;background:linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 58%,#EAF3FF 100%);box-shadow:0 28px 70px rgba(15,23,42,.075);padding:34px 36px;margin-bottom:20px;display:grid;grid-template-columns:minmax(0,1.2fr) minmax(420px,.8fr);gap:28px;align-items:center;}
        .cv-report-pill{display:inline-flex;align-items:center;gap:8px;background:#EFF6FF;border:1px solid #BFDBFE;border-radius:999px;color:#2563EB;font-size:11px;font-weight:950;letter-spacing:.12em;text-transform:uppercase;padding:8px 13px;margin-bottom:20px;}
        .cv-report-title{font-size:42px;line-height:1.04;font-weight:950;color:#0F172A;margin:0 0 14px 0;letter-spacing:-.045em;}
        .cv-report-copy{font-size:15px;line-height:1.7;font-weight:750;color:#52647A;max-width:780px;margin:0 0 22px 0;}
        .cv-report-actions{display:flex;gap:12px;flex-wrap:wrap;}
        .cv-report-btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 18px;border-radius:12px;font-size:13px;font-weight:900;text-decoration:none!important;}
        .cv-report-btn.primary{background:#2563EB;color:#fff!important;box-shadow:0 16px 32px rgba(37,99,235,.22);}
        .cv-report-btn.secondary{background:#fff;color:#2563EB!important;border:1px solid #BFDBFE;}
        .cv-report-hero-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
        .cv-report-mini{background:rgba(255,255,255,.88);border:1px solid #E2E8F0;border-radius:18px;padding:18px 18px;box-shadow:0 14px 34px rgba(15,23,42,.045);}
        .cv-report-mini-label{color:#64748B;font-size:11px;font-weight:950;letter-spacing:.12em;text-transform:uppercase;margin-bottom:8px;}
        .cv-report-mini-value{font-size:26px;font-weight:950;line-height:1;color:#0F172A;margin-bottom:7px;}
        .cv-report-mini-note{font-size:12px;font-weight:850;color:#334155;}
        .cv-report-section-head{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin:26px 0 12px;}
        .cv-report-section-title{font-size:22px;font-weight:950;color:#0F172A;letter-spacing:-.035em;margin:0;}
        .cv-report-section-sub{font-size:13px;font-weight:750;color:#64748B;margin-top:5px;}
        .cv-report-card-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-bottom:18px;}
        .cv-report-card{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:22px;padding:22px;box-shadow:0 20px 46px rgba(15,23,42,.065);min-height:160px;transition:all .16s ease;}
        .cv-report-card:hover{transform:translateY(-2px);border-color:#BFDBFE;box-shadow:0 28px 60px rgba(15,23,42,.09);}
        .cv-report-preview{height:128px;border-radius:14px;background:linear-gradient(155deg,#F8FBFF,#EAF2FF);border:1px solid #D8E4F5;padding:14px;margin-bottom:15px;box-shadow:inset 0 0 0 1px rgba(255,255,255,.8)}.cv-report-preview .bar{height:7px;border-radius:5px;background:#D9E6FA;margin:8px 0}.cv-report-preview .bar.primary{background:#2563EB;width:62%}.cv-report-preview .bar.short{width:48%}.cv-report-preview .chart{height:42px;margin-top:10px;border-radius:8px;background:linear-gradient(135deg,rgba(37,99,235,.12),rgba(22,163,74,.10));border-bottom:2px solid #2563EB}.cv-report-icon{width:42px;height:42px;border-radius:14px;background:#EFF6FF;border:1px solid #BFDBFE;color:#2563EB;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:950;margin-bottom:16px;}
        .cv-report-card-title{font-size:16px;font-weight:950;color:#0F172A;margin-bottom:8px;}
        .cv-report-card-copy{font-size:13px;line-height:1.55;font-weight:750;color:#52647A;margin-bottom:16px;}
        .cv-report-link{font-size:13px;font-weight:950;color:#2563EB;text-decoration:none!important;}
        .cv-report-board{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:22px;box-shadow:0 18px 44px rgba(15,23,42,.06);overflow:hidden;margin-bottom:18px;}
        .cv-report-row{display:grid;grid-template-columns:minmax(240px,1.2fr) minmax(180px,.8fr) 120px 120px 130px 110px;gap:12px;align-items:center;padding:16px 18px;border-bottom:1px solid #EEF2F7;}
        .cv-report-row:last-child{border-bottom:none;}
        .cv-report-head{background:#F8FAFC;color:#64748B;font-size:11px;font-weight:950;letter-spacing:.1em;text-transform:uppercase;}
        .cv-report-name{font-size:14px;font-weight:950;color:#0F172A;}
        .cv-report-meta{font-size:12px;font-weight:800;color:#64748B;margin-top:3px;}
        .cv-report-badge{display:inline-flex;align-items:center;justify-content:center;border-radius:999px;padding:7px 10px;font-size:12px;font-weight:950;border:1px solid #BFDBFE;background:#EFF6FF;color:#2563EB;white-space:nowrap;}
        .cv-report-badge.good{background:#ECFDF5;border-color:#A7F3D0;color:#047857;}
        .cv-report-badge.bad{background:#FEF2F2;border-color:#FECACA;color:#DC2626;}
        .cv-report-roadmap{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-top:14px;}
        .cv-roadmap-item{background:#FFFFFF;border:1px dashed #CBD5E1;border-radius:18px;padding:18px;}
        .cv-roadmap-kicker{font-size:11px;font-weight:950;letter-spacing:.1em;text-transform:uppercase;color:#2563EB;margin-bottom:8px;}
        .cv-roadmap-title{font-size:14px;font-weight:950;color:#0F172A;margin-bottom:6px;}
        .cv-roadmap-copy{font-size:12px;line-height:1.5;font-weight:750;color:#64748B;}
        @media(max-width:1100px){.cv-report-hero{grid-template-columns:1fr}.cv-report-card-grid{grid-template-columns:1fr}.cv-report-roadmap{grid-template-columns:1fr}.cv-report-row{grid-template-columns:1fr}.cv-report-head{display:none}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="cv-report-shell">', unsafe_allow_html=True)
    st.markdown(
        """
        <section class="cv-report-hero">
          <div>
            <div class="cv-report-pill">▣ Reports Center</div>
            <h1 class="cv-report-title">Engineering reports</h1>
            <p class="cv-report-copy">Generate executive-ready BOM risk packages, sourcing summaries, lifecycle reviews, and exportable engineering records from saved Cadivor analyses.</p>
            <div class="cv-report-actions">
              <a class="cv-report-btn primary" href="?page=BOM%20Analyzer" target="_self">Generate from BOM →</a>
              <a class="cv-report-btn secondary" href="?page=Dashboard" target="_self">Open dashboard</a>
            </div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    render_kpi_row_safe(
        [
            MetricCard(label="Reports", value=str(total_reports), detail="Saved analyses ready to export", tone="info", icon="file-text"),
            MetricCard(label="Downloads", value=str(len(st.session_state.get("reports_session_history", []))), detail="Generated this session", tone="success", icon="download"),
            MetricCard(label="Exports", value=str(total_reports), detail="Report packages available", tone="monitoring", icon="file-spreadsheet"),
        ],
        columns=3,
    )

    st.markdown(
        """
        <div class="cv-report-section-head"><div><h2 class="cv-report-section-title">Report templates</h2><div class="cv-report-section-sub">Choose the report style that matches the review workflow.</div></div></div>
        <div class="cv-report-card-grid">
          <div class="cv-report-card"><div class="cv-report-preview"><div class="bar primary"></div><div class="bar"></div><div class="chart"></div><div class="bar short"></div></div><div class="cv-report-icon">📄</div><div class="cv-report-card-title">Executive BOM Report</div><div class="cv-report-card-copy">Portfolio health, high-risk components, lifecycle signals, cost exposure, and recommended next actions for leadership review.</div><a class="cv-report-link" href="?page=BOM%20Analyzer" target="_self">Create executive report →</a></div>
          <div class="cv-report-card"><div class="cv-report-preview"><div class="bar primary"></div><div class="bar short"></div><div class="bar"></div><div class="chart"></div></div><div class="cv-report-icon">🧪</div><div class="cv-report-card-title">Engineering Risk Review</div><div class="cv-report-card-copy">Component-level risk, lifecycle status, supplier coverage, confidence, and BOM readiness details for engineers.</div><a class="cv-report-link" href="?page=Dashboard" target="_self">Review saved analyses →</a></div>
          <div class="cv-report-card"><div class="cv-report-preview"><div class="bar primary"></div><div class="chart"></div><div class="bar"></div><div class="bar short"></div></div><div class="cv-report-icon">📦</div><div class="cv-report-card-title">Sourcing Summary</div><div class="cv-report-card-copy">Procurement-oriented stock, supplier concentration, replacement readiness, lead-time, and sourcing risk package.</div><span class="cv-report-link">Validate alternatives below →</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    internal_nav_button(
        "Validate alternatives →",
        ALTERNATIVE_FINDER_PAGE,
        key="reports_template_alternative_finder",
        source_page="reports_center",
    )

    st.markdown(
        '<div class="cv-report-section-head"><div><h2 class="cv-report-section-title">Recent report sources</h2><div class="cv-report-section-sub">Saved BOM analyses ready for export or review.</div></div></div>',
        unsafe_allow_html=True,
    )

    if records:
        rows_html = [
            '<div class="cv-report-row cv-report-head"><div>Project</div><div>Source file</div><div>Date</div><div>Health</div><div>High risk</div><div>Action</div></div>'
        ]
        for row in records[:8]:
            project = _safe_text(row.get("project_name") or row.get("name") or "Saved BOM")
            filename = _safe_text(row.get("filename") or row.get("uploaded_file") or row.get("file_name") or "Source file")
            date = _safe_text(_date_text(row.get("created_at") or row.get("date")))
            health = _as_int(row.get("health_score"))
            high = _as_int(row.get("high_risk_count") or row.get("high_risk_parts"))
            badge_class = "good" if health >= 80 else ("bad" if health < 60 else "")
            high_class = "bad" if high else "good"
            rows_html.append(
                f'<div class="cv-report-row"><div><div class="cv-report-name">{project}</div><div class="cv-report-meta">Ready for report package</div></div><div class="cv-report-meta">{filename}</div><div class="cv-report-meta">{date}</div><div><span class="cv-report-badge {badge_class}">{health} health</span></div><div><span class="cv-report-badge {high_class}">{high} high</span></div><div><a class="cv-report-link" href="?page=Dashboard" target="_self">Open →</a></div></div>'
            )
        st.markdown('<div class="cv-report-board">' + ''.join(rows_html) + '</div>', unsafe_allow_html=True)
    else:
        st.markdown(
            """
            <div class="cv-report-board">
              <div style="padding:30px;text-align:center;color:#64748B;font-weight:800;"><strong style="display:block;font-size:18px;color:#0F172A;margin-bottom:8px">Create your first decision-ready report</strong>Upload and analyze a BOM to generate an executive summary, engineering risk review, and sourcing package for stakeholders.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    csv_data = _download_csv(records)
    cadivor_button_wrap("secondary")
    st.download_button(
        "Download report-source CSV",
        data=csv_data,
        file_name="cadivor_report_sources.csv",
        mime="text/csv",
        use_container_width=True,
    )
    cadivor_button_wrap_end()

    st.markdown(
        """
        <div class="cv-report-section-head"><div><h2 class="cv-report-section-title">Report automation roadmap</h2><div class="cv-report-section-sub">Planned enterprise reporting capabilities after the core workflow is stable.</div></div></div>
        <div class="cv-report-roadmap">
          <div class="cv-roadmap-item"><div class="cv-roadmap-kicker">PDF</div><div class="cv-roadmap-title">Branded PDF packets</div><div class="cv-roadmap-copy">Executive summaries with Cadivor branding, risk tables, and recommendations.</div></div>
          <div class="cv-roadmap-item"><div class="cv-roadmap-kicker">Schedule</div><div class="cv-roadmap-title">Recurring reports</div><div class="cv-roadmap-copy">Weekly or monthly report delivery for monitored BOM portfolios.</div></div>
          <div class="cv-roadmap-item"><div class="cv-roadmap-kicker">Share</div><div class="cv-roadmap-title">Team-ready links</div><div class="cv-roadmap-copy">Shareable analysis workspaces for engineering and sourcing teams.</div></div>
          <div class="cv-roadmap-item"><div class="cv-roadmap-kicker">Audit</div><div class="cv-roadmap-title">Report history</div><div class="cv-roadmap-copy">Track who generated, exported, and reviewed each report package.</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)

"""Cadivor saved analysis detail page.

This page turns each saved BOM analysis into a durable engineering record.
Dashboard links can now open a specific analysis instead of sending every user
back to the BOM Analyzer.
"""

from __future__ import annotations

from datetime import datetime, timezone
import html
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st


def _safe(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _num(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _date(value: Any) -> str:
    if not value:
        return "—"
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y")
    except Exception:
        return text[:10]


def _relative_date(value: Any) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
        if delta.days <= 0:
            hours = int(delta.total_seconds() // 3600)
            if hours <= 0:
                minutes = max(1, int(delta.total_seconds() // 60))
                return f"{minutes} min ago"
            return f"{hours} hr ago"
        if delta.days == 1:
            return "Yesterday"
        if delta.days < 7:
            return f"{delta.days} days ago"
        return dt.strftime("%b %d")
    except Exception:
        return _date(value)


def _risk_class(level: Any = None, score: Any = None) -> str:
    level_text = str(level or "").lower()
    score_num = _num(score, 0)
    if "high" in level_text or score_num >= 70:
        return "bad"
    if "medium" in level_text or score_num >= 35:
        return "warn"
    return "good"


def _health_class(score: Any) -> str:
    score_num = _num(score, 0)
    if score_num >= 80:
        return "good"
    if score_num >= 55:
        return "warn"
    return "bad"


def _lucide(name: str, size: int = 18) -> str:
    icons = {
        "arrow-left": '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
        "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/>',
        "shield": '<path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3z"/><path d="m9 12 2 2 4-4"/>',
        "alert": '<path d="m21.7 18-8.5-15a1.4 1.4 0 0 0-2.4 0L2.3 18a1.4 1.4 0 0 0 1.2 2h17a1.4 1.4 0 0 0 1.2-2Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
        "layers": '<path d="m12 2 10 5-10 5L2 7l10-5Z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
        "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
        "replace": '<path d="M17 2l4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15"/><path d="m7 22-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
        "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
        "factory": '<path d="M2 20h20"/><path d="M6 20V8l6 4V8l6 4v8"/><path d="M18 10V4h3v16"/>',
        "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    }
    body = icons.get(name, icons["file"])
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


def _query_table(supabase, table: str, *, user_id: str, analysis_id: str, order: str | None = None, limit: int | None = None):
    try:
        query = supabase.table(table).select("*").eq("user_id", user_id).eq("analysis_id", analysis_id)
        if order:
            query = query.order(order, desc=True)
        if limit:
            query = query.limit(limit)
        response = query.execute()
        return response.data or []
    except Exception:
        return []


def _analysis_link(analysis_id: str) -> str:
    return f"?page=Analysis%20Details&analysis_id={html.escape(str(analysis_id), quote=True)}"


def render_analysis_detail(
    *,
    current_user,
    supabase,
    load_analysis_history,
    light_plotly_layout=None,
    _qp_value=None,
):
    """Render a dedicated saved-analysis workspace."""

    analysis_id = ""
    if _qp_value:
        analysis_id = _safe(_qp_value("analysis_id", ""), "")
    if not analysis_id:
        analysis_id = _safe(st.query_params.get("analysis_id", ""), "")

    st.markdown(
        """
        <style>
        .cv-analysis-shell{display:grid;gap:18px;}
        .cv-analysis-back{display:inline-flex;align-items:center;gap:8px;color:#2563EB!important;text-decoration:none!important;font-size:12px;font-weight:950;margin-bottom:2px;}
        .cv-analysis-hero{background:linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 58%,#EAF2FF 100%);border:1px solid #BFDBFE;border-radius:26px;padding:26px 28px;box-shadow:0 24px 70px rgba(15,23,42,.075);display:grid;grid-template-columns:minmax(0,1.35fr) minmax(360px,.9fr);gap:22px;align-items:center;}
        .cv-analysis-eyebrow{display:inline-flex;align-items:center;gap:8px;border:1px solid #BFDBFE;background:#EFF6FF;color:#2563EB!important;border-radius:999px;padding:8px 12px;font-size:11px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;margin-bottom:14px;}
        .cv-analysis-title{color:#0B1220!important;font-size:38px;font-weight:980;line-height:1.02;letter-spacing:-.045em;margin:0 0 10px 0;}
        .cv-analysis-sub{color:#475569!important;font-size:14px;font-weight:750;line-height:1.65;max-width:820px;margin:0;}
        .cv-analysis-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px;}
        .cv-analysis-btn{display:inline-flex;align-items:center;gap:8px;text-decoration:none!important;border-radius:12px;padding:12px 14px;font-size:12px;font-weight:950;border:1px solid #BFDBFE;background:#F8FAFC;color:#2563EB!important;}
        .cv-analysis-btn.primary{background:#2563EB;color:#FFFFFF!important;border-color:#2563EB;box-shadow:0 16px 30px rgba(37,99,235,.23);}
        .cv-analysis-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}
        .cv-analysis-mini{background:rgba(255,255,255,.9);border:1px solid #E2E8F0;border-radius:18px;padding:15px 16px;box-shadow:0 12px 28px rgba(15,23,42,.045);}
        .cv-analysis-mini span{display:block;color:#64748B!important;font-size:10.5px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;margin-bottom:7px;}
        .cv-analysis-mini strong{display:block;color:#0B1220!important;font-size:25px;font-weight:980;line-height:1;}
        .cv-analysis-mini small{display:block;color:#475569!important;font-size:11.5px;font-weight:800;margin-top:6px;}
        .cv-analysis-section{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;margin-top:12px;margin-bottom:8px;}
        .cv-analysis-section-title{color:#0B1220!important;font-size:21px;font-weight:980;letter-spacing:-.025em;line-height:1.1;}
        .cv-analysis-section-meta{color:#64748B!important;font-size:12px;font-weight:800;margin-top:4px;}
        .cv-analysis-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;align-items:start;}
        .cv-analysis-card{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:22px;padding:20px;box-shadow:0 18px 44px rgba(15,23,42,.055);}
        .cv-analysis-card-title{display:flex;align-items:center;justify-content:space-between;gap:14px;color:#0B1220!important;font-size:16px;font-weight:980;margin-bottom:12px;}
        .cv-analysis-icon{width:38px;height:38px;border-radius:13px;display:flex;align-items:center;justify-content:center;background:#EFF6FF;border:1px solid #BFDBFE;color:#2563EB!important;}
        .cv-analysis-row-list{display:grid;gap:9px;}
        .cv-analysis-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:16px;padding:13px 14px;box-shadow:0 10px 25px rgba(15,23,42,.035);}
        .cv-analysis-row:hover{border-color:#BFDBFE;box-shadow:0 18px 42px rgba(15,23,42,.07);transform:translateY(-1px);transition:all .16s ease;}
        .cv-analysis-row-title{color:#0B1220!important;font-size:13px;font-weight:980;margin-bottom:4px;}
        .cv-analysis-row-meta{color:#64748B!important;font-size:11.5px;font-weight:800;line-height:1.45;}
        .cv-analysis-pills{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end;}
        .cv-analysis-pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:7px 9px;font-size:11px;font-weight:950;border:1px solid #BFDBFE;background:#EFF6FF;color:#2563EB!important;white-space:nowrap;}
        .cv-analysis-pill.good{border-color:#A7F3D0;background:#ECFDF5;color:#047857!important;}.cv-analysis-pill.warn{border-color:#FDE68A;background:#FFFBEB;color:#B45309!important;}.cv-analysis-pill.bad{border-color:#FECACA;background:#FEF2F2;color:#B91C1C!important;}
        .cv-analysis-table-wrap{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:22px;padding:0;box-shadow:0 18px 44px rgba(15,23,42,.055);overflow:hidden;}
        .cv-analysis-table-head{display:flex;justify-content:space-between;align-items:center;padding:18px 20px;border-bottom:1px solid #E2E8F0;gap:14px;}
        .cv-analysis-table-head strong{color:#0B1220!important;font-size:16px;font-weight:980;}.cv-analysis-table-head span{color:#64748B!important;font-size:12px;font-weight:800;}
        .cv-analysis-component-list{display:grid;}
        .cv-analysis-component{display:grid;grid-template-columns:1.2fr 1fr .75fr .75fr auto;gap:12px;align-items:center;padding:13px 20px;border-bottom:1px solid #EEF2F7;}
        .cv-analysis-component:last-child{border-bottom:0;}.cv-analysis-component:hover{background:#F8FAFC;}
        .cv-analysis-component .head{color:#0B1220!important;font-size:13px;font-weight:980;}.cv-analysis-component .sub{color:#64748B!important;font-size:11px;font-weight:800;margin-top:3px;}
        .cv-analysis-empty{border:1px dashed #CBD5E1;background:#F8FAFC;border-radius:18px;padding:24px;text-align:center;color:#64748B!important;font-size:13px;font-weight:800;}
        @media(max-width:1180px){.cv-analysis-hero,.cv-analysis-grid{grid-template-columns:1fr}.cv-analysis-component{grid-template-columns:1fr}.cv-analysis-pills{justify-content:flex-start}.cv-analysis-summary{grid-template-columns:repeat(2,minmax(0,1fr));}}
        @media(max-width:700px){.cv-analysis-summary{grid-template-columns:1fr}.cv-analysis-title{font-size:30px}.cv-analysis-hero{padding:20px}}
        </style>
        """,
        unsafe_allow_html=True,
    )

    if not analysis_id:
        st.markdown('<a class="cv-analysis-back" href="?page=Dashboard" target="_self">' + _lucide("arrow-left", 16) + ' Back to Dashboard</a>', unsafe_allow_html=True)
        st.error("No analysis was selected. Open an analysis from the Dashboard Recent Analyses section.")
        return

    user_id = current_user.get("id")
    try:
        analysis_response = (
            supabase.table("analyses")
            .select("*")
            .eq("user_id", user_id)
            .eq("id", analysis_id)
            .limit(1)
            .execute()
        )
        analysis = (analysis_response.data or [None])[0]
    except Exception as exc:
        st.error(f"Could not load this analysis: {exc}")
        return

    if not analysis:
        st.markdown('<a class="cv-analysis-back" href="?page=Dashboard" target="_self">' + _lucide("arrow-left", 16) + ' Back to Dashboard</a>', unsafe_allow_html=True)
        st.warning("This saved analysis could not be found, or you do not have access to it.")
        return

    parts = _query_table(supabase, "analysis_parts", user_id=user_id, analysis_id=analysis_id)
    alerts = _query_table(supabase, "monitor_alerts", user_id=user_id, analysis_id=analysis_id, order="created_at", limit=10)
    alternatives = _query_table(supabase, "alternative_recommendations", user_id=user_id, analysis_id=analysis_id, order="created_at", limit=10)

    project = _safe(analysis.get("project_name") or analysis.get("filename"), "Saved BOM Analysis")
    filename = _safe(analysis.get("filename"))
    health = _num(analysis.get("health_score"))
    high = _num(analysis.get("high_risk_count"))
    medium = _num(analysis.get("medium_risk_count"))
    low = _num(analysis.get("low_risk_count"))
    total_parts = _num(analysis.get("total_parts"), len(parts)) or len(parts)
    created = analysis.get("created_at")
    risk_status = "Review Recommended" if health < 80 or high else "Healthy"
    health_cls = _health_class(health)

    st.markdown('<a class="cv-analysis-back" href="?page=Dashboard" target="_self">' + _lucide("arrow-left", 16) + ' Back to Dashboard</a>', unsafe_allow_html=True)

    st.markdown(
        f"""
        <div class="cv-analysis-hero">
          <div>
            <div class="cv-analysis-eyebrow">{_lucide('layers',14)} Analysis Workspace</div>
            <h1 class="cv-analysis-title">{html.escape(project)}</h1>
            <p class="cv-analysis-sub">A permanent engineering record for this saved BOM analysis. Review risk, lifecycle status, supplier alerts, replacement readiness, and export-ready data from one workspace.</p>
            <div class="cv-analysis-actions">
              <a class="cv-analysis-btn primary" href="?page=BOM%20Analyzer&analysis_id={html.escape(str(analysis_id), quote=True)}" target="_self">Open in BOM Analyzer →</a>
              <a class="cv-analysis-btn" href="?page=Alternative%20Finder" target="_self">Find Alternatives</a>
              <a class="cv-analysis-btn" href="?page=Reports" target="_self">Export Report</a>
            </div>
          </div>
          <div class="cv-analysis-summary">
            <div class="cv-analysis-mini"><span>Health</span><strong>{health}</strong><small>{risk_status}</small></div>
            <div class="cv-analysis-mini"><span>Parts</span><strong>{total_parts}</strong><small>{html.escape(filename)}</small></div>
            <div class="cv-analysis-mini"><span>High Risk</span><strong>{high}</strong><small>Components needing review</small></div>
            <div class="cv-analysis-mini"><span>Updated</span><strong>{_relative_date(created)}</strong><small>{_date(created)}</small></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Engineering Summary</div><div class="cv-analysis-section-meta">Key signals for this BOM investigation.</div></div></div>',
        unsafe_allow_html=True,
    )

    summary_col, risk_col = st.columns([1.05, 1])
    with summary_col:
        action_text = "Review high-risk components before release." if high else "Continue periodic monitoring for supplier and lifecycle changes."
        st.markdown(
            f"""
            <div class="cv-analysis-card">
              <div class="cv-analysis-card-title"><span>Recommended Next Action</span><div class="cv-analysis-icon">{_lucide('shield',18)}</div></div>
              <div class="cv-analysis-row-list">
                <div class="cv-analysis-row"><div><div class="cv-analysis-row-title">{html.escape(action_text)}</div><div class="cv-analysis-row-meta">{high} high-risk components • {len(alerts)} saved alerts • {len(alternatives)} replacement records</div></div><div class="cv-analysis-pills"><span class="cv-analysis-pill {health_cls}">{health} health</span></div></div>
                <div class="cv-analysis-row"><div><div class="cv-analysis-row-title">Source file</div><div class="cv-analysis-row-meta">{html.escape(filename)} • saved {_relative_date(created)}</div></div><div class="cv-analysis-pills"><span class="cv-analysis-pill">Saved</span></div></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with risk_col:
        risk_html = "".join(
            [
                f'<div class="cv-analysis-row"><div><div class="cv-analysis-row-title">{label}</div><div class="cv-analysis-row-meta">Component count in this analysis</div></div><div class="cv-analysis-pills"><span class="cv-analysis-pill {cls}">{value}</span></div></div>'
                for label, value, cls in [
                    ("High Risk", high, "bad" if high else "good"),
                    ("Medium Risk", medium, "warn" if medium else "good"),
                    ("Low Risk", low, "good"),
                ]
            ]
        )
        st.markdown(
            f"""
            <div class="cv-analysis-card">
              <div class="cv-analysis-card-title"><span>Risk Breakdown</span><div class="cv-analysis-icon">{_lucide('alert',18)}</div></div>
              <div class="cv-analysis-row-list">{risk_html}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    chart_col, alerts_col = st.columns([1.05, 1])
    with chart_col:
        st.markdown('<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Risk Distribution</div><div class="cv-analysis-section-meta">High, medium, and low risk components.</div></div></div>', unsafe_allow_html=True)
        if high or medium or low:
            risk_df = pd.DataFrame({"Risk": ["High", "Medium", "Low"], "Count": [high, medium, low]})
            fig = px.pie(risk_df, names="Risk", values="Count", hole=0.58)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(height=330, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.05, x=0.5, xanchor="center"), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.markdown('<div class="cv-analysis-empty">No risk distribution is available for this analysis yet.</div>', unsafe_allow_html=True)
    with alerts_col:
        st.markdown('<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Supplier & Lifecycle Alerts</div><div class="cv-analysis-section-meta">Alerts associated with this analysis.</div></div></div>', unsafe_allow_html=True)
        if alerts:
            rows = []
            for alert in alerts[:5]:
                part = html.escape(_safe(alert.get("part_number") or alert.get("mpn"), "Component"))
                alert_type = html.escape(_safe(alert.get("alert_type"), "Alert"))
                msg = html.escape(_safe(alert.get("alert_message"), "Supplier or lifecycle change detected."))
                severity = _safe(alert.get("severity") or alert.get("severity_display"), "High")
                rows.append(f'<div class="cv-analysis-row"><div><div class="cv-analysis-row-title">{part}</div><div class="cv-analysis-row-meta">{alert_type} • {msg}</div></div><div class="cv-analysis-pills"><span class="cv-analysis-pill bad">{html.escape(severity)}</span></div></div>')
            st.markdown(f'<div class="cv-analysis-row-list">{"".join(rows)}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="cv-analysis-empty">No saved supplier alerts are attached to this analysis yet.</div>', unsafe_allow_html=True)

    st.markdown('<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Component Risk Report</div><div class="cv-analysis-section-meta">Parts saved for this analysis. Open in BOM Analyzer for full filtering and exports.</div></div><a class="cv-analysis-btn" href="?page=BOM%20Analyzer&analysis_id=' + html.escape(str(analysis_id), quote=True) + '" target="_self">Open full report →</a></div>', unsafe_allow_html=True)

    if parts:
        top_parts = sorted(parts, key=lambda x: _num(x.get("risk_score"), 0), reverse=True)[:12]
        rows = []
        for p in top_parts:
            mpn = html.escape(_safe(p.get("mpn") or p.get("MPN"), "Unknown MPN"))
            mfg = html.escape(_safe(p.get("manufacturer") or p.get("Manufacturer"), "Unknown manufacturer"))
            status = html.escape(_safe(p.get("lifecycle_status") or p.get("Lifecycle Status"), "Unknown"))
            stock = _num(p.get("stock_available") or p.get("Stock Available"), 0)
            risk_score = _num(p.get("risk_score") or p.get("Risk Score"), 0)
            level = _safe(p.get("risk_level") or p.get("Risk Level"), "Low")
            cls = _risk_class(level, risk_score)
            supplier_count = _num(p.get("supplier_count") or p.get("Supplier Count"), 0)
            rows.append(
                f'<div class="cv-analysis-component">'
                f'<div><div class="head">{mpn}</div><div class="sub">{mfg}</div></div>'
                f'<div><div class="head">{status}</div><div class="sub">Lifecycle</div></div>'
                f'<div><div class="head">{stock:,}</div><div class="sub">Stock</div></div>'
                f'<div><div class="head">{supplier_count}</div><div class="sub">Suppliers</div></div>'
                f'<div class="cv-analysis-pills"><span class="cv-analysis-pill {cls}">{html.escape(level)}</span></div>'
                f'</div>'
            )
        st.markdown(
            f"""
            <div class="cv-analysis-table-wrap">
              <div class="cv-analysis-table-head"><div><strong>Top Components</strong><br><span>Sorted by risk score where available.</span></div><span>{len(parts)} total parts</span></div>
              <div class="cv-analysis-component-list">{"".join(rows)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div class="cv-analysis-empty">No saved part rows were found for this analysis. The summary record exists, but detailed component data is missing.</div>', unsafe_allow_html=True)

    st.markdown('<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Replacement Readiness</div><div class="cv-analysis-section-meta">Alternative recommendation records linked to this analysis.</div></div></div>', unsafe_allow_html=True)
    if alternatives:
        alt_rows = []
        for alt in alternatives[:6]:
            original = html.escape(_safe(alt.get("original_mpn") or alt.get("mpn") or alt.get("part_number"), "Original component"))
            recommendation = html.escape(_safe(alt.get("alternative_mpn") or alt.get("recommended_mpn") or alt.get("candidate_mpn") or alt.get("replacement_mpn"), "Candidate available"))
            supplier = html.escape(_safe(alt.get("supplier") or alt.get("source"), "Supplier review"))
            alt_rows.append(f'<div class="cv-analysis-row"><div><div class="cv-analysis-row-title">{original} → {recommendation}</div><div class="cv-analysis-row-meta">{supplier}</div></div><div class="cv-analysis-pills"><span class="cv-analysis-pill good">Alternative</span></div></div>')
        st.markdown(f'<div class="cv-analysis-row-list">{"".join(alt_rows)}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="cv-analysis-empty">No replacement candidates are linked yet. Use Alternative Finder to validate lower-risk replacements.</div>', unsafe_allow_html=True)

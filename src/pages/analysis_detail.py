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
    """Render a dedicated saved-analysis workspace with enterprise-style tabs."""

    analysis_id = ""
    if _qp_value:
        analysis_id = _safe(_qp_value("analysis_id", ""), "")
    if not analysis_id:
        analysis_id = _safe(st.query_params.get("analysis_id", ""), "")

    active_tab = "overview"
    if _qp_value:
        active_tab = _safe(_qp_value("tab", "overview"), "overview").lower()
    else:
        active_tab = _safe(st.query_params.get("tab", "overview"), "overview").lower()
    valid_tabs = {"overview", "components", "suppliers", "alternatives", "reports", "history"}
    if active_tab not in valid_tabs:
        active_tab = "overview"

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
        .cv-tabbar{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 8px 0;padding:6px;background:rgba(241,245,249,.75);border:1px solid #E2E8F0;border-radius:18px;box-shadow:inset 0 1px 0 rgba(255,255,255,.8);}
        .cv-tabbar a{display:inline-flex;align-items:center;gap:8px;padding:10px 13px;border-radius:13px;color:#475569!important;text-decoration:none!important;font-size:12px;font-weight:950;border:1px solid transparent;}
        .cv-tabbar a.active{background:#FFFFFF;color:#2563EB!important;border-color:#BFDBFE;box-shadow:0 10px 24px rgba(37,99,235,.10);}
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
        .cv-ai-summary{background:linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 100%);border:1px solid #BFDBFE;border-radius:22px;padding:20px;box-shadow:0 18px 44px rgba(37,99,235,.08);}
        .cv-ai-summary p{color:#334155!important;font-size:14px;font-weight:750;line-height:1.7;margin:0;}
        .cv-metric-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:12px;}
        .cv-metric-cell{border:1px solid #E2E8F0;border-radius:16px;padding:13px;background:#FFFFFF;}
        .cv-metric-cell span{display:block;color:#64748B!important;font-size:10.5px;font-weight:950;letter-spacing:.08em;text-transform:uppercase;}.cv-metric-cell strong{display:block;color:#0B1220!important;font-size:22px;font-weight:980;margin-top:6px;}
        .cv-analysis-table-wrap{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:22px;padding:0;box-shadow:0 18px 44px rgba(15,23,42,.055);overflow:hidden;}
        .cv-analysis-table-head{display:flex;justify-content:space-between;align-items:center;padding:18px 20px;border-bottom:1px solid #E2E8F0;gap:14px;}
        .cv-analysis-table-head strong{color:#0B1220!important;font-size:16px;font-weight:980;}.cv-analysis-table-head span{color:#64748B!important;font-size:12px;font-weight:800;}
        .cv-analysis-component-list{display:grid;}
        .cv-analysis-component{display:grid;grid-template-columns:1.15fr .95fr .7fr .65fr .7fr auto;gap:12px;align-items:center;padding:13px 20px;border-bottom:1px solid #EEF2F7;}
        .cv-analysis-component:last-child{border-bottom:0;}.cv-analysis-component:hover{background:#F8FAFC;}
        .cv-analysis-component .head{color:#0B1220!important;font-size:13px;font-weight:980;}.cv-analysis-component .sub{color:#64748B!important;font-size:11px;font-weight:800;margin-top:3px;}
        .cv-timeline{position:relative;display:grid;gap:10px;margin-left:4px;}.cv-timeline:before{content:"";position:absolute;left:18px;top:8px;bottom:8px;width:2px;background:#DBEAFE;}
        .cv-time-item{position:relative;display:grid;grid-template-columns:42px minmax(0,1fr);gap:10px;align-items:start;}.cv-time-dot{width:36px;height:36px;border-radius:13px;background:#EFF6FF;border:1px solid #BFDBFE;color:#2563EB;display:flex;align-items:center;justify-content:center;z-index:1;}.cv-time-card{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:16px;padding:12px 14px;box-shadow:0 10px 24px rgba(15,23,42,.04);}
        .cv-analysis-empty{border:1px dashed #CBD5E1;background:#F8FAFC;border-radius:18px;padding:24px;text-align:center;color:#64748B!important;font-size:13px;font-weight:800;}
        @media(max-width:1180px){.cv-analysis-hero,.cv-analysis-grid{grid-template-columns:1fr}.cv-analysis-component{grid-template-columns:1fr}.cv-analysis-pills{justify-content:flex-start}.cv-analysis-summary,.cv-metric-strip{grid-template-columns:repeat(2,minmax(0,1fr));}}
        @media(max-width:700px){.cv-analysis-summary,.cv-metric-strip{grid-template-columns:1fr}.cv-analysis-title{font-size:30px}.cv-analysis-hero{padding:20px}}
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
    alerts = _query_table(supabase, "monitor_alerts", user_id=user_id, analysis_id=analysis_id, order="created_at", limit=25)
    alternatives = _query_table(supabase, "alternative_recommendations", user_id=user_id, analysis_id=analysis_id, order="created_at", limit=25)

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
    action_text = "Review high-risk components before release." if high else "Continue periodic monitoring for supplier and lifecycle changes."

    base_href = f"?page=Analysis%20Details&analysis_id={html.escape(str(analysis_id), quote=True)}"
    tab_defs = [
        ("overview", "Overview", "layers"),
        ("components", "Components", "file"),
        ("suppliers", "Suppliers", "factory"),
        ("alternatives", "Alternatives", "replace"),
        ("reports", "Reports", "download"),
        ("history", "History", "activity"),
    ]

    def render_tabs():
        links = []
        for key, label, icon in tab_defs:
            cls = "active" if key == active_tab else ""
            links.append(f'<a class="{cls}" href="{base_href}&tab={key}" target="_self">{_lucide(icon,14)} {label}</a>')
        st.markdown(f'<div class="cv-tabbar">{"".join(links)}</div>', unsafe_allow_html=True)

    def component_rows(limit: int | None = None):
        if not parts:
            return ""
        rows = []
        data = sorted(parts, key=lambda x: _num(x.get("risk_score"), 0), reverse=True)
        if limit:
            data = data[:limit]
        for p in data:
            mpn = html.escape(_safe(p.get("mpn") or p.get("MPN"), "Unknown MPN"))
            mfg = html.escape(_safe(p.get("manufacturer") or p.get("Manufacturer"), "Unknown manufacturer"))
            status = html.escape(_safe(p.get("lifecycle_status") or p.get("Lifecycle Status"), "Unknown"))
            stock = _num(p.get("stock_available") or p.get("Stock Available"), 0)
            risk_score = _num(p.get("risk_score") or p.get("Risk Score"), 0)
            level = _safe(p.get("risk_level") or p.get("Risk Level"), "Low")
            cls = _risk_class(level, risk_score)
            supplier_count = _num(p.get("supplier_count") or p.get("Supplier Count"), 0)
            alternatives_label = "Review" if cls != "good" else "Available"
            rows.append(
                f'<div class="cv-analysis-component">'
                f'<div><div class="head">{mpn}</div><div class="sub">{mfg}</div></div>'
                f'<div><div class="head">{status}</div><div class="sub">Lifecycle</div></div>'
                f'<div><div class="head">{stock:,}</div><div class="sub">Stock</div></div>'
                f'<div><div class="head">{supplier_count}</div><div class="sub">Suppliers</div></div>'
                f'<div><div class="head">{alternatives_label}</div><div class="sub">Alternatives</div></div>'
                f'<div class="cv-analysis-pills"><span class="cv-analysis-pill {cls}">{html.escape(level)}</span></div>'
                f'</div>'
            )
        return "".join(rows)

    st.markdown('<a class="cv-analysis-back" href="?page=Dashboard" target="_self">' + _lucide("arrow-left", 16) + ' Back to Dashboard</a>', unsafe_allow_html=True)

    st.markdown(
        f"""
        <div class="cv-analysis-hero">
          <div>
            <div class="cv-analysis-eyebrow">{_lucide('layers',14)} Analysis Workspace</div>
            <h1 class="cv-analysis-title">{html.escape(project)}</h1>
            <p class="cv-analysis-sub">A permanent engineering record for this saved BOM analysis. Review risk, lifecycle status, supplier alerts, replacement readiness, reports, and history from one workspace.</p>
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

    render_tabs()

    if active_tab == "overview":
        st.markdown('<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Engineering Summary</div><div class="cv-analysis-section-meta">AI-style workspace summary generated from saved analysis data.</div></div></div>', unsafe_allow_html=True)
        summary_text = (
            f"Cadivor analyzed <strong>{total_parts}</strong> components from <strong>{html.escape(filename)}</strong>. "
            f"The BOM has a health score of <strong>{health}</strong> and is currently classified as <strong>{risk_status}</strong>. "
            f"There are <strong>{high}</strong> high-risk components, <strong>{medium}</strong> medium-risk components, and <strong>{len(alerts)}</strong> supplier or lifecycle alerts attached to this analysis. "
            f"Recommended action: <strong>{html.escape(action_text)}</strong>"
        )
        st.markdown(
            f'<div class="cv-ai-summary"><div class="cv-analysis-card-title"><span>Engineering Intelligence Brief</span><div class="cv-analysis-icon">{_lucide("activity",18)}</div></div><p>{summary_text}</p><div class="cv-metric-strip"><div class="cv-metric-cell"><span>Health</span><strong>{health}</strong></div><div class="cv-metric-cell"><span>High Risk</span><strong>{high}</strong></div><div class="cv-metric-cell"><span>Alerts</span><strong>{len(alerts)}</strong></div><div class="cv-metric-cell"><span>Alternatives</span><strong>{len(alternatives)}</strong></div></div></div>',
            unsafe_allow_html=True,
        )
        left, right = st.columns([1.05, 1])
        with left:
            st.markdown('<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Risk Distribution</div><div class="cv-analysis-section-meta">High, medium, and low risk components.</div></div></div>', unsafe_allow_html=True)
            if high or medium or low:
                risk_df = pd.DataFrame({"Risk": ["High", "Medium", "Low"], "Count": [high, medium, low]})
                fig = px.pie(risk_df, names="Risk", values="Count", hole=0.62)
                fig.update_traces(textposition="inside", textinfo="percent+label")
                fig.update_layout(height=330, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.05, x=0.5, xanchor="center"), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.markdown('<div class="cv-analysis-empty">No risk distribution is available for this analysis yet.</div>', unsafe_allow_html=True)
        with right:
            st.markdown('<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Priority Signals</div><div class="cv-analysis-section-meta">Key review areas for this analysis.</div></div></div>', unsafe_allow_html=True)
            risk_html = "".join([
                f'<div class="cv-analysis-row"><div><div class="cv-analysis-row-title">{label}</div><div class="cv-analysis-row-meta">Component count in this analysis</div></div><div class="cv-analysis-pills"><span class="cv-analysis-pill {cls}">{value}</span></div></div>'
                for label, value, cls in [("High Risk", high, "bad" if high else "good"), ("Medium Risk", medium, "warn" if medium else "good"), ("Low Risk", low, "good")]
            ])
            st.markdown(f'<div class="cv-analysis-card"><div class="cv-analysis-card-title"><span>Risk Breakdown</span><div class="cv-analysis-icon">{_lucide("alert",18)}</div></div><div class="cv-analysis-row-list">{risk_html}</div></div>', unsafe_allow_html=True)
        st.markdown('<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Top Components</div><div class="cv-analysis-section-meta">Highest priority rows from this BOM.</div></div><a class="cv-analysis-btn" href="' + base_href + '&tab=components" target="_self">View all components →</a></div>', unsafe_allow_html=True)
        if parts:
            st.markdown(f'<div class="cv-analysis-table-wrap"><div class="cv-analysis-table-head"><div><strong>Component Risk Preview</strong><br><span>Sorted by risk score where available.</span></div><span>{len(parts)} total parts</span></div><div class="cv-analysis-component-list">{component_rows(6)}</div></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="cv-analysis-empty">No saved part rows were found for this analysis.</div>', unsafe_allow_html=True)

    elif active_tab == "components":
        st.markdown('<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Components</div><div class="cv-analysis-section-meta">Manufacturer part risk, lifecycle, stock, supplier coverage, and replacement readiness.</div></div><a class="cv-analysis-btn" href="?page=BOM%20Analyzer&analysis_id=' + html.escape(str(analysis_id), quote=True) + '" target="_self">Open full report →</a></div>', unsafe_allow_html=True)
        if parts:
            st.markdown(f'<div class="cv-analysis-table-wrap"><div class="cv-analysis-table-head"><div><strong>Enterprise Component Table</strong><br><span>Includes lifecycle, stock, supplier count, and risk status.</span></div><span>{len(parts)} total parts</span></div><div class="cv-analysis-component-list">{component_rows()}</div></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="cv-analysis-empty">No saved component rows were found for this analysis.</div>', unsafe_allow_html=True)

    elif active_tab == "suppliers":
        st.markdown('<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Supplier & Lifecycle Intelligence</div><div class="cv-analysis-section-meta">Lifecycle, supplier, stock, and monitoring alerts linked to this analysis.</div></div></div>', unsafe_allow_html=True)
        col1, col2 = st.columns([1,1])
        with col1:
            avg_suppliers = round(sum(_num(p.get("supplier_count") or p.get("Supplier Count"), 0) for p in parts) / max(1, len(parts)), 1) if parts else 0
            no_stock = sum(1 for p in parts if _num(p.get("stock_available") or p.get("Stock Available"), 0) <= 0)
            st.markdown(f'<div class="cv-analysis-card"><div class="cv-analysis-card-title"><span>Supplier Coverage</span><div class="cv-analysis-icon">{_lucide("factory",18)}</div></div><div class="cv-metric-strip"><div class="cv-metric-cell"><span>Avg Suppliers</span><strong>{avg_suppliers}</strong></div><div class="cv-metric-cell"><span>No Stock</span><strong>{no_stock}</strong></div><div class="cv-metric-cell"><span>Alerts</span><strong>{len(alerts)}</strong></div><div class="cv-metric-cell"><span>Parts</span><strong>{total_parts}</strong></div></div></div>', unsafe_allow_html=True)
        with col2:
            lifecycle_counts = {}
            for p in parts:
                status = _safe(p.get("lifecycle_status") or p.get("Lifecycle Status"), "Unknown")
                lifecycle_counts[status] = lifecycle_counts.get(status, 0) + 1
            rows = ''.join([f'<div class="cv-analysis-row"><div><div class="cv-analysis-row-title">{html.escape(k)}</div><div class="cv-analysis-row-meta">Lifecycle status</div></div><span class="cv-analysis-pill good">{v}</span></div>' for k,v in list(lifecycle_counts.items())[:6]]) or '<div class="cv-analysis-empty">No lifecycle data available.</div>'
            st.markdown(f'<div class="cv-analysis-card"><div class="cv-analysis-card-title"><span>Lifecycle Mix</span><div class="cv-analysis-icon">{_lucide("activity",18)}</div></div><div class="cv-analysis-row-list">{rows}</div></div>', unsafe_allow_html=True)
        st.markdown('<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Alerts</div><div class="cv-analysis-section-meta">Supplier and lifecycle events detected for this analysis.</div></div></div>', unsafe_allow_html=True)
        if alerts:
            rows = []
            for alert in alerts:
                part = html.escape(_safe(alert.get("part_number") or alert.get("mpn"), "Component"))
                alert_type = html.escape(_safe(alert.get("alert_type"), "Alert"))
                msg = html.escape(_safe(alert.get("alert_message"), "Supplier or lifecycle change detected."))
                severity = _safe(alert.get("severity") or alert.get("severity_display"), "High")
                rows.append(f'<div class="cv-analysis-row"><div><div class="cv-analysis-row-title">{part}</div><div class="cv-analysis-row-meta">{alert_type} • {msg}</div></div><div class="cv-analysis-pills"><span class="cv-analysis-pill bad">{html.escape(severity)}</span></div></div>')
            st.markdown(f'<div class="cv-analysis-row-list">{"".join(rows)}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="cv-analysis-empty">No saved supplier alerts are attached to this analysis yet.</div>', unsafe_allow_html=True)

    elif active_tab == "alternatives":
        st.markdown('<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Replacement Readiness</div><div class="cv-analysis-section-meta">Alternative recommendation records linked to this analysis.</div></div><a class="cv-analysis-btn primary" href="?page=Alternative%20Finder" target="_self">Find Alternatives →</a></div>', unsafe_allow_html=True)
        if alternatives:
            alt_rows = []
            for alt in alternatives:
                original = html.escape(_safe(alt.get("original_mpn") or alt.get("mpn") or alt.get("part_number"), "Original component"))
                recommendation = html.escape(_safe(alt.get("alternative_mpn") or alt.get("recommended_mpn") or alt.get("candidate_mpn") or alt.get("replacement_mpn"), "Candidate available"))
                supplier = html.escape(_safe(alt.get("supplier") or alt.get("source"), "Supplier review"))
                alt_rows.append(f'<div class="cv-analysis-row"><div><div class="cv-analysis-row-title">{original} → {recommendation}</div><div class="cv-analysis-row-meta">{supplier}</div></div><div class="cv-analysis-pills"><span class="cv-analysis-pill good">Alternative</span></div></div>')
            st.markdown(f'<div class="cv-analysis-row-list">{"".join(alt_rows)}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="cv-analysis-empty">No replacement candidates are linked yet. Use Alternative Finder to validate lower-risk replacements.</div>', unsafe_allow_html=True)

    elif active_tab == "reports":
        st.markdown('<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Reports & Exports</div><div class="cv-analysis-section-meta">Export-ready outputs for engineering, sourcing, and management review.</div></div></div>', unsafe_allow_html=True)
        report_rows = [
            ("Executive Summary", "Management-ready BOM health, risk, and recommended actions.", "PDF report"),
            ("Detailed Risk Workbook", "Component-level risk, lifecycle, stock, and supplier data.", "Excel export"),
            ("Supplier Review Pack", "Lifecycle alerts and sourcing intelligence for procurement.", "Review pack"),
        ]
        rows = ''.join([f'<div class="cv-analysis-row"><div><div class="cv-analysis-row-title">{title}</div><div class="cv-analysis-row-meta">{desc}</div></div><div class="cv-analysis-pills"><span class="cv-analysis-pill">{pill}</span></div></div>' for title,desc,pill in report_rows])
        st.markdown(f'<div class="cv-analysis-card"><div class="cv-analysis-card-title"><span>Available Reports</span><div class="cv-analysis-icon">{_lucide("download",18)}</div></div><div class="cv-analysis-row-list">{rows}</div><div class="cv-analysis-actions"><a class="cv-analysis-btn primary" href="?page=Reports" target="_self">Open Reports Center →</a></div></div>', unsafe_allow_html=True)

    elif active_tab == "history":
        st.markdown('<div class="cv-analysis-section"><div><div class="cv-analysis-section-title">Analysis Timeline</div><div class="cv-analysis-section-meta">Audit-style history for this engineering record.</div></div></div>', unsafe_allow_html=True)
        timeline = [
            ("Analysis saved", f"{project} was saved to the workspace from {filename}.", _relative_date(created), "file"),
            ("Risk profile calculated", f"Health {health} • {high} high risk • {medium} medium risk • {low} low risk.", _date(created), "shield"),
            ("Supplier monitoring linked", f"{len(alerts)} supplier or lifecycle alerts are associated with this analysis.", "Current", "activity"),
            ("Replacement readiness checked", f"{len(alternatives)} alternative recommendation records are linked.", "Current", "replace"),
        ]
        items = ''.join([f'<div class="cv-time-item"><div class="cv-time-dot">{_lucide(icon,16)}</div><div class="cv-time-card"><div class="cv-analysis-row-title">{html.escape(title)}</div><div class="cv-analysis-row-meta">{html.escape(desc)} • {html.escape(time)}</div></div></div>' for title,desc,time,icon in timeline])
        st.markdown(f'<div class="cv-analysis-card"><div class="cv-timeline">{items}</div></div>', unsafe_allow_html=True)

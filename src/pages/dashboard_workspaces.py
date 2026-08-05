"""Sprint 67.2 — Dashboard workspace renderers and lazy context preparation."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.living_workspace import (
    render_portfolio_project_summaries,
    render_team_workload_section,
)
from src.ui.cadivor_design_system import MetricCard, cadivor_engineering_dataframe, render_kpi_row_safe

DASHBOARD_WORKSPACES: tuple[str, ...] = (
    "Engineering Overview",
    "Portfolio Intelligence",
    "Analytics",
    "Monitoring",
)


def inject_dashboard_workspace_styles() -> None:
    """Inject dashboard page styles once per Dashboard visit."""
    from src.pages.dashboard import inject_dashboard_page_styles

    inject_dashboard_page_styles()


def _lucide_icon(name: str, size: int = 18) -> str:
    icons = {
        "file": """<svg width='{s}' height='{s}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z'/><path d='M14 2v4a2 2 0 0 0 2 2h4'/></svg>""",
    }
    return icons.get(name, icons["file"]).format(s=size)


def _is_real_saved_analysis(row: Mapping[str, Any]) -> bool:
    if not isinstance(row, dict) or not row.get("id"):
        return False
    meaningful = (
        row.get("filename"),
        row.get("project_name"),
        row.get("created_at"),
        row.get("total_parts"),
        row.get("health_score"),
    )
    return any(value not in (None, "", 0, 0.0) for value in meaningful)


def _fmt_date(value: Any) -> str:
    if not value:
        return "—"
    try:
        return pd.to_datetime(value).strftime("%b %d")
    except Exception:
        return str(value)[:10]


def _activity_relative(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return "Recently"
    now = pd.Timestamp.now(tz="UTC")
    seconds = max(0, int((now - parsed).total_seconds()))
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = seconds // 86400
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days} days ago"
    return parsed.strftime("%b %d, %Y")


def build_portfolio_dashboard_context(
    *,
    analysis_data: List[Dict[str, Any]],
    alert_data: List[Dict[str, Any]],
    alternative_history: List[Dict[str, Any]],
    get_user_profile: Callable[..., Dict[str, Any]],
    current_user: Mapping[str, Any],
) -> Dict[str, Any]:
    """Prepare portfolio/analytics context from already-loaded Dashboard data."""
    total_analyses = len(analysis_data)
    if analysis_data:
        avg_health_score = int(
            sum(item.get("health_score", 0) or 0 for item in analysis_data)
            / max(1, total_analyses)
        )
        total_high_risk = sum(item.get("high_risk_count", 0) or 0 for item in analysis_data)
        total_medium_risk = sum(item.get("medium_risk_count", 0) or 0 for item in analysis_data)
        total_low_risk = sum(item.get("low_risk_count", 0) or 0 for item in analysis_data)
        total_components = sum(item.get("total_parts", 0) or 0 for item in analysis_data)
        latest_analysis = analysis_data[0]
    else:
        avg_health_score = 0
        total_high_risk = 0
        total_medium_risk = 0
        total_low_risk = 0
        total_components = 0
        latest_analysis = None

    alert_count = len(alert_data)
    high_alert_count = sum(1 for item in alert_data if "high" in str(item.get("severity", "")).lower())

    if avg_health_score >= 80:
        health_badge = "Healthy Portfolio"
        health_kind = "success"
    elif avg_health_score >= 55:
        health_badge = "Review Recommended"
        health_kind = "warning"
    elif avg_health_score > 0:
        health_badge = "Critical Review"
        health_kind = "danger"
    else:
        health_badge = "No Data Yet"
        health_kind = ""

    profile = get_user_profile(current_user)
    user_name = profile["full_name"].split()[0] if profile.get("full_name") else "there"
    hour = datetime.now().hour
    greeting_prefix = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"

    prev_health = None
    if analysis_data and len(analysis_data) >= 2:
        try:
            prev_health = int(analysis_data[1].get("health_score", 0) or 0)
        except Exception:
            prev_health = None
    health_delta = (avg_health_score - prev_health) if prev_health is not None else 0
    health_delta_label = f"{health_delta:+d}" if prev_health is not None else "—"

    latest_project = (latest_analysis or {}).get("project_name") or (latest_analysis or {}).get("filename") or "No saved BOM yet"
    latest_parts = int((latest_analysis or {}).get("total_parts", 0) or 0)
    latest_health = int((latest_analysis or {}).get("health_score", avg_health_score) or 0)
    latest_high_risk = int((latest_analysis or {}).get("high_risk_count", 0) or 0)
    latest_medium_risk = int((latest_analysis or {}).get("medium_risk_count", 0) or 0)
    latest_date = _fmt_date((latest_analysis or {}).get("created_at", ""))
    alternatives_found = len(alternative_history)

    trend_records = []
    for item in analysis_data[:30]:
        created_at = pd.to_datetime(item.get("created_at"), errors="coerce", utc=True)
        if pd.isna(created_at):
            continue
        trend_records.append(
            {
                "created_at": created_at,
                "project": str(
                    item.get("project_name")
                    or item.get("filename")
                    or item.get("source_filename")
                    or "Saved BOM"
                ),
                "health": int(item.get("health_score", 0) or 0),
                "high_risk": int(item.get("high_risk_count", 0) or 0),
                "medium_risk": int(item.get("medium_risk_count", 0) or 0),
            }
        )
    trend_records.sort(key=lambda row: row["created_at"])
    latest_trend = trend_records[-1] if trend_records else None
    previous_trend = trend_records[-2] if len(trend_records) >= 2 else None
    trend_health_change = (
        latest_trend["health"] - previous_trend["health"]
        if latest_trend and previous_trend else 0
    )
    trend_high_risk_change = (
        latest_trend["high_risk"] - previous_trend["high_risk"]
        if latest_trend and previous_trend else 0
    )

    project_history: Dict[str, List[Dict[str, Any]]] = {}
    for row in trend_records:
        project_history.setdefault(row["project"], []).append(row)

    declining_projects = []
    for project_name, records in project_history.items():
        if len(records) < 2:
            continue
        earlier, current = records[-2], records[-1]
        health_change = current["health"] - earlier["health"]
        risk_change = current["high_risk"] - earlier["high_risk"]
        if health_change < 0 or risk_change > 0:
            declining_projects.append(
                {
                    "project": project_name,
                    "health_change": health_change,
                    "risk_change": risk_change,
                    "current_health": current["health"],
                }
            )
    declining_projects.sort(key=lambda row: (row["health_change"], -row["risk_change"]))

    def _activity_datetime(value):
        fallback = pd.Timestamp("1970-01-01", tz="UTC")
        if not value:
            return fallback
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
        return fallback if pd.isna(parsed) else parsed

    recent_activity = []
    for item in analysis_data[:12]:
        project_name = (
            item.get("project_name")
            or item.get("filename")
            or item.get("source_filename")
            or "Saved BOM analysis"
        )
        analysis_id = str(item.get("id") or "")
        health = int(item.get("health_score", 0) or 0)
        parts = int(item.get("total_parts", 0) or 0)
        recent_activity.append(
            {
                "category": "Analyses",
                "type": "BOM Analysis",
                "title": str(project_name),
                "copy": f"Analysis completed with health {health}/100 across {parts} component record(s).",
                "created_at": item.get("created_at"),
                "href": (
                    f"?page=Analysis%20Details&analysis_id={html.escape(analysis_id, quote=True)}"
                    if analysis_id
                    else "?page=BOM%20Analyzer"
                ),
                "action": "Open project",
            }
        )

    for item in alert_data[:16]:
        part_number = item.get("part_number") or item.get("mpn") or "Monitored component"
        alert_type = item.get("alert_type") or item.get("change_type") or "Monitoring alert"
        message = (
            item.get("alert_message")
            or item.get("message")
            or item.get("description")
            or "A monitored component changed."
        )
        recent_activity.append(
            {
                "category": "Monitoring",
                "type": str(alert_type),
                "title": str(part_number),
                "copy": str(message),
                "created_at": item.get("created_at") or item.get("detected_at"),
                "href": "?page=Monitoring",
                "action": "Review alert",
            }
        )

    for item in alternative_history[:10]:
        original = (
            item.get("original_part")
            or item.get("original_mpn")
            or item.get("part_number")
            or "Component"
        )
        candidate = (
            item.get("alternative_part")
            or item.get("candidate_mpn")
            or item.get("recommended_part")
            or "replacement candidate"
        )
        recent_activity.append(
            {
                "category": "Replacements",
                "type": "Replacement Review",
                "title": str(original),
                "copy": f"Replacement candidate {candidate} was recorded for engineering review.",
                "created_at": item.get("created_at") or item.get("updated_at"),
                "href": "?page=Alternative%20Finder",
                "action": "Open replacement",
            }
        )

    recent_activity.sort(key=lambda event: _activity_datetime(event.get("created_at")), reverse=True)
    grouped_activity = []
    for event in recent_activity:
        signature = (
            str(event.get("category") or ""),
            str(event.get("type") or ""),
            str(event.get("title") or ""),
            str(event.get("copy") or ""),
        )
        if grouped_activity and grouped_activity[-1].get("_signature") == signature:
            grouped_activity[-1]["repeat_count"] += 1
            continue
        grouped_event = dict(event)
        grouped_event["repeat_count"] = 1
        grouped_event["_signature"] = signature
        grouped_activity.append(grouped_event)

    now_utc = pd.Timestamp.now(tz="UTC")
    recent_alerts_7d = 0
    lifecycle_alert_count = 0
    stock_alert_count = 0
    price_alert_count = 0
    for alert in alert_data:
        alert_time = pd.to_datetime(
            alert.get("created_at") or alert.get("detected_at"),
            errors="coerce",
            utc=True,
        )
        if not pd.isna(alert_time) and (now_utc - alert_time).days <= 7:
            recent_alerts_7d += 1
        blob = " ".join(
            str(alert.get(key) or "")
            for key in ("alert_type", "alert_message", "change_type", "message")
        ).lower()
        if "lifecycle" in blob:
            lifecycle_alert_count += 1
        if "stock" in blob or "inventory" in blob:
            stock_alert_count += 1
        if "price" in blob:
            price_alert_count += 1

    healthy_count = max(0, total_components - total_high_risk - total_medium_risk)
    total_for_pct = max(1, total_components or (total_high_risk + total_medium_risk + total_low_risk + healthy_count))
    healthy_pct = round(healthy_count / total_for_pct * 100)
    medium_pct = round(total_medium_risk / total_for_pct * 100)
    critical_pct = max(0, 100 - healthy_pct - medium_pct)

    if latest_trend and previous_trend:
        health_direction = (
            "improved" if trend_health_change > 0 else "declined" if trend_health_change < 0 else "held steady"
        )
        risk_direction = (
            "increased" if trend_high_risk_change > 0 else "decreased" if trend_high_risk_change < 0 else "did not change"
        )
        trend_summary = (
            f"Portfolio health {health_direction} by {abs(trend_health_change)} point(s), "
            f"while high-risk component exposure {risk_direction} by "
            f"{abs(trend_high_risk_change)} compared with the previous saved analysis."
        )
    elif latest_trend:
        trend_summary = (
            "One saved analysis is available. Save another analysis to begin measuring portfolio movement."
        )
    else:
        trend_summary = (
            "No saved analysis history is available yet. Analyze and save a BOM to begin tracking trends."
        )

    return {
        "analysis_data": analysis_data,
        "alert_data": alert_data,
        "alternative_history": alternative_history,
        "total_analyses": total_analyses,
        "avg_health_score": avg_health_score,
        "total_high_risk": total_high_risk,
        "total_medium_risk": total_medium_risk,
        "total_low_risk": total_low_risk,
        "total_components": total_components,
        "alert_count": alert_count,
        "high_alert_count": high_alert_count,
        "health_badge": health_badge,
        "health_kind": health_kind,
        "user_name": user_name,
        "greeting_prefix": greeting_prefix,
        "health_delta": health_delta,
        "health_delta_label": health_delta_label,
        "latest_project": latest_project,
        "latest_parts": latest_parts,
        "latest_health": latest_health,
        "latest_high_risk": latest_high_risk,
        "latest_medium_risk": latest_medium_risk,
        "latest_date": latest_date,
        "alternatives_found": alternatives_found,
        "trend_records": trend_records,
        "trend_health_change": trend_health_change,
        "trend_high_risk_change": trend_high_risk_change,
        "declining_projects": declining_projects,
        "recent_activity": grouped_activity,
        "recent_alerts_7d": recent_alerts_7d,
        "lifecycle_alert_count": lifecycle_alert_count,
        "stock_alert_count": stock_alert_count,
        "price_alert_count": price_alert_count,
        "healthy_pct": healthy_pct,
        "medium_pct": medium_pct,
        "critical_pct": critical_pct,
        "healthy_count": healthy_count,
        "trend_summary": trend_summary,
    }


def load_portfolio_dashboard_context(
    *,
    current_user: Mapping[str, Any],
    load_alternative_history: Callable[..., List[Dict[str, Any]]],
    get_user_profile: Callable[..., Dict[str, Any]],
    preloaded_analyses: Optional[List[Dict[str, Any]]] = None,
    preloaded_alerts: Optional[List[Dict[str, Any]]] = None,
    fallback_analyses: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Lazy portfolio context — reuses overview queries where possible."""
    analysis_data = [row for row in (preloaded_analyses or []) if _is_real_saved_analysis(row)]
    if not analysis_data and fallback_analyses:
        analysis_data = [row for row in fallback_analyses if _is_real_saved_analysis(row)]

    alert_data = list(preloaded_alerts or [])

    try:
        alternative_history = load_alternative_history(current_user["id"]) or []
    except Exception:
        alternative_history = []

    return build_portfolio_dashboard_context(
        analysis_data=analysis_data,
        alert_data=alert_data,
        alternative_history=alternative_history,
        get_user_profile=get_user_profile,
        current_user=current_user,
    )


def render_portfolio_intelligence_workspace(
    *,
    ctx: Mapping[str, Any],
    overview: Mapping[str, Any],
    internal_nav_button: Callable[..., Any],
) -> None:
    st.markdown('<div class="cv672-dashboard-workspace">', unsafe_allow_html=True)
    if not ctx.get("analysis_data"):
        st.markdown(
            """
            <section class="cv672-dashboard-empty">
              <strong>No portfolio projects yet</strong>
              <p>Analyze or save a BOM to begin building portfolio intelligence.</p>
            </section>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.html(
        f"""
        <section class="cv57-command">
          <div class="cv57-kicker">Portfolio Intelligence</div>
          <h1>{html.escape(str(ctx.get('greeting_prefix')))}, {html.escape(str(ctx.get('user_name')))}.</h1>
          <p class="cv57-lead">Review portfolio health, project readiness, and recent engineering activity.</p>
        </section>
        """
    )

    portfolio_tone = ctx.get("health_kind") if ctx.get("health_kind") in {"success", "warning", "danger"} else "info"
    render_kpi_row_safe(
        [
            MetricCard(
                label="Portfolio health",
                value=str(ctx.get("avg_health_score")),
                detail=f"{ctx.get('health_badge')} · {ctx.get('health_delta_label')} vs previous",
                tone=portfolio_tone,
                icon="gauge",
            ),
            MetricCard(
                label="Saved projects",
                value=str(ctx.get("total_analyses")),
                detail="Saved engineering analyses",
                tone="info",
                icon="folder-archive",
            ),
            MetricCard(
                label="Critical components",
                value=str(ctx.get("total_high_risk")),
                detail="Require engineering review",
                tone="danger" if ctx.get("total_high_risk") else "success",
                icon="triangle-alert",
            ),
            MetricCard(
                label="Portfolio alerts",
                value=str(ctx.get("alert_count")),
                detail=f"{ctx.get('high_alert_count')} high severity",
                tone="warning" if ctx.get("alert_count") else "neutral",
                icon="calendar-clock",
            ),
        ],
        columns=4,
    )

    render_portfolio_project_summaries(
        projects=overview.get("projects", []),
        internal_nav_button=internal_nav_button,
    )

    project_col_left, project_col_right = st.columns([1.35, 0.78], gap="small")
    with project_col_left:
        latest_analysis_id = ""
        analysis_data = ctx.get("analysis_data") or []
        if analysis_data:
            latest_analysis_id = str(analysis_data[0].get("id") or "")
        project_href = (
            f"?page=Analysis%20Details&analysis_id={html.escape(latest_analysis_id, quote=True)}"
            if latest_analysis_id
            else "?page=BOM%20Analyzer"
        )
        st.markdown(
            """
            <div class="cv-v4-section-head cv-6b-column-heading">
              <div>
                <div class="cv-v4-section-title">Current Working BOM</div>
                <div class="cv-v4-section-meta">Continue the most recently saved engineering review.</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <div class="cv-6b-panel cv-6b-project-panel">
              <div class="cv-6b-project-head">
                <div>
                  <div class="cv-v4-label">Active Analysis</div>
                  <div class="cv-6b-project-title">{html.escape(str(ctx.get('latest_project')))}</div>
                </div>
                <div class="cv-v4-icon">{_lucide_icon('file',18)}</div>
              </div>
              <div class="cv241-project-grid">
                <div class="cv241-project-stat"><span>Health</span><strong>{ctx.get('latest_health')}</strong></div>
                <div class="cv241-project-stat"><span>Components</span><strong>{ctx.get('latest_parts')}</strong></div>
                <div class="cv241-project-stat"><span>High Risk</span><strong>{ctx.get('latest_high_risk')}</strong></div>
                <div class="cv241-project-stat"><span>Medium Risk</span><strong>{ctx.get('latest_medium_risk')}</strong></div>
              </div>
              <a class="cv-6b-project-link" href="{project_href}" target="_self">
                <span>Continue analysis</span><span>→</span>
              </a>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with project_col_right:
        st.markdown(
            """
            <div class="cv-v4-section-head cv-6b-column-heading">
              <div>
                <div class="cv-v4-section-title">Readiness distribution</div>
                <div class="cv-v4-section-meta">Healthy, medium-risk, and critical component exposure.</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <section class="cv26-card">
              <div class="cv26-riskdist">
                <i class="healthy" style="width:{ctx.get('healthy_pct')}%"></i>
                <i class="medium" style="width:{ctx.get('medium_pct')}%"></i>
                <i class="critical" style="width:{ctx.get('critical_pct')}%"></i>
              </div>
              <div class="cv26-legend">
                <span>Healthy {ctx.get('healthy_count')}</span>
                <span>Medium {ctx.get('total_medium_risk')}</span>
                <span>Critical {ctx.get('total_high_risk')}</span>
              </div>
            </section>
            """,
            unsafe_allow_html=True,
        )

    declining_projects = ctx.get("declining_projects") or []
    st.markdown(
        """
        <div class="cv-v4-section-head" style="margin-top:8px;">
          <div>
            <div class="cv-v4-section-title">Projects requiring attention</div>
            <div class="cv-v4-section-meta">Projects moving in the wrong direction.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if declining_projects:
        for project in declining_projects[:3]:
            project_name = html.escape(str(project.get("project") or "Saved BOM"))
            health_change = int(project.get("health_change", 0) or 0)
            risk_change = int(project.get("risk_change", 0) or 0)
            explanation_parts = []
            if health_change < 0:
                explanation_parts.append(f"health {health_change:+d}")
            if risk_change > 0:
                explanation_parts.append(f"high-risk {risk_change:+d}")
            explanation = " • ".join(explanation_parts) or "Recorded risk increased"
            st.markdown(
                f"""
                <div class="cv231-activity-card" style="padding:12px 14px;">
                  <div class="cv231-activity-type">Needs Attention</div>
                  <div class="cv231-activity-title">{project_name}</div>
                  <div class="cv231-activity-copy">{html.escape(explanation)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div class="cv242-status-note">No saved projects are currently trending downward.</div>',
            unsafe_allow_html=True,
        )

    recent_activity = ctx.get("recent_activity") or []
    st.markdown(
        """
        <div class="cv-v4-section-head cv-6b-column-heading">
          <div>
            <div class="cv-v4-section-title">Recent engineering activity</div>
            <div class="cv-v4-section-meta">Analyses, monitoring, and replacement events.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    visible_activity = recent_activity[:4]
    if visible_activity:
        for event in visible_activity:
            st.markdown(
                f"""
                <section class="cv231-activity-card" style="padding:12px 14px;margin-bottom:9px;">
                  <div class="cv231-activity-top">
                    <div class="cv231-activity-type">{html.escape(str(event['type']))}</div>
                    <div class="cv231-activity-time">{html.escape(_activity_relative(event.get('created_at')))}</div>
                  </div>
                  <div class="cv231-activity-title">
                    {html.escape(str(event['title']))}
                    {f'<span class="cv242-repeat-badge">{event.get("repeat_count", 1)} repeated</span>' if event.get("repeat_count", 1) > 1 else ''}
                  </div>
                  <div class="cv231-activity-copy">{html.escape(str(event['copy']))}</div>
                  <a class="cv231-activity-link" href="{event['href']}" target="_self">
                    {html.escape(str(event['action']))} →
                  </a>
                </section>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div class="cv231-empty"><strong>No engineering activity yet.</strong><br>Analyze a BOM to begin portfolio activity tracking.</div>',
            unsafe_allow_html=True,
        )

    render_team_workload_section(overview=overview)
    st.markdown("</div>", unsafe_allow_html=True)


def render_dashboard_analytics_workspace(
    *,
    ctx: Mapping[str, Any],
    light_plotly_layout: Callable[..., Any],
) -> None:
    st.markdown('<div class="cv672-dashboard-workspace">', unsafe_allow_html=True)
    analysis_data = ctx.get("analysis_data") or []
    trend_records = ctx.get("trend_records") or []

    if len(analysis_data) < 2:
        st.markdown(
            """
            <section class="cv672-dashboard-empty">
              <strong>Not enough historical data</strong>
              <p>Complete additional analyses to unlock engineering trends.</p>
            </section>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown(
        """
        <div class="cv-v4-section-head">
          <div>
            <div class="cv-v4-section-title">Engineering Analytics</div>
            <div class="cv-v4-section-meta">Trend and distribution views derived from saved analyses.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="cv232-trend-summary">{html.escape(str(ctx.get('trend_summary')))}</div>
        <section class="cv232-trend-grid">
          <div class="cv232-trend-card {'good' if ctx.get('trend_health_change', 0) > 0 else 'bad' if ctx.get('trend_health_change', 0) < 0 else ''}">
            <div class="cv232-trend-label">Health Change</div>
            <div class="cv232-trend-value">{ctx.get('trend_health_change', 0):+d}</div>
            <div class="cv232-trend-note">Latest saved analysis versus previous</div>
          </div>
          <div class="cv232-trend-card {'good' if ctx.get('trend_high_risk_change', 0) < 0 else 'bad' if ctx.get('trend_high_risk_change', 0) > 0 else ''}">
            <div class="cv232-trend-label">High-Risk Change</div>
            <div class="cv232-trend-value">{ctx.get('trend_high_risk_change', 0):+d}</div>
            <div class="cv232-trend-note">Fewer high-risk records is better</div>
          </div>
          <div class="cv232-trend-card {'warn' if ctx.get('recent_alerts_7d') else ''}">
            <div class="cv232-trend-label">Alert Trend (7d)</div>
            <div class="cv232-trend-value">{ctx.get('recent_alerts_7d', 0)}</div>
            <div class="cv232-trend-note">Recorded in the last seven days</div>
          </div>
          <div class="cv232-trend-card">
            <div class="cv232-trend-label">Lifecycle Signals</div>
            <div class="cv232-trend-value">{ctx.get('lifecycle_alert_count', 0)}</div>
            <div class="cv232-trend-note">Lifecycle-related monitoring events</div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    chart_left, chart_right = st.columns(2, gap="medium")
    with chart_left:
        st.markdown(
            f"""
            <div class="cv-v4-section-head cv-6b-column-heading">
              <div>
                <div class="cv-v4-section-title">Portfolio health trend</div>
                <div class="cv-v4-section-meta">Latest 7 recorded days · {ctx.get('health_delta_label')} vs previous</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        trend_df = pd.DataFrame(analysis_data)
        trend_df["created_at"] = pd.to_datetime(trend_df["created_at"], errors="coerce", utc=True)
        trend_df["health_score"] = pd.to_numeric(trend_df["health_score"], errors="coerce")
        trend_df = trend_df.dropna(subset=["created_at", "health_score"]).sort_values("created_at")
        trend_df["Date"] = trend_df["created_at"].dt.floor("D")
        daily_health = (
            trend_df.groupby("Date", as_index=False)
            .agg(Health_Score=("health_score", "mean"), Analyses=("health_score", "size"))
            .sort_values("Date")
            .tail(7)
            .reset_index(drop=True)
        )
        daily_health["Health_Score"] = daily_health["Health_Score"].round(1)
        health_values = daily_health["Health_Score"].dropna()
        health_min = max(0, float(health_values.min()) - 3) if not health_values.empty else 0
        health_max = min(100, float(health_values.max()) + 3) if not health_values.empty else 100
        if health_max - health_min < 10:
            midpoint = (health_max + health_min) / 2
            health_min = max(0, midpoint - 5)
            health_max = min(100, midpoint + 5)

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=daily_health["Date"],
                y=[health_min] * len(daily_health),
                mode="lines",
                line={"width": 0},
                hoverinfo="skip",
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=daily_health["Date"],
                y=daily_health["Health_Score"],
                customdata=daily_health[["Analyses"]],
                mode="lines+markers",
                name="Portfolio Health",
                line={"color": "#2563EB", "width": 2.5, "shape": "linear"},
                marker={"size": 5, "color": "#FFFFFF", "line": {"color": "#2563EB", "width": 2}},
                fill="tonexty",
                fillcolor="rgba(37, 99, 235, 0.09)",
            )
        )
        fig.update_yaxes(range=[health_min, health_max], gridcolor="rgba(148,163,184,0.16)", zeroline=False)
        fig.update_xaxes(gridcolor="rgba(148,163,184,0.10)", showline=False)
        fig.update_layout(
            hovermode="x unified",
            margin={"l": 3, "r": 5, "t": 10, "b": 2},
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(
            light_plotly_layout(fig, height=165),
            use_container_width=True,
            config={"displayModeBar": False, "scrollZoom": False, "responsive": True},
        )

    with chart_right:
        st.markdown(
            """
            <div class="cv-v4-section-head cv-6b-column-heading">
              <div>
                <div class="cv-v4-section-title">Risk movement</div>
                <div class="cv-v4-section-meta">High- and medium-risk movement over recorded days.</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if len(trend_records) >= 2:
            risk_df = pd.DataFrame(trend_records)
            risk_df["created_at"] = pd.to_datetime(risk_df["created_at"], errors="coerce", utc=True)
            risk_df["high_risk"] = pd.to_numeric(risk_df["high_risk"], errors="coerce").fillna(0)
            risk_df["medium_risk"] = pd.to_numeric(risk_df["medium_risk"], errors="coerce").fillna(0)
            risk_df = risk_df.dropna(subset=["created_at"]).sort_values("created_at")
            risk_df["Date"] = risk_df["created_at"].dt.floor("D")
            daily_risk = (
                risk_df.groupby("Date", as_index=False)
                .agg(High_Risk=("high_risk", "mean"), Medium_Risk=("medium_risk", "mean"), Analyses=("high_risk", "size"))
                .sort_values("Date")
                .tail(7)
                .reset_index(drop=True)
            )
            daily_risk["High_Risk"] = daily_risk["High_Risk"].round(1)
            daily_risk["Medium_Risk"] = daily_risk["Medium_Risk"].round(1)
            risk_max = max(
                1.0,
                float(max(daily_risk["High_Risk"].max(), daily_risk["Medium_Risk"].max())),
            )
            risk_fig = go.Figure()
            risk_fig.add_trace(
                go.Scatter(
                    x=daily_risk["Date"],
                    y=daily_risk["Medium_Risk"],
                    mode="lines+markers",
                    name="Medium Risk",
                    line={"color": "#F59E0B", "width": 2.2, "shape": "linear"},
                )
            )
            risk_fig.add_trace(
                go.Scatter(
                    x=daily_risk["Date"],
                    y=daily_risk["High_Risk"],
                    mode="lines+markers",
                    name="High Risk",
                    line={"color": "#DC2626", "width": 2.2, "shape": "linear"},
                )
            )
            risk_fig.update_yaxes(range=[0, risk_max + max(1, risk_max * 0.25)], gridcolor="rgba(148,163,184,0.16)", zeroline=False)
            risk_fig.update_xaxes(gridcolor="rgba(148,163,184,0.10)", showline=False)
            risk_fig.update_layout(
                hovermode="x unified",
                legend={"orientation": "h", "y": 1.03, "x": 1, "xanchor": "right"},
                margin={"l": 3, "r": 5, "t": 25, "b": 2},
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(
                light_plotly_layout(risk_fig, height=165),
                use_container_width=True,
                config={"displayModeBar": False, "scrollZoom": False, "responsive": True},
            )
        else:
            st.info("Save at least two BOM analyses to display risk movement.")

    st.markdown(
        f"""
        <section class="cv672-dashboard-analytics-summary">
          <strong>Analytical summary</strong>
          <p>{html.escape(str(ctx.get('trend_summary')))}</p>
          <ul>
            <li>Stock-related monitoring events: {ctx.get('stock_alert_count', 0)}</li>
            <li>Price-related monitoring events: {ctx.get('price_alert_count', 0)}</li>
            <li>Average BOM health: {ctx.get('avg_health_score', 0)}/100</li>
          </ul>
        </section>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

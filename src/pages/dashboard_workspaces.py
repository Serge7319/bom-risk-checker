"""Sprint 67.2 — Dashboard workspace renderers and lazy context preparation."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.living_workspace import (
    render_portfolio_project_summaries,
    render_subsection_header,
    render_team_workload_section,
)
from src.ui.cadivor_design_system import MetricCard, cadivor_engineering_dataframe, render_kpi_row_safe
from src.ui.navigation import ALTERNATIVE_FINDER_PAGE, internal_nav_button, navigate_to

DASHBOARD_WORKSPACES: tuple[str, ...] = (
    "Engineering Overview",
    "Portfolio Intelligence",
    "Analytics",
    "Monitoring",
)

WORKSPACE_HEADERS: Dict[str, tuple[str, str]] = {
    "Engineering Overview": ("Engineering Overview", "What should engineering do today?"),
    "Portfolio Intelligence": (
        "Portfolio Intelligence",
        "Review portfolio health, readiness, and recent engineering activity.",
    ),
    "Analytics": ("Analytics", "How is engineering risk changing over time?"),
    "Monitoring": ("Monitoring", "Recent lifecycle, inventory, pricing, and supplier change summaries."),
}


def render_dashboard_page_heading() -> None:
    st.markdown(
        """
        <div class="cv-page cv-dashboard-page">
          <header class="cv-page-header cv672-dashboard-heading">
            <div>
              <h1 class="cv-page-title cv672-dashboard-title">Dashboard</h1>
              <p class="cv-page-subtitle cv672-dashboard-subtitle">
                Monitor portfolio health, prioritize engineering work, and continue active analyses.
              </p>
            </div>
          </header>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard_workspace_navigation(*, radio_key: str) -> str:
    """Clean, URL-backed workspace navigation without Streamlit radio chrome."""
    raw_workspace = str(st.query_params.get("dashboard_workspace", "")).strip()
    workspace = raw_workspace if raw_workspace in DASHBOARD_WORKSPACES else st.session_state.get(
        radio_key, DASHBOARD_WORKSPACES[0]
    )
    if workspace not in DASHBOARD_WORKSPACES:
        workspace = DASHBOARD_WORKSPACES[0]
    st.session_state[radio_key] = workspace
    nav_items = []
    for item in DASHBOARD_WORKSPACES:
        active = " cv672-dashboard-nav__link--active" if item == workspace else ""
        current = ' aria-current="page"' if item == workspace else ""
        nav_items.append(
            f'<a class="cv672-dashboard-nav__link{active}" href="?page=Dashboard&amp;dashboard_workspace='
            f'{html.escape(item, quote=True)}" target="_self"{current}>{html.escape(item)}</a>'
        )
    st.markdown(
        '<nav class="cv672-dashboard-nav" aria-label="Workspace navigation">'
        + "".join(nav_items)
        + "</nav>",
        unsafe_allow_html=True,
    )
    return workspace


def render_workspace_section_header(title: str, description: str) -> None:
    st.markdown(
        f"""
        <header class="cv-section-header cv672-dashboard-workspace-header cv6723-workspace-header">
          <h2 class="cv-section-title">{html.escape(title)}</h2>
          <p class="cv-section-subtitle">{html.escape(description)}</p>
        </header>
        """,
        unsafe_allow_html=True,
    )


def _alert_trend_frame(alert_data: List[Dict[str, Any]], *, keyword: str) -> pd.DataFrame:
    rows = []
    for item in alert_data:
        blob = " ".join(
            str(item.get(key) or "")
            for key in ("alert_type", "alert_message", "change_type", "message")
        ).lower()
        if keyword != "alert" and keyword not in blob:
            continue
        created_at = pd.to_datetime(
            item.get("created_at") or item.get("detected_at"),
            errors="coerce",
            utc=True,
        )
        if pd.isna(created_at):
            continue
        rows.append({"created_at": created_at})
    if not rows:
        return pd.DataFrame(columns=["Date", "Events"])
    frame = pd.DataFrame(rows)
    frame["Date"] = frame["created_at"].dt.floor("D")
    daily = frame.groupby("Date", as_index=False).size().rename(columns={"size": "Events"})
    return daily.sort_values("Date").tail(7).reset_index(drop=True)


def _render_trend_chart_panel(
    *,
    title: str,
    description: str,
    frame: pd.DataFrame,
    light_plotly_layout: Callable[..., Any],
    line_color: str,
    fill_rgba: str,
    empty_copy: str,
) -> None:
    st.markdown(
        f"""
        <div class="cv6723-chart-panel-head">
          <strong>{html.escape(title)}</strong>
          <span>{html.escape(description)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if frame.empty:
        st.markdown(
            f'<div class="cv6723-chart-empty">{html.escape(empty_copy)}</div>',
            unsafe_allow_html=True,
        )
        return
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=frame["Date"],
            y=frame["Events"],
            mode="lines+markers",
            line={"color": line_color, "width": 2.2},
            marker={"size": 4, "color": "#FFFFFF", "line": {"color": line_color, "width": 1.5}},
            fill="tozeroy",
            fillcolor=fill_rgba,
        )
    )
    fig.update_layout(
        margin={"l": 2, "r": 4, "t": 8, "b": 2},
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(showgrid=False, showline=False)
    fig.update_yaxes(gridcolor="rgba(148,163,184,0.12)", zeroline=False, rangemode="tozero")
    st.plotly_chart(
        light_plotly_layout(fig, height=140),
        use_container_width=True,
        config={"displayModeBar": False, "scrollZoom": False, "responsive": True},
    )


def inject_dashboard_workspace_styles() -> None:
    """Inject Dashboard styles for every rendered Dashboard view."""
    from src.pages.dashboard import inject_dashboard_page_styles

    inject_dashboard_page_styles()
    _inject_dashboard_v2_styles()


def _inject_dashboard_v2_styles() -> None:
    """Render the style block every time; browser history rebuilds page DOM."""
    css_path = Path(__file__).resolve().parents[1] / "assets" / "css" / "dashboard_v2.css"
    try:
        css = css_path.read_text(encoding="utf-8")
    except OSError:
        return
    if css.strip():
        st.markdown(
            f"<style id='cadivor-dashboard-v2-css'>{css}</style>",
            unsafe_allow_html=True,
        )


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


def _activity_card_html(event: Mapping[str, Any], *, include_link: bool = True) -> str:
    link_html = ""
    if include_link and not event.get("nav_page"):
        link_html = (
            f'<a class="cv6723-inline-link" href="{html.escape(str(event.get("href") or "?page=Dashboard"), quote=True)}" target="_self">'
            f"{html.escape(str(event.get('action') or 'Review'))} →"
            f"</a>"
        )
    return (
        f'<section class="cv6723-activity-card cv-card cv-card-interactive cv-dashboard-activity-card">'
        f'<div class="cv6723-activity-top">'
        f"<span>{html.escape(str(event.get('type') or ''))}</span>"
        f"<span>{html.escape(_activity_relative(event.get('created_at')))}</span>"
        f"</div>"
        f"<strong>{html.escape(str(event.get('title') or ''))}</strong>"
        f"<p>{html.escape(str(event.get('copy') or ''))}</p>"
        f"{link_html}"
        f"</section>"
    )


def _render_activity_cards(events: Iterable[Mapping[str, Any]]) -> None:
    for index, event in enumerate(events):
        nav_page = str(event.get("nav_page") or "").strip()
        st.html(_activity_card_html(event, include_link=not bool(nav_page)))
        if nav_page:
            internal_nav_button(
                f"{event.get('action') or 'Review'} →",
                nav_page,
                key=f"dashboard_ws_activity_{index}_{nav_page.replace(' ', '_')}",
                **dict(event.get("nav_params") or {}),
            )


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
                "nav_page": ALTERNATIVE_FINDER_PAGE,
                "nav_params": {
                    "original_part": str(original),
                    "source_page": "dashboard_workspace_activity",
                },
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
) -> None:
    st.markdown('<div class="cv-page cv672-dashboard-workspace cv-dashboard-workspace">', unsafe_allow_html=True)
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

    render_workspace_section_header(
        "Portfolio Intelligence",
        "Review portfolio health, readiness, and recent engineering activity.",
    )

    portfolio_tone = ctx.get("health_kind") if ctx.get("health_kind") in {"success", "warning", "danger"} else "info"
    render_kpi_row_safe(
        [
            MetricCard(
                label="Portfolio Health",
                value=str(ctx.get("avg_health_score")),
                detail=f"{ctx.get('health_badge')} · {ctx.get('health_delta_label')} vs previous",
                tone=portfolio_tone,
                icon="gauge",
            ),
            MetricCard(
                label="Saved Projects",
                value=str(ctx.get("total_analyses")),
                detail="Saved engineering analyses",
                tone="info",
                icon="folder-archive",
                href="?page=BOM%20Analyzer",
                action_label="Open saved projects",
            ),
            MetricCard(
                label="Critical Components",
                value=str(ctx.get("total_high_risk")),
                detail="Require engineering review",
                tone="danger" if ctx.get("total_high_risk") else "success",
                icon="triangle-alert",
                href="?page=Portfolio%20Intelligence",
                action_label="Review critical components",
            ),
            MetricCard(
                label="Portfolio Alerts",
                value=str(ctx.get("alert_count")),
                detail=f"{ctx.get('high_alert_count')} high severity",
                tone="warning" if ctx.get("alert_count") else "neutral",
                icon="calendar-clock",
                href="?page=Monitoring",
                action_label="Open portfolio alerts",
            ),
        ],
        columns=4,
    )

    declining_projects = ctx.get("declining_projects") or []

    render_subsection_header(
        "Projects requiring attention",
        description="Projects moving in the wrong direction.",
        icon="triangle-alert",
    )
    if declining_projects:
        attention_rows = []
        for project in declining_projects[:4]:
            project_name = html.escape(str(project.get("project") or "Saved BOM"))
            health_change = int(project.get("health_change", 0) or 0)
            risk_change = int(project.get("risk_change", 0) or 0)
            explanation_parts = []
            if health_change < 0:
                explanation_parts.append(f"health {health_change:+d}")
            if risk_change > 0:
                explanation_parts.append(f"high-risk {risk_change:+d}")
            explanation = " • ".join(explanation_parts) or "Recorded risk increased"
            attention_rows.append(
                f"<tr><td>{project_name}</td>"
                f"<td>{health_change:+d}</td>"
                f"<td>{risk_change:+d}</td>"
                f"<td>{html.escape(explanation)}</td></tr>"
            )
        st.markdown(
            """
            <div class="cv6723-section">
              <div class="cv6723-compact-table-wrap">
                <table class="cv6723-compact-table">
                  <thead>
                    <tr><th>Project</th><th>Health Δ</th><th>Risk Δ</th><th>Signal</th></tr>
                  </thead>
                  <tbody>
            """
            + "".join(attention_rows)
            + """
                  </tbody>
                </table>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div class="cv6723-section">
              <section class="cv672-attention-stable">
                <div class="cv672-attention-stable-icon" aria-hidden="true">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                    <path d="m9 11 3 3L22 4"/>
                  </svg>
                </div>
                <div>
                  <strong>No projects currently trending downward</strong>
                  <p>Portfolio health is stable across saved projects.</p>
                </div>
              </section>
            </div>
            """,
            unsafe_allow_html=True,
        )

    render_portfolio_project_summaries(
        projects=overview.get("projects", []),
    )

    latest_analysis_id = ""
    analysis_data = ctx.get("analysis_data") or []
    if analysis_data:
        latest_analysis_id = str(analysis_data[0].get("id") or "")
    project_href = (
        f"?page=Analysis%20Details&analysis_id={html.escape(latest_analysis_id, quote=True)}"
        if latest_analysis_id
        else "?page=BOM%20Analyzer"
    )
    render_subsection_header(
        "Current working BOM",
        description="Continue the most recently saved engineering review.",
        icon="file",
    )
    st.markdown(
        f"""
        <section class="cv6723-section cv6723-bom-strip cv-card cv-card-interactive cv-dashboard-bom-card">
          <div class="cv6723-bom-main">
            <span class="cv6723-bom-label">Active analysis</span>
            <strong>{html.escape(str(ctx.get('latest_project')))}</strong>
            <span>Updated {html.escape(str(ctx.get('latest_date')))}</span>
          </div>
          <div class="cv6723-bom-stats">
            <div><span>Health</span><strong>{ctx.get('latest_health')}</strong></div>
            <div><span>Components</span><strong>{ctx.get('latest_parts')}</strong></div>
            <div><span>High risk</span><strong>{ctx.get('latest_high_risk')}</strong></div>
            <div><span>Medium risk</span><strong>{ctx.get('latest_medium_risk')}</strong></div>
          </div>
          <div class="cv6723-bom-side">
            <div class="cv6723-readiness-inline">
              <span>Healthy {ctx.get('healthy_count')}</span>
              <span>Medium {ctx.get('total_medium_risk')}</span>
              <span>Critical {ctx.get('total_high_risk')}</span>
            </div>
            <a class="cv6723-inline-link" href="{project_href}" target="_self">Continue analysis →</a>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    recent_activity = ctx.get("recent_activity") or []
    activity_col, workload_col = st.columns([1.2, 0.8], gap="small")
    with activity_col:
        render_subsection_header(
            "Recent engineering activity",
            description="Analyses, monitoring, and replacement events.",
            icon="history",
        )
        visible_activity = recent_activity[:3]
        if visible_activity:
            st.markdown('<div class="cv6723-section cv6723-activity-list">', unsafe_allow_html=True)
            _render_activity_cards(visible_activity)
            st.markdown("</div>", unsafe_allow_html=True)
            if len(recent_activity) > 3:
                with st.expander(f"View all activity ({len(recent_activity)})", expanded=False):
                    _render_activity_cards(recent_activity[3:8])
        else:
            st.markdown(
                """
                <section class="cv6723-compact-panel cv6723-empty-note">
                  <strong>No engineering activity yet</strong>
                  <p>Analyze a BOM to begin portfolio activity tracking.</p>
                </section>
                """,
                unsafe_allow_html=True,
            )

    with workload_col:
        render_team_workload_section(overview=overview)
    st.markdown("</div>", unsafe_allow_html=True)


def render_dashboard_analytics_workspace(
    *,
    ctx: Mapping[str, Any],
    light_plotly_layout: Callable[..., Any],
) -> None:
    st.markdown('<div class="cv-page cv672-dashboard-workspace cv-dashboard-workspace">', unsafe_allow_html=True)
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

    render_workspace_section_header(
        "Analytics",
        "How is engineering risk changing over time?",
    )

    alert_data = list(ctx.get("alert_data") or [])
    lifecycle_trend = _alert_trend_frame(alert_data, keyword="lifecycle")
    alert_trend = _alert_trend_frame(alert_data, keyword="alert")

    st.markdown('<div class="cv6723-chart-grid">', unsafe_allow_html=True)
    chart_row_1 = st.columns(2, gap="small")
    with chart_row_1[0]:
        st.markdown(
            f"""
            <div class="cv6723-chart-panel-head">
              <strong>Portfolio health trend</strong>
              <span>Latest 7 recorded days · {html.escape(str(ctx.get('health_delta_label')))} vs previous</span>
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
            light_plotly_layout(fig, height=140),
            use_container_width=True,
            config={"displayModeBar": False, "scrollZoom": False, "responsive": True},
        )

    with chart_row_1[1]:
        st.markdown(
            """
            <div class="cv6723-chart-panel-head">
              <strong>Risk movement</strong>
              <span>High- and medium-risk movement over recorded days.</span>
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
                light_plotly_layout(risk_fig, height=140),
                use_container_width=True,
                config={"displayModeBar": False, "scrollZoom": False, "responsive": True},
            )
        else:
            st.markdown(
                '<div class="cv6723-chart-empty">Save at least two BOM analyses to display risk movement.</div>',
                unsafe_allow_html=True,
            )

    chart_row_2 = st.columns(2, gap="small")
    with chart_row_2[0]:
        _render_trend_chart_panel(
            title="Lifecycle trend",
            description="Lifecycle-related monitoring events over recorded days.",
            frame=lifecycle_trend,
            light_plotly_layout=light_plotly_layout,
            line_color="#D97706",
            fill_rgba="rgba(217, 119, 6, 0.08)",
            empty_copy="No lifecycle monitoring events recorded yet.",
        )
    with chart_row_2[1]:
        _render_trend_chart_panel(
            title="Alert trend",
            description="Recorded monitoring events over the last seven days.",
            frame=alert_trend,
            light_plotly_layout=light_plotly_layout,
            line_color="#2563EB",
            fill_rgba="rgba(37, 99, 235, 0.08)",
            empty_copy="No monitoring alerts recorded yet.",
        )
    st.markdown("</div>", unsafe_allow_html=True)

    health_change = int(ctx.get("trend_health_change", 0) or 0)
    high_risk_change = int(ctx.get("trend_high_risk_change", 0) or 0)
    health_card_tone = "good" if health_change > 0 else "bad" if health_change < 0 else ""
    risk_card_tone = "good" if high_risk_change < 0 else "bad" if high_risk_change > 0 else ""
    alert_card_tone = "warn" if ctx.get("recent_alerts_7d") else ""

    st.markdown(
        f"""
        <section class="cv672-analytics-metric-grid">
          <div class="cv672-analytics-metric-card {health_card_tone}">
            <div class="cv672-analytics-metric-label">Portfolio Health Change</div>
            <div class="cv672-analytics-metric-value">{health_change:+d}</div>
            <div class="cv672-analytics-metric-note">latest saved analysis versus previous</div>
          </div>
          <div class="cv672-analytics-metric-card {risk_card_tone}">
            <div class="cv672-analytics-metric-label">High-Risk Change</div>
            <div class="cv672-analytics-metric-value">{high_risk_change}</div>
            <div class="cv672-analytics-metric-note">fewer high-risk records is better</div>
          </div>
          <div class="cv672-analytics-metric-card {alert_card_tone}">
            <div class="cv672-analytics-metric-label">Alerts — Last 7 Days</div>
            <div class="cv672-analytics-metric-value">{ctx.get('recent_alerts_7d', 0)}</div>
            <div class="cv672-analytics-metric-note">recorded monitoring events</div>
          </div>
          <div class="cv672-analytics-metric-card">
            <div class="cv672-analytics-metric-label">Lifecycle Events</div>
            <div class="cv672-analytics-metric-value">{ctx.get('lifecycle_alert_count', 0)}</div>
            <div class="cv672-analytics-metric-note">lifecycle-related monitoring events</div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

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

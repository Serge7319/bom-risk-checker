"""Cadivor Milestone 18.0 — Living Engineering Workspace.

This module owns the customer-facing Engineering Overview so the main
Streamlit entry point can remain focused on routing and data access.
"""
from __future__ import annotations

from datetime import datetime, timezone
import html
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import quote

import pandas as pd
import streamlit as st

from src.ui.cadivor_design_system import (
    MetricCard,
    cadivor_table,
    render_kpi_row_safe,
    render_section_header,
    render_subsection_header,
)


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _relative_time(value: Any) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        return "Recently"
    now = datetime.now(timezone.utc)
    seconds = max(0, int((now - parsed.astimezone(timezone.utc)).total_seconds()))
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} hr ago"
    days = seconds // 86400
    return "Yesterday" if days == 1 else f"{days} days ago"


def _action_button_label(action: Dict[str, Any]) -> str:
    action_text = _text(action.get("title")).lower()
    if action.get("page") == "Engineering Decisions":
        if "approve" in action_text:
            return "Review Approval"
        if "replacement" in action_text or "successor" in action_text:
            return "Review Replacement"
        return "Review Decision"
    if "stock" in action_text or "source" in action_text:
        return "Find Source"
    return "Review Purchase"


def _work_queue_action_href(action: Dict[str, Any]) -> str:
    destination = _text(action.get("page"), "Engineering Decisions")
    params = [f"page={quote(destination)}"]
    if destination == "Engineering Decisions" and action.get("decision_id"):
        params.append(f"decision_id={quote(str(action['decision_id']))}")
    return "?" + "&".join(params)


def _full_work_queue_table_html(actions: Iterable[Dict[str, Any]]) -> str:
    rows = list(actions or [])
    if not rows:
        return (
            '<section class="cv6723-compact-panel cv6723-empty-note">'
            "<strong>No urgent work recorded</strong>"
            "<p>The prioritized queue is clear.</p></section>"
        )
    table_html = [
        '<div class="cv6723-compact-table-wrap">',
        '<table class="cv6723-compact-table">',
        "<thead><tr>",
        "<th>Component or Project</th>",
        "<th>Recommended Work</th>",
        "<th>Owner</th>",
        "<th>Due</th>",
        "<th>Priority</th>",
        "<th>Action</th>",
        "</tr></thead><tbody>",
    ]
    for action in rows:
        priority = int(_number(action.get("priority"), 0))
        label = _action_button_label(action)
        href = _work_queue_action_href(action)
        table_html.append(
            "<tr>"
            f"<td>{html.escape(_text(action.get('item'), 'BOM'))}</td>"
            f"<td>{html.escape(_text(action.get('title'), 'Review engineering action'))}</td>"
            f"<td>{html.escape(_text(action.get('owner'), 'Engineering'))}</td>"
            f"<td>{html.escape(_text(action.get('due'), '—'))}</td>"
            f'<td><span class="cv6723-status-chip cv6723-status-chip--info">P{priority}</span></td>'
            f'<td><a class="cv6723-inline-link" href="{href}" target="_self">{html.escape(label)} →</a></td>'
            "</tr>"
        )
    table_html.append("</tbody></table></div>")
    return "".join(table_html)


def timeline_event(alert: Dict[str, Any]) -> Dict[str, str]:
    part = _text(alert.get("part_number") or alert.get("mpn"), "Component")
    alert_type = _text(alert.get("alert_type"), "Component update")
    message = _text(alert.get("alert_message"), "Component intelligence changed.")
    lower = f"{alert_type} {message}".lower()

    category = "Component"
    old_value = _text(alert.get("previous_value"))
    new_value = _text(alert.get("current_value"))
    if "lifecycle" in lower:
        category = "Lifecycle"
    elif "stock" in lower:
        category = "Stock"
    elif "price" in lower:
        category = "Price"
    elif "supplier" in lower:
        category = "Supplier"

    if old_value or new_value:
        change = f"{old_value or 'Not recorded'} → {new_value or 'Not recorded'}"
    else:
        change = message

    return {
        "part": part,
        "category": category,
        "change": change,
        "time": _relative_time(alert.get("created_at") or alert.get("detected_at")),
        "severity": _text(alert.get("severity"), "Review"),
    }


def _timeline_event(alert: Dict[str, Any]) -> Dict[str, str]:
    return timeline_event(alert)


def _monitoring_events_html(
    events: List[Dict[str, str]],
    *,
    empty_copy: str,
    limit: int = 5,
    compact: bool = False,
) -> str:
    if not events:
        panel_class = "cv6723-monitor-empty" if compact else "cv672-dashboard-empty"
        return (
            f'<section class="{panel_class}"><strong>No changes recorded</strong>'
            f"<p>{html.escape(empty_copy)}</p></section>"
        )
    timeline_class = "cv6723-timeline" if compact else "cv64-timeline"
    rows = [f'<div class="{timeline_class}">']
    for event in events[:limit]:
        rows.append(
            '<div class="cv6723-timeline-item">'
            f'<div class="cv6723-timeline-time">{html.escape(event["time"])}</div>'
            f'<div class="cv6723-timeline-title">{html.escape(event["part"])}</div>'
            f'<div class="cv6723-timeline-copy">{html.escape(event["change"])}</div>'
            "</div>"
        )
    rows.append("</div>")
    return "".join(rows)


def _compact_release_posture_html(metrics: Dict[str, Any]) -> str:
    tone = metrics.get("health_tone", "info")
    return (
        f'<section class="cv6723-compact-panel cv-card cv6723-release-posture cv6723-release-posture--{html.escape(tone)}">'
        f'<div class="cv6723-compact-panel-head">'
        f'<strong>Release posture</strong>'
        f'<span class="cv6723-status-chip cv6723-status-chip--{html.escape(tone)}">'
        f'{html.escape(metrics.get("health_status", "Review"))}</span></div>'
        f'<p>{html.escape(metrics.get("release_label", "Controlled review recommended"))}</p>'
        f"</section>"
    )


def _compact_recommendations_html(recommendations: Iterable[Any]) -> str:
    items = list(recommendations or [])[:4]
    if not items:
        return (
            '<section class="cv6723-compact-panel cv6723-empty-note">'
            "<strong>No urgent recommendations</strong>"
            "<p>Continue routine monitoring.</p></section>"
        )
    cards = []
    for index, recommendation in enumerate(items):
        badge = "Priority" if index == 0 else "Review"
        badge_class = "info" if index == 0 else "neutral"
        text = _text(recommendation)
        action_line = text.split(".")[0] if "." in text else text
        if len(action_line) > 92:
            action_line = f"{action_line[:89].rstrip()}..."
        cards.append(
            f'<article class="cv6723-rec-card cv-card">'
            f'<div class="cv6723-rec-top">'
            f'<strong>Recommendation {index + 1}</strong>'
            f'<span class="cv6723-status-chip cv6723-status-chip--{badge_class}">{badge}</span>'
            f"</div>"
            f'<p class="cv6723-rec-copy">{html.escape(action_line)}</p>'
            f"</article>"
        )
    return f'<section class="cv6723-rec-grid">{"".join(cards)}</section>'


def _compact_work_queue_html(actions: Iterable[Dict[str, Any]], *, limit: int = 3) -> str:
    rows = list(actions or [])[:limit]
    if not rows:
        return (
            '<section class="cv6723-compact-panel cv6723-empty-note">'
            "<strong>No urgent work recorded</strong>"
            "<p>The prioritized queue is clear.</p></section>"
        )
    body = ['<div class="cv6723-queue-list">']
    for action in rows:
        priority = int(_number(action.get("priority"), 0))
        label = _action_button_label(action)
        href = _work_queue_action_href(action)
        body.append(
            '<article class="cv6723-queue-row">'
            f'<div class="cv6723-queue-main">'
            f'<strong>{html.escape(_text(action.get("item"), "BOM"))}</strong>'
            f'<span>{html.escape(_text(action.get("title"), "Review engineering action"))}</span>'
            f"</div>"
            f'<div class="cv6723-queue-meta">'
            f'<span class="cv6723-status-chip cv6723-status-chip--info">P{priority}</span>'
            f'<span>{html.escape(_text(action.get("owner"), "Engineering"))}</span>'
            f'<a class="cv6723-inline-link" href="{href}" target="_self">{html.escape(label)} →</a>'
            f"</div></article>"
        )
    body.append("</div>")
    return "".join(body)


def _monitoring_category_panel_html(
    *,
    title: str,
    count: int,
    body_html: str,
) -> str:
    return (
        f'<section class="cv6723-monitor-panel">'
        f'<header class="cv6723-monitor-panel-head">'
        f"<div><strong>{html.escape(title)}</strong>"
        f"<span>{count} recorded</span></div>"
        f'<div class="cv6723-monitor-count">{count}</div>'
        f"</header>"
        f'<div class="cv6723-monitor-panel-body">{body_html}</div>'
        f"</section>"
    )


def supplier_watch_rows(parts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    watch: List[Dict[str, Any]] = []
    seen = set()
    for row in parts or []:
        mpn = _text(row.get("mpn") or row.get("part_number"))
        manufacturer = _text(row.get("manufacturer"), "Unknown manufacturer")
        if not mpn or mpn.upper() in seen:
            continue

        stock = int(_number(row.get("stock_available") or row.get("stock"), 0))
        suppliers = int(_number(row.get("supplier_count"), 0))
        lead_time = _number(row.get("lead_time_weeks") or row.get("lead_time"), 0)
        lifecycle = _text(row.get("lifecycle_status"), "Unknown")
        signal = None
        detail = None
        priority = 0

        if stock <= 0:
            signal, detail, priority = "No stock recorded", "Find authorized inventory or an alternate.", 100
        elif suppliers <= 1:
            signal, detail, priority = "Single-source exposure", "Qualify another authorized source.", 80
        elif lead_time >= 16:
            signal, detail, priority = "Long lead time", f"{lead_time:g} weeks recorded.", 70
        elif any(term in lifecycle.lower() for term in ("obsolete", "replacement", "nrnd", "not recommended")):
            signal, detail, priority = "Lifecycle attention", lifecycle, 75

        if signal:
            seen.add(mpn.upper())
            watch.append(
                {
                    "part": mpn,
                    "manufacturer": manufacturer,
                    "signal": signal,
                    "detail": detail,
                    "priority": priority,
                }
            )

    watch.sort(key=lambda item: -item["priority"])
    return watch[:5]


def _supplier_watch(parts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return supplier_watch_rows(parts)


def workload_rows(actions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    totals: Dict[str, Dict[str, Any]] = {}
    for action in actions or []:
        owner = _text(action.get("owner"), "Engineering")
        bucket = totals.setdefault(owner, {"team": owner, "actions": 0, "hours": 0})
        bucket["actions"] += 1
        priority = int(_number(action.get("priority"), 0))
        bucket["hours"] += 4 if priority >= 85 else 2 if priority >= 60 else 1
    return sorted(totals.values(), key=lambda row: (-row["actions"], row["team"]))[:4]


def _workload(actions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return workload_rows(actions)


def compute_dashboard_summary_metrics(overview: Dict[str, Any]) -> Dict[str, Any]:
    projects = overview.get("projects", [])
    blocked_projects = sum(
        1 for project in projects
        if int(_number(project.get("health"), 0)) < 70 or int(_number(project.get("high"), 0)) >= 3
    )
    portfolio_health = (
        round(sum(int(_number(project.get("health"), 0)) for project in projects) / len(projects))
        if projects else 0
    )
    top_action = overview.get("top_actions", [{}])[0] if overview.get("top_actions") else {}
    health_tone = "success" if portfolio_health >= 85 else "warning" if portfolio_health >= 70 else "danger"
    health_status = "Excellent" if portfolio_health >= 90 else "Stable" if portfolio_health >= 75 else "Needs attention"
    release_label = (
        "Ready for controlled release"
        if portfolio_health >= 85 and blocked_projects == 0
        else "Release review required"
        if blocked_projects
        else "Controlled review recommended"
    )
    return {
        "projects": projects,
        "blocked_projects": blocked_projects,
        "portfolio_health": portfolio_health,
        "top_action": top_action,
        "brief_action": _text(top_action.get("title"), "Continue routine monitoring."),
        "brief_item": _text(top_action.get("item"), "your component portfolio"),
        "health_tone": health_tone,
        "health_status": health_status,
        "release_label": release_label,
    }


def render_engineering_overview_brief_and_kpis(*, overview: Dict[str, Any], metrics: Dict[str, Any]) -> None:
    """Engineering Overview — daily brief and primary KPI row."""
    render_section_header(
        "Your Engineering Brief",
        eyebrow="Engineering Overview",
        description=(
            f"{_text(overview.get('summary'))} "
            f"The most important next step is to {metrics['brief_action'].lower()} "
            f"for {metrics['brief_item']}."
        ),
        icon="briefcase-business",
    )
    render_kpi_row_safe(
        [
            MetricCard(
                label="Portfolio Health",
                value=f"{metrics['portfolio_health']}%",
                status=metrics["health_status"],
                tone=metrics["health_tone"],
                icon="gauge",
            ),
            MetricCard(
                label="Ready for Production",
                value=str(overview.get("ready_projects", 0)),
                detail="Projects cleared for release",
                tone="success",
                icon="badge-check",
            ),
            MetricCard(
                label="Action Today",
                value=str(len(overview.get("action_today", []))),
                detail="Prioritized engineering tasks",
                tone="info",
                icon="clipboard-list",
            ),
            MetricCard(
                label="Blocked Projects",
                value=str(metrics["blocked_projects"]),
                detail="Require immediate review" if metrics["blocked_projects"] else "No blockers recorded",
                tone="danger" if metrics["blocked_projects"] else "success",
                icon="octagon-alert",
            ),
        ],
        columns=4,
    )
    ready_col, action_col, blocked_col = st.columns(3)
    with ready_col:
        if st.button("View ready projects", key="dashboard_view_ready_projects", use_container_width=True):
            st.session_state["cadivor_dashboard_drilldown"] = "ready"
    with action_col:
        if st.button("View today's actions", key="dashboard_view_action_today", use_container_width=True):
            st.session_state["cadivor_dashboard_drilldown"] = "actions"
    with blocked_col:
        if st.button("View blocked projects", key="dashboard_view_blocked_projects", use_container_width=True):
            st.session_state["cadivor_dashboard_drilldown"] = "blocked"


def render_dashboard_summary_strip(*, overview: Dict[str, Any], metrics: Dict[str, Any]) -> None:
    """Backward-compatible alias — Engineering Overview only."""
    render_engineering_overview_brief_and_kpis(overview=overview, metrics=metrics)


def render_engineering_overview_workspace(
    *,
    overview: Dict[str, Any],
    metrics: Dict[str, Any],
    after_brief_hook: Optional[Callable[[], None]] = None,
    activation_hook: Optional[Callable[[], None]] = None,
) -> None:
    """Workspace 1 — brief, KPIs, release posture, recommendations, work queue, quick actions."""
    st.markdown('<div class="cv-page cv672-dashboard-workspace cv-dashboard-workspace">', unsafe_allow_html=True)
    render_engineering_overview_brief_and_kpis(overview=overview, metrics=metrics)
    if after_brief_hook:
        after_brief_hook()

    actions = overview.get("all_actions", [])
    recommendations = overview.get("recommendations", [])
    top_actions = list(overview.get("top_actions", []))

    drilldown = st.session_state.get("cadivor_dashboard_drilldown")
    if drilldown:
        labels = {"ready": "Ready for production", "actions": "Action today", "blocked": "Blocked projects"}
        st.markdown(f"#### {labels.get(drilldown, 'Engineering')} details")
        if st.button("Clear detail view", key="dashboard_clear_drilldown"):
            st.session_state.pop("cadivor_dashboard_drilldown", None)
            st.rerun()
        if drilldown == "actions":
            st.html(_full_work_queue_table_html(overview.get("action_today", []) or actions))
        else:
            projects = list(overview.get("projects", []))
            if drilldown == "ready":
                projects = [
                    project for project in projects
                    if int(_number(project.get("health"), 0)) >= 85
                    and int(_number(project.get("high"), 0)) == 0
                ]
            else:
                projects = [
                    project for project in projects
                    if int(_number(project.get("health"), 0)) < 70
                    or int(_number(project.get("high"), 0)) >= 3
                ]
            render_portfolio_project_summaries(projects=projects)

    st.markdown(
        f'<section class="cv6723-section">{_compact_release_posture_html(metrics)}</section>',
        unsafe_allow_html=True,
    )

    render_subsection_header(
        "Engineering recommendations",
        description="Cadivor-ranked actions based on saved evidence and open workflow.",
        icon="sparkles",
    )
    st.markdown(
        f'<div class="cv6723-section">{_compact_recommendations_html(recommendations)}</div>',
        unsafe_allow_html=True,
    )

    render_subsection_header(
        "Engineering Work Queue",
        description="Top priority tasks ranked by release and supply impact.",
        icon="clipboard",
    )
    st.markdown(
        f'<div class="cv6723-section">{_compact_work_queue_html(top_actions, limit=3)}</div>',
        unsafe_allow_html=True,
    )
    if len(actions) > 3:
        with st.expander(f"View complete work queue ({len(actions)})", expanded=False):
            st.html(_full_work_queue_table_html(actions))

    render_subsection_header(
        "Quick engineering actions",
        description="Jump to the most common engineering workflows.",
        icon="zap",
    )
    st.html(
        """
        <nav class="cv6723-action-toolbar cv6723-quick-actions cv-dashboard-quick-actions" aria-label="Quick engineering actions">
          <a class="cv6723-quick-action cv-card-interactive" href="?page=Engineering%20Decisions" target="_self">Engineering Decisions</a>
          <a class="cv6723-quick-action cv-card-interactive" href="?page=Procurement%20Advisor" target="_self">Procurement Advisor</a>
          <a class="cv6723-quick-action cv-card-interactive" href="?page=Monitoring" target="_self">Monitoring</a>
          <a class="cv6723-quick-action cv-card-interactive" href="?page=Reports" target="_self">Reports</a>
        </nav>
        """
    )

    if activation_hook:
        activation_hook()

    st.markdown("</div>", unsafe_allow_html=True)


def render_portfolio_project_summaries(
    *,
    projects: Iterable[Dict[str, Any]],
) -> None:
    project_list = list(projects or [])
    render_subsection_header(
        "Project summaries",
        description="Saved BOMs ranked by health and release readiness.",
        icon="chart-no-axes-combined",
    )
    if not project_list:
        st.markdown(
            """
            <section class="cv6723-compact-panel cv6723-empty-note">
              <strong>No portfolio projects yet</strong>
              <p>Analyze or save a BOM to begin building portfolio intelligence.</p>
            </section>
            """,
            unsafe_allow_html=True,
        )
        return

    summary_rows = []
    for project in project_list[:8]:
        project_id = str(project.get("id") or "")
        href = (
            f"?page=Analysis%20Details&analysis_id={html.escape(project_id, quote=True)}"
            if project_id
            else "?page=BOM%20Analyzer"
        )
        summary_rows.append(
            {
                "Project": _text(project.get("name"), "Saved BOM"),
                "Health": f"{int(_number(project.get('health'), 0))}/100",
                "Components": int(_number(project.get("parts"), 0)),
                "High-Risk": int(_number(project.get("high"), 0)),
                "Status": _text(project.get("status"), "Needs Review"),
                "Open": href,
            }
        )

    table_html = ['<div class="cv6723-project-table-wrap"><table class="cv6723-compact-table">']
    table_html.append(
        "<thead><tr>"
        "<th>Project</th><th>Health</th><th>Components</th>"
        "<th>High-Risk</th><th>Status</th><th>Open</th>"
        "</tr></thead><tbody>"
    )
    for row in summary_rows:
        table_html.append(
            "<tr>"
            f"<td>{html.escape(str(row['Project']))}</td>"
            f"<td>{html.escape(str(row['Health']))}</td>"
            f"<td>{row['Components']}</td>"
            f"<td>{row['High-Risk']}</td>"
            f'<td><span class="cv6723-status-chip cv6723-status-chip--neutral">{html.escape(str(row["Status"]))}</span></td>'
            f'<td><a class="cv6723-inline-link" href="{row["Open"]}" target="_self">Open Project</a></td>'
            "</tr>"
        )
    table_html.append("</tbody></table></div>")
    st.markdown("".join(table_html), unsafe_allow_html=True)


def render_team_workload_section(*, overview: Dict[str, Any]) -> None:
    workload = workload_rows(overview.get("all_actions", []))
    render_subsection_header(
        "Team workload",
        description="Open actions and estimated effort by team.",
        icon="clipboard",
    )
    if workload:
        cadivor_table(
            pd.DataFrame(workload).rename(
                columns={"team": "Team", "actions": "Open Actions", "hours": "Estimated Hours"}
            ),
            numeric_columns=["Open Actions", "Estimated Hours"],
            align={"Open Actions": "right", "Estimated Hours": "right"},
        )
    else:
        st.markdown(
            """
            <section class="cv6723-compact-panel cv6723-empty-note">
              <strong>No assigned workload recorded</strong>
              <p>Team workload will appear when actions are assigned.</p>
            </section>
            """,
            unsafe_allow_html=True,
        )


def render_dashboard_monitoring_workspace(
    *,
    overview: Dict[str, Any],
    parts: Iterable[Dict[str, Any]],
    alerts: Iterable[Dict[str, Any]],
) -> None:
    """Workspace 4 — monitoring summaries with link to full Monitoring page."""
    st.markdown('<div class="cv-page cv672-dashboard-workspace cv-dashboard-workspace">', unsafe_allow_html=True)
    changes = overview.get("recent_change_summary", {})
    alert_rows = list(alerts or [])
    timeline = [timeline_event(row) for row in alert_rows]
    supplier_rows = supplier_watch_rows(parts)

    st.html(
        """
        <header class="cv672-dashboard-workspace-header cv6723-monitoring-header">
          <div>
            <h2>Monitoring</h2>
            <p>Lifecycle, inventory, pricing, and supplier change summaries from your workspace.</p>
          </div>
          <a class="cv6723-quick-action cv6723-monitoring-header-link" href="?page=Monitoring" target="_self">
            Open Monitoring Center →
          </a>
        </header>
        """
    )

    render_kpi_row_safe(
        [
            MetricCard(
                label="Lifecycle Changes",
                value=str(int(_number(changes.get("lifecycle"), 0))),
                detail="Recent lifecycle updates",
                tone="warning",
                icon="clock-3",
            ),
            MetricCard(
                label="Stock Changes",
                value=str(int(_number(changes.get("stock"), 0))),
                detail="Inventory movement recorded",
                tone="monitoring",
                icon="package-search",
            ),
            MetricCard(
                label="Price Changes",
                value=str(int(_number(changes.get("price"), 0))),
                detail="Pricing movement recorded",
                tone="confidence",
                icon="dollar-sign",
            ),
            MetricCard(
                label="Supplier Changes",
                value=str(len(supplier_rows)),
                detail="Sourcing signals on this dashboard",
                tone="warning" if supplier_rows else "success",
                icon="factory",
            ),
        ],
        columns=4,
    )

    lifecycle_events = [event for event in timeline if event["category"] == "Lifecycle"]
    stock_events = [event for event in timeline if event["category"] == "Stock"]
    price_events = [event for event in timeline if event["category"] == "Price"]
    supplier_events = [event for event in timeline if event["category"] == "Supplier"]

    if supplier_events:
        supplier_body = _monitoring_events_html(
            supplier_events,
            empty_copy="No supplier monitoring events are recorded yet.",
            limit=4,
            compact=True,
        )
    elif supplier_rows:
        watch_rows = [
            {
                "Component": f'{item["part"]} · {item["manufacturer"]}',
                "Signal": item["signal"],
                "Detail": item["detail"],
            }
            for item in supplier_rows[:4]
        ]
        supplier_body = (
            '<div class="cv6723-compact-table-wrap"><table class="cv6723-compact-table">'
            "<thead><tr><th>Component</th><th>Signal</th><th>Detail</th></tr></thead><tbody>"
            + "".join(
                f"<tr><td>{html.escape(row['Component'])}</td>"
                f"<td>{html.escape(row['Signal'])}</td>"
                f"<td>{html.escape(row['Detail'])}</td></tr>"
                for row in watch_rows
            )
            + "</tbody></table></div>"
        )
    else:
        supplier_body = _monitoring_events_html(
            [],
            empty_copy="No supplier monitoring events are recorded yet.",
            limit=4,
            compact=True,
        )

    category_panels = [
        ("Lifecycle changes", len(lifecycle_events), lifecycle_events, "No lifecycle monitoring events are recorded yet."),
        ("Stock changes", len(stock_events), stock_events, "No stock monitoring events are recorded yet."),
        ("Price changes", len(price_events), price_events, "No price monitoring events are recorded yet."),
        ("Supplier changes", len(supplier_events) or len(supplier_rows), None, "No supplier monitoring events are recorded yet."),
    ]

    st.markdown('<div class="cv6723-monitor-grid">', unsafe_allow_html=True)
    grid_row_1 = st.columns(2, gap="small")
    grid_row_2 = st.columns(2, gap="small")
    grid_slots = [grid_row_1[0], grid_row_1[1], grid_row_2[0], grid_row_2[1]]

    for slot, (title, count, events, empty_copy) in zip(grid_slots, category_panels):
        with slot:
            if title == "Supplier changes":
                body_html = supplier_body
            else:
                body_html = _monitoring_events_html(
                    events or [],
                    empty_copy=empty_copy,
                    limit=4,
                    compact=True,
                )
            st.markdown(
                _monitoring_category_panel_html(title=title, count=count, body_html=body_html),
                unsafe_allow_html=True,
            )
            if events and len(events) > 4:
                with st.expander(f"View all {title.lower()}", expanded=False):
                    st.html(
                        _monitoring_events_html(
                            events,
                            empty_copy=empty_copy,
                            limit=12,
                            compact=True,
                        )
                    )
    st.markdown("</div>", unsafe_allow_html=True)

    render_subsection_header(
        "Recent monitoring events",
        description="Latest recorded monitoring activity.",
        icon="history",
    )
    if timeline:
        st.html(
            _monitoring_events_html(
                timeline,
                empty_copy="No monitoring activity yet.",
                limit=5,
                compact=True,
            )
        )
        if len(timeline) > 5:
            with st.expander(f"View all monitoring events ({len(timeline)})", expanded=False):
                st.html(
                    _monitoring_events_html(
                        timeline,
                        empty_copy="No monitoring activity yet.",
                        limit=20,
                        compact=True,
                    )
                )
    else:
        st.markdown(
            """
            <section class="cv6723-compact-panel cv6723-empty-note">
              <strong>No monitoring activity yet</strong>
              <p>Add monitored components to track lifecycle, stock, price, and supplier changes.</p>
            </section>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)


def render_living_workspace(
    *,
    overview: Dict[str, Any],
    parts: Iterable[Dict[str, Any]],
) -> None:
    """Legacy full-page Engineering Overview — kept for fallback paths."""
    metrics = compute_dashboard_summary_metrics(overview)
    render_dashboard_summary_strip(overview=overview, metrics=metrics)
    render_engineering_overview_workspace(
        overview=overview,
        metrics=metrics,
    )

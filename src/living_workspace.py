"""Cadivor Milestone 18.0 — Living Engineering Workspace.

This module owns the customer-facing Engineering Overview so the main
Streamlit entry point can remain focused on routing and data access.
"""
from __future__ import annotations

from datetime import datetime, timezone
import html
from typing import Any, Callable, Dict, Iterable, List, Optional

import pandas as pd
import streamlit as st

from src.ui.cadivor_design_system import (
    MetricCard,
    cadivor_button_wrap,
    cadivor_button_wrap_end,
    cadivor_card,
    cadivor_meta_row,
    cadivor_metric_row,
    cadivor_panel,
    cadivor_panel_end,
    cadivor_table,
    render_kpi_row_safe,
    render_metric_strip,
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


def render_dashboard_summary_strip(*, overview: Dict[str, Any], metrics: Dict[str, Any]) -> None:
    """Backward-compatible alias — Engineering Overview only."""
    render_engineering_overview_brief_and_kpis(overview=overview, metrics=metrics)


def render_engineering_overview_workspace(
    *,
    overview: Dict[str, Any],
    metrics: Dict[str, Any],
    internal_nav_button: Callable[..., Any],
    after_brief_hook: Optional[Callable[[], None]] = None,
    activation_hook: Optional[Callable[[], None]] = None,
) -> None:
    """Workspace 1 — brief, KPIs, release posture, recommendations, work queue, quick actions."""
    st.markdown('<div class="cv672-dashboard-workspace">', unsafe_allow_html=True)
    render_engineering_overview_brief_and_kpis(overview=overview, metrics=metrics)
    if after_brief_hook:
        after_brief_hook()

    actions = overview.get("all_actions", [])
    recommendations = overview.get("recommendations", [])

    cadivor_panel(title="Release posture", subtitle=metrics["release_label"], tone="soft")
    cadivor_meta_row([(metrics["health_status"], metrics["health_tone"])])
    cadivor_panel_end()

    render_subsection_header(
        "Engineering recommendations",
        description="Cadivor-ranked actions based on saved evidence and open workflow.",
        icon="sparkles",
    )
    if recommendations:
        for index, recommendation in enumerate(recommendations[:3]):
            cadivor_card(
                f"Recommendation {index + 1}",
                _text(recommendation),
                badge="Priority" if index == 0 else "Review",
                badge_tone="info" if index == 0 else "neutral",
            )
    else:
        st.info("No urgent recommendation is recorded. Continue routine monitoring.")

    render_subsection_header(
        "Engineering Work Queue",
        description="Work is ranked by release and supply impact.",
        icon="clipboard",
    )
    if not overview.get("top_actions"):
        st.success("No urgent work is currently recorded.")
    for index, action in enumerate(overview.get("top_actions", [])):
        priority = int(_number(action.get("priority"), 0))
        effort = "10 min" if priority >= 85 else "20 min" if priority >= 60 else "30 min"
        due_label = _text(action.get("due"), "This week")
        cadivor_panel(title=_text(action.get("item"), "BOM"), subtitle=_text(action.get("title"), "Review engineering action"))
        cadivor_meta_row(
            [
                (f"Priority {priority}/100", "info"),
                (_text(action.get("owner"), "Engineering"), "neutral"),
                (f"Estimated {effort}", "monitoring"),
                (f"Due {due_label}", "warning"),
            ]
        )
        cadivor_panel_end()
        destination = _text(action.get("page"), "Engineering Decisions")
        kwargs: Dict[str, Any] = {}
        if destination == "Engineering Decisions" and action.get("decision_id"):
            kwargs["decision_id"] = action["decision_id"]
        internal_nav_button(
            _action_button_label(action),
            destination,
            key=f"living_action_{index}",
            use_container_width=True,
            **kwargs,
        )

    if len(actions) > 5:
        with st.expander(f"View complete work queue ({len(actions)})", expanded=False):
            queue_df = pd.DataFrame(actions)
            visible = [column for column in ("item", "title", "owner", "due", "priority") if column in queue_df.columns]
            cadivor_table(
                queue_df[visible].rename(
                    columns={
                        "item": "Component or Project",
                        "title": "Recommended Work",
                        "owner": "Owner",
                        "due": "Due",
                        "priority": "Priority",
                    }
                ),
                caption="Complete prioritized engineering queue",
                monospace_columns=["Component or Project"],
                numeric_columns=["Priority"],
                align={"Priority": "right"},
            )

    render_subsection_header("Quick engineering actions", icon="zap")
    nav_cols = st.columns(4)
    with nav_cols[0]:
        cadivor_button_wrap("secondary")
        internal_nav_button("Engineering Decisions", "Engineering Decisions", key="living_decisions", use_container_width=True)
        cadivor_button_wrap_end()
    with nav_cols[1]:
        cadivor_button_wrap("secondary")
        internal_nav_button("Procurement Advisor", "Procurement Advisor", key="living_procurement", use_container_width=True)
        cadivor_button_wrap_end()
    with nav_cols[2]:
        cadivor_button_wrap("secondary")
        internal_nav_button("Monitoring", "Monitoring", key="living_monitoring", use_container_width=True)
        cadivor_button_wrap_end()
    with nav_cols[3]:
        cadivor_button_wrap("secondary")
        internal_nav_button("Reports", "Reports", key="living_reports", use_container_width=True)
        cadivor_button_wrap_end()

    if activation_hook:
        activation_hook()

    st.markdown("</div>", unsafe_allow_html=True)


def render_portfolio_project_summaries(
    *,
    projects: Iterable[Dict[str, Any]],
    internal_nav_button: Callable[..., Any],
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
            <section class="cv672-dashboard-empty">
              <strong>No portfolio projects yet</strong>
              <p>Analyze or save a BOM to begin building portfolio intelligence.</p>
            </section>
            """,
            unsafe_allow_html=True,
        )
        return

    impact_rows = []
    for project in project_list[:8]:
        impact_rows.append(
            {
                "Project": _text(project.get("name"), "Saved BOM"),
                "Health": f"{int(_number(project.get('health'), 0))}/100",
                "Components": int(_number(project.get("parts"), 0)),
                "High-Risk": int(_number(project.get("high"), 0)),
                "Status": _text(project.get("status"), "Needs Review"),
            }
        )
    cadivor_table(
        pd.DataFrame(impact_rows),
        badge_columns=["Status"],
        numeric_columns=["Components", "High-Risk"],
        align={"Components": "right", "High-Risk": "right", "Health": "right"},
    )

    render_subsection_header(
        "Production readiness",
        description="Projects requiring attention appear first.",
        icon="badge-check",
    )
    for index, project in enumerate(project_list[:5]):
        status = _text(project.get("status"), "Needs Review")
        badge_tone = "success" if status == "Ready for Production" else "warning"
        updated = _relative_time(project.get("updated_at") or project.get("created_at"))
        health = int(_number(project.get("health"), 0))
        parts_count = int(_number(project.get("parts"), 0))
        high_count = int(_number(project.get("high"), 0))
        project_health_tone = "success" if health >= 85 else "warning" if health >= 70 else "danger"
        cadivor_panel(
            title=_text(project.get("name"), "Saved BOM"),
            subtitle=f"Updated {updated}",
            tone="soft",
        )
        cadivor_meta_row([(status, badge_tone)])
        render_metric_strip(
            [
                MetricCard(label="Health", value=f"{health}/100", tone=project_health_tone, icon="gauge"),
                MetricCard(label="Components", value=str(parts_count), tone="info", icon="boxes"),
                MetricCard(
                    label="High-Risk",
                    value=str(high_count),
                    tone="danger" if high_count else "success",
                    icon="triangle-alert",
                ),
            ],
            columns=3,
        )
        cadivor_panel_end()
        if project.get("id"):
            internal_nav_button(
                "Open Project",
                "Analysis Details",
                key=f"living_project_{index}",
                use_container_width=True,
                analysis_id=project["id"],
            )


def render_team_workload_section(*, overview: Dict[str, Any]) -> None:
    workload = workload_rows(overview.get("all_actions", []))
    render_subsection_header("Team Workload", icon="clipboard")
    if workload:
        cadivor_table(
            pd.DataFrame(workload).rename(
                columns={"team": "Team", "actions": "Open Actions", "hours": "Estimated Hours"}
            ),
            numeric_columns=["Open Actions", "Estimated Hours"],
            align={"Open Actions": "right", "Estimated Hours": "right"},
        )
    else:
        st.info("No assigned workload is currently recorded.")


def render_dashboard_monitoring_workspace(
    *,
    overview: Dict[str, Any],
    parts: Iterable[Dict[str, Any]],
    alerts: Iterable[Dict[str, Any]],
    internal_nav_button: Callable[..., Any],
) -> None:
    """Workspace 4 — monitoring summaries with link to full Monitoring page."""
    st.markdown('<div class="cv672-dashboard-workspace">', unsafe_allow_html=True)
    changes = overview.get("recent_change_summary", {})
    alert_rows = list(alerts or [])
    timeline = [timeline_event(row) for row in alert_rows]
    supplier_rows = supplier_watch_rows(parts)

    st.markdown(
        """
        <header class="cv672-dashboard-workspace-header">
          <h2>Monitoring</h2>
          <p>Lifecycle, inventory, pricing, and supplier change summaries from your workspace.</p>
        </header>
        """,
        unsafe_allow_html=True,
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

    render_subsection_header("Lifecycle changes", icon="clock-3")
    st.html(_monitoring_events_html(lifecycle_events, empty_copy="No lifecycle monitoring events are recorded yet."))

    render_subsection_header("Stock changes", icon="package-search")
    st.html(_monitoring_events_html(stock_events, empty_copy="No stock monitoring events are recorded yet."))

    render_subsection_header("Price changes", icon="dollar-sign")
    st.html(_monitoring_events_html(price_events, empty_copy="No price monitoring events are recorded yet."))

    render_subsection_header("Supplier changes", icon="factory")
    if supplier_events:
        st.html(_monitoring_events_html(supplier_events, empty_copy="No supplier monitoring events are recorded yet."))
    elif supplier_rows:
        watch_rows = [
            {
                "Component": f'{item["part"]} · {item["manufacturer"]}',
                "Signal": item["signal"],
                "Detail": item["detail"],
                "Priority": item["priority"],
            }
            for item in supplier_rows
        ]
        cadivor_table(
            pd.DataFrame(watch_rows),
            monospace_columns=["Component"],
            numeric_columns=["Priority"],
            align={"Priority": "right"},
        )
    else:
        st.html(_monitoring_events_html([], empty_copy="No supplier monitoring events are recorded yet."))

    render_subsection_header(
        "Recent monitoring events",
        description="Latest recorded monitoring activity.",
        icon="history",
    )
    if timeline:
        st.html(_monitoring_events_html(timeline, empty_copy="No monitoring activity yet."))
    else:
        st.markdown(
            """
            <section class="cv672-dashboard-empty">
              <strong>No monitoring activity yet</strong>
              <p>Add monitored components to track lifecycle, stock, price, and supplier changes.</p>
            </section>
            """,
            unsafe_allow_html=True,
        )

    internal_nav_button(
        "Open Monitoring Center",
        "Monitoring",
        key="dashboard_monitoring_center",
        use_container_width=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


def render_living_workspace(
    *,
    overview: Dict[str, Any],
    parts: Iterable[Dict[str, Any]],
    internal_nav_button: Callable[..., Any],
) -> None:
    """Legacy full-page Engineering Overview — kept for fallback paths."""
    metrics = compute_dashboard_summary_metrics(overview)
    render_dashboard_summary_strip(overview=overview, metrics=metrics)
    render_engineering_overview_workspace(
        overview=overview,
        metrics=metrics,
        internal_nav_button=internal_nav_button,
    )

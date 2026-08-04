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


def _timeline_event(alert: Dict[str, Any]) -> Dict[str, str]:
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


def _supplier_watch(parts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


def _workload(actions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    totals: Dict[str, Dict[str, Any]] = {}
    for action in actions or []:
        owner = _text(action.get("owner"), "Engineering")
        bucket = totals.setdefault(owner, {"team": owner, "actions": 0, "hours": 0})
        bucket["actions"] += 1
        priority = int(_number(action.get("priority"), 0))
        bucket["hours"] += 4 if priority >= 85 else 2 if priority >= 60 else 1
    return sorted(totals.values(), key=lambda row: (-row["actions"], row["team"]))[:4]


def _render_css() -> None:
    """Legacy page CSS retired — styling comes from cadivor_design_system.css."""
    return


def render_living_workspace(
    *,
    overview: Dict[str, Any],
    parts: Iterable[Dict[str, Any]],
    internal_nav_button: Callable[..., Any],
) -> None:
    """Render the Living Engineering Workspace using prepared intelligence."""
    _render_css()
    st.html('<div class="cv64-page-shell">')

    changes = overview.get("recent_change_summary", {})
    projects = overview.get("projects", [])
    actions = overview.get("all_actions", [])
    timeline = [_timeline_event(row) for row in overview.get("recent_alerts", [])]
    supplier_watch = _supplier_watch(parts)
    workload = _workload(actions)
    recommendations = overview.get("recommendations", [])

    blocked_projects = sum(
        1 for project in projects
        if int(_number(project.get("health"), 0)) < 70 or int(_number(project.get("high"), 0)) >= 3
    )
    portfolio_health = (
        round(sum(int(_number(project.get("health"), 0)) for project in projects) / len(projects))
        if projects else 0
    )

    top_action = overview.get("top_actions", [{}])[0] if overview.get("top_actions") else {}
    brief_action = _text(top_action.get("title"), "Continue routine monitoring.")
    brief_item = _text(top_action.get("item"), "your component portfolio")

    health_tone = "success" if portfolio_health >= 85 else "warning" if portfolio_health >= 70 else "danger"
    health_status = "Excellent" if portfolio_health >= 90 else "Stable" if portfolio_health >= 75 else "Needs attention"
    release_label = (
        "Ready for controlled release"
        if portfolio_health >= 85 and blocked_projects == 0
        else "Release review required"
        if blocked_projects
        else "Controlled review recommended"
    )

    render_section_header(
        "Your Engineering Brief",
        eyebrow="Engineering Workspace",
        description=(
            f"{_text(overview.get('summary'))} "
            f"The most important next step is to {brief_action.lower()} for {brief_item}."
        ),
        icon="briefcase-business",
    )

    render_kpi_row_safe(
        [
            MetricCard(
                label="Portfolio Health",
                value=f"{portfolio_health}%",
                status=health_status,
                tone=health_tone,
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
                value=str(blocked_projects),
                detail="Require immediate review" if blocked_projects else "No blockers recorded",
                tone="danger" if blocked_projects else "success",
                icon="octagon-alert",
            ),
        ],
        columns=4,
    )

    cadivor_panel(title="Release posture", subtitle=release_label, tone="soft")
    cadivor_meta_row([(health_status, health_tone)])
    cadivor_metric_row(
        [
            MetricCard(label="Components Changed", value=str(int(_number(changes.get("components"), 0))), tone="info", icon="git-compare"),
            MetricCard(label="Lifecycle Updates", value=str(int(_number(changes.get("lifecycle"), 0))), tone="warning", icon="clock-3"),
            MetricCard(label="Stock Changes", value=str(int(_number(changes.get("stock"), 0))), tone="monitoring", icon="package-search"),
            MetricCard(label="Price Changes", value=str(int(_number(changes.get("price"), 0))), tone="confidence", icon="dollar-sign"),
        ],
        columns=4,
        compact=True,
    )
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

    if projects:
        render_subsection_header(
            "Project impact",
            description="Saved BOMs ranked by health and release readiness.",
            icon="chart-no-axes-combined",
        )
        impact_rows = []
        for project in projects[:8]:
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

    left, right = st.columns([1.28, 1], gap="medium")

    with left:
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

        render_subsection_header(
            "Engineering Timeline",
            description="The latest lifecycle, inventory, pricing, and supplier changes.",
            icon="history",
        )
        if timeline:
            timeline_html = ['<div class="cv64-timeline">']
            for event in timeline[:6]:
                timeline_html.append(
                    '<div class="cv64-timeline-item">'
                    f'<div class="cv64-timeline-time">{html.escape(event["time"])}</div>'
                    f'<div class="cv64-timeline-title">{html.escape(event["part"])} · {html.escape(event["category"])}</div>'
                    f'<div class="cv64-timeline-copy">{html.escape(event["change"])}</div>'
                    '</div>'
                )
            timeline_html.append('</div>')
            st.html(''.join(timeline_html))
        else:
            st.info("No recent engineering changes are available.")

    with right:
        render_subsection_header(
            "Production Readiness",
            description="Projects requiring attention appear first.",
            icon="badge-check",
        )
        if not projects:
            st.info("No saved projects are available yet.")
        for index, project in enumerate(projects[:5]):
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

        render_subsection_header(
            "Supplier Watch",
            description="Components with the clearest sourcing exposure.",
            icon="factory",
        )
        if supplier_watch:
            watch_rows = []
            for item in supplier_watch:
                watch_rows.append(
                    {
                        "Component": f'{item["part"]} · {item["manufacturer"]}',
                        "Signal": item["signal"],
                        "Detail": item["detail"],
                        "Priority": item["priority"],
                    }
                )
            cadivor_table(
                pd.DataFrame(watch_rows),
                monospace_columns=["Component"],
                numeric_columns=["Priority"],
                align={"Priority": "right"},
            )
        else:
            st.success("No supplier exception currently requires attention.")

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

    st.html("</div>")

    with st.expander("More workspace tools", expanded=False):
        shortcuts = st.columns(5)
        items = [
            ("Analyze BOM", "BOM Analyzer"),
            ("Find Alternatives", "Alternative Finder"),
            ("Portfolio Intelligence", "Portfolio Intelligence"),
            ("Engineering Decisions", "Engineering Decisions"),
            ("Reports", "Reports"),
        ]
        for index, (label, destination) in enumerate(items):
            with shortcuts[index]:
                internal_nav_button(
                    label,
                    destination,
                    key=f"living_shortcut_{index}",
                    use_container_width=True,
                )

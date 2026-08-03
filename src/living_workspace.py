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
    cadivor_badge,
    cadivor_metric_row,
    cadivor_panel,
    cadivor_panel_end,
    cadivor_section_header,
    cadivor_table,
    cadivor_toolbar_end,
    cadivor_toolbar_start,
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
    st.markdown(
        """
        <style id="cadivor-living-workspace-18">
          .cv18-brief{
            border:1px solid #bfdbfe;background:linear-gradient(135deg,#ffffff,#eef5ff);
            border-radius:24px;padding:24px;margin-bottom:16px;
            box-shadow:0 16px 42px rgba(37,99,235,.07)
          }
          .cv18-eyebrow{font-size:11px;font-weight:900;color:#2563eb;letter-spacing:.12em;text-transform:uppercase}
          .cv18-title{font-size:30px;font-weight:950;color:#0f172a;letter-spacing:-.045em;margin:7px 0}
          .cv18-copy{font-size:14px;font-weight:680;color:#52647a;line-height:1.58;max-width:1050px}
          .cv18-status-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:17px}
          .cv18-status{background:#fff;border:1px solid #dbe3ef;border-radius:15px;padding:13px}
          .cv18-status strong{display:block;font-size:24px;color:#0f172a;letter-spacing:-.035em}
          .cv18-status span{font-size:11px;font-weight:820;color:#64748b}
          .cv18-section{font-size:22px;font-weight:950;color:#0f172a;letter-spacing:-.03em;margin:20px 0 4px}
          .cv18-subtitle{font-size:13px;font-weight:650;color:#64748b;margin-bottom:11px}
          .cv18-card{
            border:1px solid #dbe3ef;background:#fff;border-radius:17px;padding:16px;
            margin-bottom:10px;box-shadow:0 8px 24px rgba(15,23,42,.04)
          }
          .cv18-card-title{font-size:16px;font-weight:950;color:#0f172a}
          .cv18-card-copy{font-size:13px;font-weight:680;color:#475569;line-height:1.5;margin-top:6px}
          .cv18-meta{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}
          .cv18-meta span{
            font-size:10px;font-weight:850;color:#1d4ed8;background:#eff6ff;
            border:1px solid #dbeafe;border-radius:999px;padding:5px 8px
          }
          .cv18-timeline{border-left:2px solid #dbeafe;margin-left:7px;padding-left:17px}
          .cv18-event{position:relative;margin-bottom:15px}
          .cv18-event:before{
            content:"";position:absolute;left:-23px;top:5px;width:10px;height:10px;
            border-radius:50%;background:#2563eb;border:3px solid #eff6ff
          }
          .cv18-event-time{font-size:10px;font-weight:850;color:#64748b}
          .cv18-event-title{font-size:14px;font-weight:920;color:#0f172a;margin-top:2px}
          .cv18-event-copy{font-size:12px;font-weight:650;color:#52647a;line-height:1.45}
          .cv18-project{
            border:1px solid #dbe3ef;background:#fff;border-radius:16px;padding:15px;margin-bottom:10px
          }
          .cv18-project-top{display:flex;align-items:center;justify-content:space-between;gap:10px}
          .cv18-project-name{font-size:15px;font-weight:950;color:#0f172a}
          .cv18-pill{font-size:10px;font-weight:900;border-radius:999px;padding:5px 8px}
          .cv18-pill.ready{color:#047857;background:#ecfdf5;border:1px solid #a7f3d0}
          .cv18-pill.review{color:#a16207;background:#fffbeb;border:1px solid #fde68a}
          .cv18-progress{height:8px;background:#e2e8f0;border-radius:999px;overflow:hidden;margin:10px 0}
          .cv18-progress i{display:block;height:100%;background:#2563eb;border-radius:999px}
          .cv18-project-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
          .cv18-project-stats div{font-size:11px;font-weight:720;color:#64748b}
          .cv18-project-stats strong{display:block;font-size:14px;color:#0f172a}
          .cv18-watch{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;border-bottom:1px solid #edf2f7;padding:11px 0}
          .cv18-watch:last-child{border-bottom:0}
          .cv18-watch strong{font-size:13px;color:#0f172a}
          .cv18-watch p{font-size:11px;color:#64748b;margin:3px 0 0}
          .cv18-score{font-size:11px;font-weight:900;color:#b91c1c;background:#fff1f2;border:1px solid #fecdd3;border-radius:999px;padding:5px 8px;white-space:nowrap}
          .cv18-workload{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
          .cv18-workload-card{border:1px solid #e2e8f0;border-radius:14px;padding:13px;background:#fff}
          .cv18-workload-card strong{font-size:14px;color:#0f172a}
          .cv18-workload-card span{display:block;font-size:11px;color:#64748b;margin-top:4px}
          @media(max-width:900px){
            .cv18-status-grid,.cv18-project-stats,.cv18-workload{grid-template-columns:1fr 1fr}
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_living_workspace(
    *,
    overview: Dict[str, Any],
    parts: Iterable[Dict[str, Any]],
    internal_nav_button: Callable[..., Any],
) -> None:
    """Render the Living Engineering Workspace using prepared intelligence."""
    st.markdown('<div class="cv64-page-shell">', unsafe_allow_html=True)

    changes = overview.get("recent_change_summary", {})
    projects = overview.get("projects", [])
    actions = overview.get("all_actions", [])
    timeline = [_timeline_event(row) for row in overview.get("recent_alerts", [])]
    supplier_watch = _supplier_watch(parts)
    workload = _workload(actions)

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

    cadivor_section_header(
        "Your Engineering Brief",
        eyebrow="Engineering Workspace",
        description=(
            f"{_text(overview.get('summary'))} "
            f"The most important next step is to {brief_action.lower()} for {brief_item}."
        ),
        icon="sparkles",
    )

    cadivor_metric_row(
        [
            MetricCard(
                label="Portfolio Health",
                value=f"{portfolio_health}%",
                status=health_status,
                tone=health_tone,
                icon="shield",
            ),
            MetricCard(
                label="Ready for Production",
                value=str(overview.get("ready_projects", 0)),
                detail="Projects cleared for release",
                tone="success",
                icon="chart",
            ),
            MetricCard(
                label="Action Today",
                value=str(len(overview.get("action_today", []))),
                detail="Prioritized engineering tasks",
                tone="info",
                icon="clipboard",
            ),
            MetricCard(
                label="Blocked Projects",
                value=str(blocked_projects),
                detail="Require immediate review",
                tone="danger" if blocked_projects else "monitoring",
                icon="alert",
            ),
        ]
    )

    cadivor_toolbar_start()
    nav_cols = st.columns(4)
    with nav_cols[0]:
        internal_nav_button("Engineering Decisions", "Engineering Decisions", key="living_decisions", use_container_width=True)
    with nav_cols[1]:
        internal_nav_button("Procurement Advisor", "Procurement Advisor", key="living_procurement", use_container_width=True)
    with nav_cols[2]:
        internal_nav_button("Monitoring", "Monitoring", key="living_monitoring", use_container_width=True)
    with nav_cols[3]:
        internal_nav_button("Reports", "Reports", key="living_reports", use_container_width=True)
    cadivor_toolbar_end()

    left, right = st.columns([1.28, 1])

    with left:
        cadivor_section_header(
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
            st.markdown(
                f'<div class="cv64-meta-row">'
                f'{cadivor_badge(f"Priority {priority}/100", "info")}'
                f'{cadivor_badge(_text(action.get("owner"), "Engineering"), "neutral")}'
                f'{cadivor_badge(f"Estimated {effort}", "monitoring")}'
                f'{cadivor_badge(f"Due {due_label}", "warning")}'
                f"</div>",
                unsafe_allow_html=True,
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

        cadivor_section_header(
            "Engineering Timeline",
            description="The latest lifecycle, inventory, pricing, and supplier changes.",
            icon="activity",
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
            st.markdown(''.join(timeline_html), unsafe_allow_html=True)
        else:
            st.info("No recent engineering changes are available.")

    with right:
        cadivor_section_header(
            "Production Readiness",
            description="Projects requiring attention appear first.",
            icon="shield",
        )
        for index, project in enumerate(projects[:5]):
            status = _text(project.get("status"), "Needs Review")
            badge_tone = "success" if status == "Ready for Production" else "warning"
            updated = _relative_time(project.get("updated_at") or project.get("created_at"))
            cadivor_panel(
                title=_text(project.get("name"), "Saved BOM"),
                subtitle=f"Updated {updated}",
                tone="soft",
            )
            st.markdown(
                f'<div class="cv64-meta-row">{cadivor_badge(status, badge_tone)}</div>'
                f'<div class="cv64-progress"><i style="width:{int(_number(project.get("health"), 0))}%"></i></div>'
                f'<div class="cv64-mini-metrics">'
                f'<div><strong>{int(_number(project.get("health"), 0))}/100</strong><span>Health</span></div>'
                f'<div><strong>{int(_number(project.get("parts"), 0))}</strong><span>Components</span></div>'
                f'<div><strong>{int(_number(project.get("high"), 0))}</strong><span>High-Risk</span></div>'
                f"</div>",
                unsafe_allow_html=True,
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

        cadivor_section_header(
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

        cadivor_section_header("Team Workload", icon="clipboard")
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

    cadivor_section_header(
        "What Changed Since the Last Review",
        icon="activity",
    )
    cadivor_metric_row(
        [
            MetricCard(label="Components Changed", value=str(int(_number(changes.get("components"), 0))), tone="info", icon="layers"),
            MetricCard(label="Lifecycle Updates", value=str(int(_number(changes.get("lifecycle"), 0))), tone="warning", icon="alert"),
            MetricCard(label="Stock Changes", value=str(int(_number(changes.get("stock"), 0))), tone="monitoring", icon="factory"),
            MetricCard(label="Price Changes", value=str(int(_number(changes.get("price"), 0))), tone="confidence", icon="chart"),
        ],
        columns=4,
    )

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

    st.markdown("</div>", unsafe_allow_html=True)

"""Workspace-aware command records for Cadivor Sprint 34.2.

The loader is deliberately defensive: older Cadivor databases may not yet have
all collaboration or reporting tables/columns. Missing sources are skipped so
Command Center navigation remains available.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode


def _text(value: Any, default: str = "") -> str:
    value = "" if value is None else str(value).strip()
    return value or default


def _href(page: str, **params: Any) -> str:
    payload = {"page": page}
    payload.update({key: value for key, value in params.items() if value not in (None, "")})
    return "?" + urlencode(payload, quote_via=quote)


def _rows(query) -> list[dict]:
    try:
        response = query.execute()
        return list(response.data or [])
    except Exception:
        return []


def _command(
    command_id: str,
    title: str,
    subtitle: str,
    href: str,
    category: str,
    icon: str,
    keywords: list[str] | tuple[str, ...] = (),
    badge: str = "",
    entity_type: str = "record",
) -> dict:
    return {
        "id": command_id,
        "title": title,
        "subtitle": subtitle,
        "href": href,
        "category": category,
        "icon": icon,
        "keywords": [item for item in keywords if item],
        "shortcut": badge,
        "entityType": entity_type,
    }


def build_workspace_commands(supabase, user_id: str, *, limit_per_source: int = 80) -> list[dict]:
    """Return searchable BOMs, components, alerts, decisions, and alternatives."""
    commands: list[dict] = []
    analysis_names: dict[str, str] = {}

    analyses = _rows(
        supabase.table("analyses")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit_per_source)
    )
    for index, row in enumerate(analyses):
        analysis_id = _text(row.get("id") or row.get("analysis_id"))
        title = _text(row.get("project_name") or row.get("filename"), "Saved BOM")
        analysis_names[analysis_id] = title
        parts = _text(row.get("total_parts"), "—")
        health = _text(row.get("health_score"), "—")
        high = _text(row.get("high_risk_count"), "0")
        commands.append(
            _command(
                f"bom-record-{analysis_id or index}",
                title,
                f"{parts} parts · Health {health} · {high} high-risk",
                _href("Analysis Details", analysis_id=analysis_id),
                "Saved BOMs",
                "▦",
                [title, row.get("filename"), "project", "bom", "saved analysis"],
                "BOM",
                "bom",
            )
        )
        commands.append(
            _command(
                f"report-record-{analysis_id or index}",
                f"Report · {title}",
                "Open executive, lifecycle, sourcing, and readiness reports",
                _href("Reports", analysis_id=analysis_id),
                "Reports",
                "□",
                [title, "executive report", "lifecycle report", "risk report", "pdf"],
                "Report",
                "report",
            )
        )

    parts = _rows(
        supabase.table("analysis_parts")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(max(limit_per_source * 3, 150))
    )
    seen_parts: set[tuple[str, str]] = set()
    for index, row in enumerate(parts):
        mpn = _text(row.get("mpn") or row.get("part_number") or row.get("manufacturer_part_number"))
        if not mpn:
            continue
        analysis_id = _text(row.get("analysis_id"))
        key = (mpn.lower(), analysis_id)
        if key in seen_parts:
            continue
        seen_parts.add(key)
        manufacturer = _text(row.get("manufacturer"), "Unknown manufacturer")
        risk = _text(row.get("risk_level") or row.get("risk"), "Unrated")
        lifecycle = _text(row.get("lifecycle_status") or row.get("lifecycle"), "Lifecycle unknown")
        project = analysis_names.get(analysis_id, "Saved BOM")
        commands.append(
            _command(
                f"component-{analysis_id}-{mpn}-{index}",
                mpn,
                f"{manufacturer} · {risk} risk · {lifecycle} · {project}",
                _href("Alternative Finder", original_part=mpn, return_analysis_id=analysis_id),
                "Components",
                "◉",
                [mpn, manufacturer, risk, lifecycle, project, "part", "component", "alternative"],
                risk,
                "component",
            )
        )

    manufacturers: dict[str, int] = {}
    for row in parts:
        manufacturer = _text(row.get("manufacturer"))
        if manufacturer:
            manufacturers[manufacturer] = manufacturers.get(manufacturer, 0) + 1
    for index, (manufacturer, count) in enumerate(sorted(manufacturers.items(), key=lambda item: (-item[1], item[0].lower()))):
        commands.append(
            _command(
                f"supplier-{index}-{manufacturer}",
                manufacturer,
                f"Manufacturer or supplier represented by {count} saved component record(s)",
                _href("Procurement Advisor"),
                "Suppliers",
                "$",
                [manufacturer, "supplier", "manufacturer", "sourcing", "procurement"],
                f"{count} parts",
                "supplier",
            )
        )

    alerts = _rows(
        supabase.table("monitor_alerts")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit_per_source)
    )
    for index, row in enumerate(alerts):
        part = _text(row.get("part_number") or row.get("mpn"), "Monitoring alert")
        alert_type = _text(row.get("alert_type") or row.get("change_type") or row.get("event_type"), "Risk change")
        message = _text(row.get("message") or row.get("alert_message") or row.get("summary"), alert_type)
        status = _text(row.get("status"), "Open")
        analysis_id = _text(row.get("analysis_id"))
        commands.append(
            _command(
                f"monitor-alert-{_text(row.get('id'), str(index))}",
                f"{part} · {alert_type}",
                message,
                _href("Monitoring", return_analysis_id=analysis_id),
                "Monitoring",
                "!",
                [part, alert_type, message, status, "stock", "supplier", "lifecycle", "alert"],
                status,
                "alert",
            )
        )

    decisions = _rows(
        supabase.table("engineering_decisions")
        .select("*")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .limit(limit_per_source)
    )
    for index, row in enumerate(decisions):
        part = _text(row.get("part_number") or row.get("original_part") or row.get("mpn"), "Engineering decision")
        decision = _text(row.get("decision") or row.get("status") or row.get("decision_status"), "Review")
        rationale = _text(row.get("rationale") or row.get("reason") or row.get("notes"), "Open the engineering decision record")
        commands.append(
            _command(
                f"decision-{_text(row.get('id'), str(index))}",
                f"{part} · {decision}",
                rationale,
                _href("Engineering Decisions"),
                "Decisions",
                "◆",
                [part, decision, rationale, "approval", "audit", "review"],
                decision,
                "decision",
            )
        )

    alternatives = _rows(
        supabase.table("alternative_recommendations")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit_per_source)
    )
    for index, row in enumerate(alternatives):
        original = _text(row.get("original_part") or row.get("original_mpn"))
        alternative = _text(row.get("alternative_part") or row.get("alternative_mpn"))
        if not original and not alternative:
            continue
        supplier = _text(row.get("supplier"), "Supplier not recorded")
        score = _text(row.get("recommendation_score") or row.get("score"), "—")
        commands.append(
            _command(
                f"alternative-{_text(row.get('id'), str(index))}",
                f"{original or 'Part'} → {alternative or 'Candidate'}",
                f"{supplier} · Recommendation score {score}",
                _href("Alternative Finder", original_part=original),
                "Alternatives",
                "⇄",
                [original, alternative, supplier, "replacement", "cross reference"],
                "Alternative",
                "alternative",
            )
        )

    # Stable de-duplication protects against duplicate records in historical data.
    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for command in commands:
        key = (_text(command.get("entityType")), _text(command.get("title")).lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(command)
    return deduped

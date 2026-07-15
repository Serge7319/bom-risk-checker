"""Cadivor Milestone 12.3 — AI Monitoring & Action Center."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

import pandas as pd


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    result = str(value).strip()
    return result or default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except Exception:
        return default


def _severity_rank(value: Any) -> int:
    text = _text(value).lower()
    if "critical" in text:
        return 4
    if "high" in text:
        return 3
    if "medium" in text:
        return 2
    if "low" in text:
        return 1
    return 0


def _alert_priority(row: Dict[str, Any]) -> int:
    severity = _severity_rank(row.get("severity"))
    alert_type = _text(row.get("alert_type")).lower()
    message = _text(row.get("alert_message")).lower()

    score = severity * 20
    if "stock" in alert_type or "stock" in message:
        current = _number(row.get("current_value"), 0)
        if current <= 0:
            score += 35
        elif current < 100:
            score += 20
        elif current < 500:
            score += 10
    if "lifecycle" in alert_type or "lifecycle" in message:
        if any(term in message for term in ("obsolete", "eol", "end of life")):
            score += 35
        elif any(term in message for term in ("replacement", "nrnd", "not recommended")):
            score += 25
        else:
            score += 12
    if "price" in alert_type or "price" in message:
        score += 8
    return min(100, score)


def _recommended_action(row: Dict[str, Any]) -> Dict[str, str]:
    alert_type = _text(row.get("alert_type")).lower()
    message = _text(row.get("alert_message")).lower()
    current = _text(row.get("current_value"), "Unknown")
    part = _text(row.get("part_number"), "Component")

    if "stock" in alert_type or "stock" in message:
        if _number(row.get("current_value"), 0) <= 0:
            return {
                "action": f"Resolve the supply gap for {part}",
                "owner": "Procurement",
                "deadline": "Today",
                "impact": "Protects the next build from a material-driven delay.",
                "route": "alternative",
            }
        return {
            "action": f"Review purchasing coverage for {part}",
            "owner": "Supply Chain",
            "deadline": "This week",
            "impact": "Preserves purchasing lead time before inventory becomes critical.",
            "route": "alternative",
        }

    if "lifecycle" in alert_type or "lifecycle" in message:
        if any(term in message for term in ("obsolete", "eol", "end of life")):
            return {
                "action": f"Begin immediate replacement qualification for {part}",
                "owner": "Engineering",
                "deadline": "Before production approval",
                "impact": "Reduces emergency redesign and continuity risk.",
                "route": "alternative",
            }
        return {
            "action": f"Verify the new lifecycle status for {part}",
            "owner": "Component Engineering",
            "deadline": "This week",
            "impact": "Confirms whether redesign or sourcing action is required.",
            "route": "alternative",
        }

    if "price" in alert_type or "price" in message:
        return {
            "action": f"Review cost exposure for {part}",
            "owner": "Procurement",
            "deadline": "Before the next purchase order",
            "impact": "Avoids unplanned BOM-cost growth.",
            "route": "monitoring",
        }

    return {
        "action": f"Review the monitoring change for {part}",
        "owner": "Engineering & Supply Chain",
        "deadline": "This week",
        "impact": "Ensures the change is evaluated before release or purchasing decisions.",
        "route": "monitoring",
    }


def build_monitoring_action_center(
    alert_df: pd.DataFrame,
    monitor_df: pd.DataFrame,
) -> Dict[str, Any]:
    alerts = alert_df.copy() if isinstance(alert_df, pd.DataFrame) else pd.DataFrame()
    history = monitor_df.copy() if isinstance(monitor_df, pd.DataFrame) else pd.DataFrame()

    if alerts.empty:
        prioritized = pd.DataFrame(
            columns=[
                "Part Number",
                "Priority",
                "Severity",
                "Change",
                "Recommended Action",
                "Owner",
                "Deadline",
                "Detected At",
            ]
        )
        action_records: List[Dict[str, Any]] = []
    else:
        records: List[Dict[str, Any]] = []
        for raw in alerts.to_dict("records"):
            action = _recommended_action(raw)
            priority = _alert_priority(raw)
            records.append(
                {
                    "Part Number": _text(raw.get("part_number"), "Unknown"),
                    "Priority": priority,
                    "Severity": _text(raw.get("severity"), "Unknown").title(),
                    "Alert Type": _text(raw.get("alert_type"), "Change detected"),
                    "Change": _text(raw.get("alert_message"), "Monitoring change detected"),
                    "Previous Value": _text(raw.get("previous_value"), "—"),
                    "Current Value": _text(raw.get("current_value"), "—"),
                    "Recommended Action": action["action"],
                    "Owner": action["owner"],
                    "Deadline": action["deadline"],
                    "Expected Impact": action["impact"],
                    "Route": action["route"],
                    "Detected At": _text(raw.get("created_at"), "—"),
                }
            )
        action_records = sorted(
            records,
            key=lambda item: (item["Priority"], _severity_rank(item["Severity"])),
            reverse=True,
        )
        prioritized = pd.DataFrame(action_records)

    active_alerts = len(prioritized)
    immediate_actions = int((prioritized["Priority"] >= 75).sum()) if not prioritized.empty else 0
    engineering_actions = (
        int(prioritized["Owner"].astype(str).str.contains("Engineering", case=False).sum())
        if not prioritized.empty
        else 0
    )
    procurement_actions = (
        int(
            prioritized["Owner"]
            .astype(str)
            .str.contains("Procurement|Supply Chain", case=False, regex=True)
            .sum()
        )
        if not prioritized.empty
        else 0
    )

    if immediate_actions:
        posture = "Immediate Action Required"
        posture_tone = "bad"
        summary = (
            f"{immediate_actions} monitoring change(s) require same-day or pre-production action. "
            "Resolve the highest-priority supply and lifecycle exceptions first."
        )
    elif active_alerts:
        posture = "Controlled Review Required"
        posture_tone = "warn"
        summary = (
            f"{active_alerts} active monitoring change(s) are available for review. "
            "No immediate blocker dominates, but owners and deadlines should be confirmed."
        )
    else:
        posture = "Monitoring Healthy"
        posture_tone = "good"
        summary = (
            "No active monitoring exception is recorded. Continue scheduled stock, lifecycle, "
            "pricing, and supplier checks."
        )

    latest_by_part = pd.DataFrame()
    if not history.empty:
        rename_map = {
            "part_number": "Part Number",
            "supplier": "Supplier",
            "lifecycle_status": "Lifecycle Status",
            "stock": "Available Stock",
            "unit_price": "Unit Price",
            "risk_level": "Risk Level",
            "created_at": "Last Checked",
        }
        latest_by_part = history.rename(columns=rename_map)
        allowed = [
            column
            for column in (
                "Part Number",
                "Supplier",
                "Lifecycle Status",
                "Available Stock",
                "Unit Price",
                "Risk Level",
                "Last Checked",
            )
            if column in latest_by_part.columns
        ]
        latest_by_part = latest_by_part[allowed].copy()
        if "Part Number" in latest_by_part.columns:
            latest_by_part = latest_by_part.drop_duplicates(
                subset=["Part Number"],
                keep="first",
            )

    return {
        "posture": posture,
        "posture_tone": posture_tone,
        "summary": summary,
        "active_alerts": active_alerts,
        "immediate_actions": immediate_actions,
        "engineering_actions": engineering_actions,
        "procurement_actions": procurement_actions,
        "prioritized_alerts": prioritized,
        "action_records": action_records,
        "latest_components": latest_by_part,
    }

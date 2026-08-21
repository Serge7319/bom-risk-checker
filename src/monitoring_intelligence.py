"""Cadivor Sprint 32.0 — Monitoring Intelligence Center."""
from __future__ import annotations

from typing import Any, Dict, List
import pandas as pd


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except Exception:
        return default


def _severity_rank(value: Any) -> int:
    value = _text(value).lower()
    return 4 if "critical" in value else 3 if "high" in value else 2 if "medium" in value else 1 if "low" in value else 0


def _alert_priority(row: Dict[str, Any]) -> int:
    severity = _severity_rank(row.get("severity"))
    alert_type = _text(row.get("alert_type")).lower()
    message = _text(row.get("alert_message")).lower()
    score = severity * 20
    if "stock" in alert_type or "inventory" in alert_type or "stock" in message:
        current = _number(row.get("current_value"), 0)
        score += 35 if current <= 0 else 20 if current < 100 else 10 if current < 500 else 0
    if "lifecycle" in alert_type or "lifecycle" in message:
        score += 35 if any(x in message for x in ("obsolete", "eol", "end of life")) else 25 if any(x in message for x in ("replacement", "nrnd", "not recommended")) else 12
    if "supplier" in alert_type or "lead" in alert_type:
        score += 15
    if "price" in alert_type or "price" in message:
        score += 8
    if _text(row.get("priority")).lower() == "urgent":
        score += 15
    return min(100, score)


def _recommended_action(row: Dict[str, Any]) -> Dict[str, str]:
    alert_type = _text(row.get("alert_type")).lower()
    message = _text(row.get("alert_message")).lower()
    part = _text(row.get("part_number"), "Component")
    if "stock" in alert_type or "inventory" in alert_type or "stock" in message:
        if _number(row.get("current_value"), 0) <= 0:
            return {"action": f"Qualify an alternate source or replacement for {part}", "owner": "Procurement", "deadline": "Today", "impact": "Protects the next build from a material-driven delay.", "route": "alternative"}
        return {"action": f"Review purchasing coverage for {part}", "owner": "Supply Chain", "deadline": "This week", "impact": "Preserves purchasing lead time before inventory becomes critical.", "route": "alternative"}
    if "lifecycle" in alert_type or "lifecycle" in message:
        if any(x in message for x in ("obsolete", "eol", "end of life")):
            return {"action": f"Begin immediate replacement qualification for {part}", "owner": "Engineering", "deadline": "Before production approval", "impact": "Reduces emergency redesign and continuity risk.", "route": "alternative"}
        return {"action": f"Verify the lifecycle status and second-source strategy for {part}", "owner": "Component Engineering", "deadline": "This week", "impact": "Confirms whether redesign or sourcing action is required.", "route": "alternative"}
    if "price" in alert_type:
        return {"action": f"Review cost exposure for {part}", "owner": "Procurement", "deadline": "Before the next purchase order", "impact": "Avoids unplanned BOM-cost growth.", "route": "monitoring"}
    if "supplier" in alert_type or "lead" in alert_type:
        return {"action": f"Validate supplier coverage for {part}", "owner": "Supply Chain", "deadline": "This week", "impact": "Reduces single-source and lead-time exposure.", "route": "monitoring"}
    return {"action": f"Review the monitoring change for {part}", "owner": "Engineering & Supply Chain", "deadline": "This week", "impact": "Ensures the change is evaluated before release or purchasing decisions.", "route": "monitoring"}


def build_monitoring_action_center(alert_df: pd.DataFrame, monitor_df: pd.DataFrame) -> Dict[str, Any]:
    alerts = alert_df.copy() if isinstance(alert_df, pd.DataFrame) else pd.DataFrame()
    history = monitor_df.copy() if isinstance(monitor_df, pd.DataFrame) else pd.DataFrame()
    records: List[Dict[str, Any]] = []
    seen_alerts = set()
    for raw in alerts.to_dict("records") if not alerts.empty else []:
        alert_type = _text(raw.get("alert_type")).casefold()
        alert_message = _text(raw.get("alert_message")).casefold()
        if "test alert" in alert_type or "scheduled monitoring test alert" in alert_message:
            continue
        alert_identity = (
            _text(raw.get("part_number")).casefold(),
            _text(raw.get("analysis_id")).casefold(),
            alert_type,
            alert_message,
            _text(raw.get("workflow_status"), "Open").casefold(),
        )
        if alert_identity in seen_alerts:
            continue
        seen_alerts.add(alert_identity)
        action = _recommended_action(raw)
        status = _text(raw.get("workflow_status"), "Open").title()
        records.append({
            "Alert ID": _text(raw.get("id")), "Part Number": _text(raw.get("part_number"), "Unknown"),
            "Analysis ID": _text(raw.get("analysis_id")), "Priority Score": _alert_priority(raw),
            "Priority": _text(raw.get("priority"), "High" if _alert_priority(raw) >= 70 else "Normal").title(),
            "Severity": _text(raw.get("severity"), "Unknown").title(), "Alert Type": _text(raw.get("alert_type"), "Change detected"),
            "Change": _text(raw.get("alert_message"), "Monitoring change detected"), "Previous Value": _text(raw.get("previous_value"), "—"),
            "Current Value": _text(raw.get("current_value"), "—"), "Recommended Action": action["action"],
            "Owner": _text(raw.get("assigned_to"), action["owner"]), "Due Date": _text(raw.get("due_date"), action["deadline"]),
            "Expected Impact": action["impact"], "Route": action["route"], "Status": status,
            "Note": _text(raw.get("review_note")), "Detected At": _text(raw.get("created_at"), "—"),
            "Updated At": _text(raw.get("updated_at"), "—"),
        })
    records.sort(key=lambda x: (x["Status"] not in {"Open", "In Review", "Reopened"}, -x["Priority Score"]))
    prioritized = pd.DataFrame(records)
    active = prioritized[~prioritized["Status"].isin(["Resolved", "Dismissed"])] if not prioritized.empty else prioritized

    latest = pd.DataFrame()
    if not history.empty:
        latest = history.rename(columns={"part_number":"Part Number","supplier":"Supplier","lifecycle_status":"Lifecycle Status","stock":"Available Stock","unit_price":"Unit Price","risk_level":"Risk Level","created_at":"Last Checked","analysis_id":"Analysis ID"})
        cols = [c for c in ("Part Number","Supplier","Lifecycle Status","Available Stock","Unit Price","Risk Level","Last Checked","Analysis ID") if c in latest.columns]
        latest = latest[cols].copy()
        if "Part Number" in latest.columns:
            latest = latest.drop_duplicates("Part Number", keep="first")

    active_count = len(active)
    immediate = int((active["Priority Score"] >= 75).sum()) if not active.empty else 0
    lifecycle = int(active["Alert Type"].astype(str).str.contains("lifecycle|eol|obsolete", case=False, regex=True).sum()) if not active.empty else 0
    inventory = int(active["Alert Type"].astype(str).str.contains("stock|inventory", case=False, regex=True).sum()) if not active.empty else 0
    supplier = int(active["Alert Type"].astype(str).str.contains("supplier|lead", case=False, regex=True).sum()) if not active.empty else 0
    needs_review = int(active["Status"].isin(["Open", "Reopened"]).sum()) if not active.empty else 0
    monitored = int(latest["Part Number"].nunique()) if not latest.empty and "Part Number" in latest else 0

    if immediate:
        posture, tone = "Immediate Action Required", "bad"
        exception_label = "exception requires" if immediate == 1 else "exceptions require"
        summary = (
            f"{immediate} monitoring {exception_label} urgent engineering or sourcing action. "
            "Address lifecycle and inventory exposure first."
        )
    elif active_count:
        posture, tone = "Controlled Review Required", "warn"
        change_label = "change is" if active_count == 1 else "changes are"
        summary = (
            f"{active_count} active {change_label} being tracked. Confirm owners, due dates, "
            "and next actions before release or purchasing decisions."
        )
    else:
        posture, tone = "Monitoring Healthy", "good"
        summary = "No unresolved monitoring exception is recorded. Continue scheduled lifecycle, inventory, price, and supplier checks."

    return {"posture":posture,"posture_tone":tone,"summary":summary,"active_alerts":active_count,"immediate_actions":immediate,
            "lifecycle_alerts":lifecycle,"inventory_alerts":inventory,"supplier_alerts":supplier,"needs_review":needs_review,
            "monitored_components":monitored,"prioritized_alerts":prioritized,"active_queue":active,"action_records":records,"latest_components":latest}

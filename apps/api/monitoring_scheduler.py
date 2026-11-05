"""On-demand / cron-hook monitoring refresh for the migration API.

Real alert email and live supplier refresh stay disabled unless explicitly
enabled with verified credentials. The schedule endpoint records a refresh
tick and re-derives alerts from saved analyses using the mock/synthetic path.
"""
from __future__ import annotations

import os
from typing import Any

from apps.api import migration_tools
from apps.api import monitoring_store


def scheduler_enabled() -> bool:
    return (os.environ.get("CADIVOR_MONITORING_SCHEDULER_ENABLED") or "").strip() == "1"


def cron_token_configured() -> bool:
    return bool((os.environ.get("CADIVOR_MONITORING_CRON_TOKEN") or "").strip())


def authorize_cron(header_token: str | None) -> bool:
    expected = (os.environ.get("CADIVOR_MONITORING_CRON_TOKEN") or "").strip()
    if not expected:
        return False
    return (header_token or "").strip() == expected


def run_workspace_refresh(workspace_id: str, *, analysis_id: str | None = None) -> dict[str, Any]:
    payload = migration_tools.monitoring_payload(
        workspace_id=workspace_id, analysis_id=analysis_id
    )
    prefs = monitoring_store.get_preferences(workspace_id)
    delivered = []
    if prefs.get("email_alerts") and monitoring_store.email_delivery_enabled():
        for alert in payload.get("alerts") or []:
            delivered.append(monitoring_store.deliver_alert_email(workspace_id, alert))
    return {
        "ok": True,
        "workspace_id": workspace_id,
        "scheduler_enabled": scheduler_enabled(),
        "email_delivery_enabled": monitoring_store.email_delivery_enabled(),
        "alert_count": len(payload.get("alerts") or []),
        "refresh": payload.get("refresh"),
        "notifications": delivered,
        "gap": (
            None
            if scheduler_enabled()
            else "Scheduler flag off; this was an on-demand refresh only."
        ),
    }

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




def scheduler_readiness() -> dict[str, Any]:
    """Operational scheduler status — flag alone is not Ready.

    Ready requires the enable flag, a cron token, and a verifiable schedule
    attachment. External cron attachment is not introspectable here, so a
    fully configured process reports Partial rather than inventing Ready.
    """
    enabled = scheduler_enabled()
    cron = cron_token_configured()
    if not enabled:
        return {
            "status": "not_connected",
            "enabled": False,
            "cron_token_configured": cron,
        }
    if not cron:
        return {
            "status": "partial",
            "enabled": True,
            "cron_token_configured": False,
        }
    return {
        "status": "partial",
        "enabled": True,
        "cron_token_configured": True,
        "detail": "Cron token is configured; external schedule attachment is not verified.",
    }

def authorize_cron(header_token: str | None) -> bool:
    expected = (os.environ.get("CADIVOR_MONITORING_CRON_TOKEN") or "").strip()
    if not expected:
        return False
    return (header_token or "").strip() == expected


def run_workspace_refresh(
    workspace_id: str,
    *,
    analysis_id: str | None = None,
    part_number: str | None = None,
    portfolio: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Explicit data refresh only — never sends email.

    Email delivery requires the separate, clearly labeled
    ``POST /tools/monitoring/notify`` action. ``dry_run=True`` derives the
    scoped view, writes nothing, and never reaches email. A cron caller that
    supplies no ``analysis_id`` must request ``portfolio=True`` explicitly.
    """
    part = str(part_number or "").strip() or None
    if dry_run:
        if portfolio:
            raise ValueError("dry_run supports a single analysis_id scope")
        payload = migration_tools.monitoring_payload(
            workspace_id=workspace_id, analysis_id=analysis_id
        )
        alerts = list(payload.get("alerts") or [])
        if part:
            alerts = [
                a
                for a in alerts
                if str(a.get("part_number") or "").casefold() == part.casefold()
            ]
        return {
            "ok": True,
            "dry_run": True,
            "workspace_id": workspace_id,
            "scope": "part" if part else "analysis",
            "analysis_id": payload.get("analysis_id") or analysis_id,
            "part_number": part,
            "scheduler_enabled": scheduler_enabled(),
            "email_delivery_enabled": monitoring_store.email_delivery_enabled(),
            "alert_count": len(alerts),
            "alerts": alerts,
            "refresh": None,
            "notifications": [],
            "email_sent": False,
            "persisted": False,
            "gap": (
                "Dry run: nothing was saved and no notifications were attempted. "
                "Email is never sent from refresh; use the explicit notify action."
            ),
        }
    payload = migration_tools.monitoring_refresh_payload(
        workspace_id=workspace_id,
        analysis_id=analysis_id,
        part_number=part,
        portfolio=portfolio,
    )
    return {
        "ok": True,
        "dry_run": False,
        "persisted": True,
        "workspace_id": workspace_id,
        "scope": payload.get("scope"),
        "scope_label": payload.get("scope_label"),
        "analysis_id": payload.get("analysis_id"),
        "part_number": payload.get("part_number"),
        "scheduler_enabled": scheduler_enabled(),
        "email_delivery_enabled": monitoring_store.email_delivery_enabled(),
        "alert_count": payload.get("alert_count", len(payload.get("alerts") or [])),
        "alerts": payload.get("alerts") or [],
        "refresh": payload.get("refresh"),
        "live_supplier_refresh": False,
        "notifications": [],
        "email_sent": False,
        "gap": (
            "Data refresh saved alerts from the selected scope. "
            "Email was not sent — use the explicit Notify action when delivery is enabled. "
            + (
                ""
                if scheduler_enabled()
                else "Scheduler flag off; this was an on-demand refresh only."
            )
        ).strip(),
    }

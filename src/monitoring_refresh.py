"""On-demand supplier refreshes for an already monitored BOM component."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from src.monitoring_engine import (
    build_updated_monitor_snapshot,
    detect_monitor_alerts,
    save_monitor_alerts,
    save_monitor_history_with_diagnostic,
    scope_monitoring_query,
)
from src.normalizer import normalize_part_number


def refresh_monitored_part(
    supabase: Any,
    *,
    user_id: str,
    workspace_id: str | None,
    part_number: str,
    analysis_id: str | None = None,
    supplier_lookup: Callable[[str], dict] | None = None,
) -> dict[str, Any]:
    """Poll configured distributor APIs for one scoped, existing monitoring baseline.

    The operation is intentionally user-triggered and component-scoped. It never
    emails, starts monitoring, changes another component, or trusts a ranked
    supplier response unless its manufacturer MPN exactly matches the request.
    """
    uid = str(user_id or "").strip()
    workspace = str(workspace_id or "").strip()
    requested = str(part_number or "").strip()
    analysis = str(analysis_id or "").strip()
    requested_key = normalize_part_number(requested)
    if not uid or not requested_key:
        return {"status": "invalid_scope"}

    query = scope_monitoring_query(
        supabase.table("part_monitor_history").select("*"),
        user_id=uid,
        workspace_id=workspace or None,
        analysis_id=analysis or None,
    )
    response = (
        query.eq("part_number", requested)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = getattr(response, "data", None) or []
    previous = next(
        (
            row for row in rows
            if isinstance(row, dict)
            and normalize_part_number(str(row.get("part_number") or "")) == requested_key
        ),
        None,
    )
    if not previous:
        return {"status": "no_baseline"}

    lookup = supplier_lookup
    if lookup is None:
        from integrations.supplier_aggregator import get_best_part_data

        lookup = get_best_part_data
    try:
        fresh = lookup(requested) or {}
    except Exception:
        # Do not put provider exception text, credentials, or request details in
        # the UI. The last saved snapshot remains the source of truth.
        return {"status": "supplier_unavailable"}

    returned = str(fresh.get("manufacturer_part_number") or "").strip()
    if (
        not fresh.get("supplier_data_verified")
        or normalize_part_number(returned) != requested_key
    ):
        return {"status": "exact_supplier_match_unavailable"}

    snapshot = build_updated_monitor_snapshot(
        uid,
        requested,
        previous,
        fresh,
    )
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    alerts, messages = detect_monitor_alerts(
        uid,
        snapshot.get("analysis_id"),
        requested,
        previous,
        snapshot,
        workspace_id=snapshot.get("workspace_id"),
    )

    saved, diagnostic = save_monitor_history_with_diagnostic(supabase, [snapshot])
    if not saved:
        return {
            "status": "snapshot_save_failed",
            "diagnostic": diagnostic,
        }

    alerts_saved = save_monitor_alerts(supabase, alerts) if alerts else True
    return {
        "status": "updated" if alerts_saved else "alert_save_failed",
        "checked_at": checked_at,
        "part_number": requested,
        "supplier": str(fresh.get("source") or "").strip(),
        "sources_available": str(fresh.get("sources_available") or "").strip(),
        "provider_health": dict(fresh.get("provider_health") or {}),
        "alert_count": len(alerts),
        "change_messages": list(messages),
        "diagnostic": "" if alerts_saved else "The supplier snapshot was saved, but its change alert could not be saved.",
    }

"""Durable monitoring alerts and notification preferences.

Uses the dedicated migration Postgres when CADIVOR_MIGRATION_DATABASE_URL is set;
otherwise an ephemeral file/memory store for local tests. Alert email delivery
uses an injectable sink; production delivery stays disabled until
CADIVOR_MONITORING_EMAIL_ENABLED=1 with a verified transport. Default sink
records payloads in-memory for tests.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from apps.api.workspace_store import allow_ephemeral_file_store, get_store, migration_database_url


_lock = threading.Lock()
_EMAIL_SINK: list[dict[str, Any]] = []
_DEFAULT_PREFS = {
    "email_alerts": False,
    "weekly_digest": False,
    "lifecycle": True,
    "availability": True,
    "risk": True,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def email_delivery_enabled() -> bool:
    return (os.environ.get("CADIVOR_MONITORING_EMAIL_ENABLED") or "").strip() == "1"


def _configured_email_transport() -> bool:
    """True when Resend (or equivalent) can actually submit mail."""
    try:
        from src.email_delivery import email_delivery_configured

        return bool(email_delivery_configured())
    except Exception:  # noqa: BLE001
        return False


def email_transport_ready() -> bool:
    """Operational delivery: flag on and a wired transport (or test sink)."""
    if not email_delivery_enabled():
        return False
    # Injectable sink used by unit tests counts as an operational transport.
    if getattr(deliver_alert_email, "_default_sink", None) is not None:
        return True
    return _configured_email_transport()


def monitoring_email_readiness() -> dict[str, Any]:
    enabled = email_delivery_enabled()
    transport = email_transport_ready()
    if not enabled:
        return {
            "status": "not_connected",
            "enabled": False,
            "transport_ready": False,
            "missing_requirements": ["monitoring email delivery flag"],
        }
    if transport:
        return {
            "status": "ready",
            "enabled": True,
            "transport_ready": True,
            "missing_requirements": [],
        }
    # Flag on but deliver_alert_email would return no_sink_configured.
    return {
        "status": "not_connected",
        "enabled": True,
        "transport_ready": False,
        "missing_requirements": ["Resend API key and verified sender address"],
    }


def set_default_email_sink(sink: Callable[[dict[str, Any]], None] | None) -> None:
    """Install a process-default sink for monitoring alert delivery (tests)."""
    deliver_alert_email._default_sink = sink  # type: ignore[attr-defined]


def reset_email_sink_for_tests() -> None:
    with _lock:
        _EMAIL_SINK.clear()
    set_default_email_sink(None)


def recorded_emails() -> list[dict[str, Any]]:
    with _lock:
        return list(_EMAIL_SINK)


def _use_postgres() -> bool:
    return bool(migration_database_url())


def _pg_connect():
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(migration_database_url(), row_factory=dict_row)


def _file_path() -> Path | None:
    if not allow_ephemeral_file_store():
        return None
    store = get_store()
    base = getattr(store, "path", None)
    if base is None:
        return None
    return Path(base).with_name("monitoring_state.json")


def _load_state() -> dict[str, Any]:
    path = _file_path()
    if path and path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
    else:
        state = getattr(_load_state, "_mem", {"workspaces": {}})  # type: ignore[attr-defined]
    state.setdefault("workspaces", {})
    state.setdefault("scheduled_runs", {})
    state.setdefault("workspace_monitoring_capacities", {})
    return state


def _save_state(state: dict[str, Any]) -> None:
    path = _file_path()
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        return
    setattr(_load_state, "_mem", state)


def reset_monitoring_store_for_tests() -> None:
    with _lock:
        setattr(_load_state, "_mem", {"workspaces": {}, "scheduled_runs": {}})
        path = _file_path()
        if path and path.exists():
            path.unlink()
        _EMAIL_SINK.clear()
        if _use_postgres():
            with _pg_connect() as conn:
                conn.execute("DELETE FROM migration_monitoring_alerts")
                conn.execute("DELETE FROM migration_notification_preferences")
                conn.execute("DELETE FROM migration_monitoring_member_preferences")
                conn.execute("DELETE FROM migration_monitoring_snapshots")
                conn.execute("DELETE FROM migration_monitoring_email_deliveries")
                conn.execute("DELETE FROM migration_monitoring_slack_deliveries")
                conn.execute("DELETE FROM migration_monitoring_digest_deliveries")
                conn.execute("DELETE FROM migration_monitoring_refresh_history")
                conn.execute("DELETE FROM migration_monitoring_scheduled_runs")
                conn.execute("DELETE FROM migration_workspace_monitoring_capacity")
                conn.commit()


def _scheduled_run_row(row: Any) -> dict[str, Any]:
    if not row:
        return {}
    item = dict(row)
    for key in ("started_at", "updated_at", "finished_at"):
        value = item.get(key)
        if value is not None and hasattr(value, "isoformat"):
            item[key] = value.isoformat()
    result = item.get("result")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            result = {}
    item["result"] = result if isinstance(result, dict) else {}
    return item


def begin_scheduled_run(run_id: str) -> dict[str, Any]:
    """Atomically claim the single active scheduled cycle and persist its ID."""
    rid = str(run_id or "").strip()
    if not rid or len(rid) > 100:
        raise ValueError("A valid monitoring run ID is required")
    if _use_postgres():
        with _pg_connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                ("cadivor_monitoring_scheduled_runs",),
            )
            conn.execute(
                """
                UPDATE migration_monitoring_scheduled_runs
                   SET status = 'failed', updated_at = NOW(), finished_at = NOW(),
                       error = 'The prior run stopped reporting progress.'
                 WHERE status = 'running'
                   AND updated_at < NOW() - INTERVAL '60 minutes'
                """
            )
            existing = conn.execute(
                "SELECT * FROM migration_monitoring_scheduled_runs WHERE id = %s",
                (rid,),
            ).fetchone()
            if existing:
                return {"created": False, **_scheduled_run_row(existing)}
            active = conn.execute(
                "SELECT * FROM migration_monitoring_scheduled_runs WHERE status = 'running' LIMIT 1"
            ).fetchone()
            if active:
                return {"created": False, "busy": True, **_scheduled_run_row(active)}
            row = conn.execute(
                """
                INSERT INTO migration_monitoring_scheduled_runs (id, status)
                VALUES (%s, 'running')
                RETURNING *
                """,
                (rid,),
            ).fetchone()
        return {"created": True, **_scheduled_run_row(row)}

    with _lock:
        state = _load_state()
        runs = state.setdefault("scheduled_runs", {})
        existing = runs.get(rid)
        if existing:
            return {"created": False, **dict(existing)}
        now = utc_now()
        stale_before = datetime.now(timezone.utc) - timedelta(minutes=60)
        for previous in runs.values():
            if previous.get("status") != "running":
                continue
            try:
                updated = datetime.fromisoformat(str(previous.get("updated_at") or ""))
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
            except ValueError:
                updated = stale_before - timedelta(seconds=1)
            if updated < stale_before:
                previous.update({
                    "status": "failed",
                    "updated_at": now,
                    "finished_at": now,
                    "error": "The prior run stopped reporting progress.",
                })
        active = next((row for row in runs.values() if row.get("status") == "running"), None)
        if active:
            return {"created": False, "busy": True, **dict(active)}
        record = {
            "id": rid,
            "status": "running",
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
            "result": {},
            "error": None,
        }
        runs[rid] = record
        _save_state(state)
        return {"created": True, **dict(record)}


def get_scheduled_run(run_id: str) -> dict[str, Any] | None:
    rid = str(run_id or "").strip()
    if not rid:
        return None
    if _use_postgres():
        with _pg_connect() as conn:
            row = conn.execute(
                "SELECT * FROM migration_monitoring_scheduled_runs WHERE id = %s",
                (rid,),
            ).fetchone()
        return _scheduled_run_row(row) if row else None
    with _lock:
        row = _load_state().get("scheduled_runs", {}).get(rid)
        return dict(row) if row else None


def touch_scheduled_run(run_id: str) -> None:
    rid = str(run_id or "").strip()
    if not rid:
        return
    now = utc_now()
    if _use_postgres():
        with _pg_connect() as conn:
            conn.execute(
                "UPDATE migration_monitoring_scheduled_runs SET updated_at = NOW() WHERE id = %s AND status = 'running'",
                (rid,),
            )
            conn.commit()
        return
    with _lock:
        state = _load_state()
        row = state.get("scheduled_runs", {}).get(rid)
        if row and row.get("status") == "running":
            row["updated_at"] = now
            _save_state(state)


def finish_scheduled_run(
    run_id: str,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    rid = str(run_id or "").strip()
    if not rid:
        return
    if status not in {"succeeded", "completed_with_failures", "failed"}:
        raise ValueError("Invalid scheduled monitoring terminal status")
    payload = result if isinstance(result, dict) else {}
    if _use_postgres():
        with _pg_connect() as conn:
            conn.execute(
                """
                UPDATE migration_monitoring_scheduled_runs
                   SET status = %s, updated_at = NOW(), finished_at = NOW(),
                       result = %s::jsonb, error = %s
                 WHERE id = %s AND status = 'running'
                """,
                (status, json.dumps(payload), str(error or "")[:1000] or None, rid),
            )
            conn.commit()
        return
    with _lock:
        state = _load_state()
        row = state.get("scheduled_runs", {}).get(rid)
        if row and row.get("status") == "running":
            now = utc_now()
            row.update({
                "status": status,
                "updated_at": now,
                "finished_at": now,
                "result": payload,
                "error": str(error or "")[:1000] or None,
            })
            _save_state(state)


def _ws(state: dict[str, Any], workspace_id: str) -> dict[str, Any]:
    workspaces = state.setdefault("workspaces", {})
    return workspaces.setdefault(
        workspace_id,
        {
            "alerts": [],
            "preferences": dict(_DEFAULT_PREFS),
            "user_preferences": {},
            "snapshots": {},
            "email_deliveries": {},
            "slack_deliveries": {},
            "refresh_history": [],
        },
    )


def delete_analysis_scopes(workspace_id: str, analysis_ids: list[str]) -> None:
    """Remove monitoring state tied to reports that a user deleted."""
    wid = str(workspace_id or "").strip()
    aids = sorted({str(aid or "").strip() for aid in analysis_ids if str(aid or "").strip()})
    if not wid or not aids:
        return
    if _use_postgres():
        with _pg_connect() as conn:
            alert_rows = conn.execute(
                """
                SELECT id FROM migration_monitoring_alerts
                WHERE workspace_id = %s AND analysis_id = ANY(%s)
                """,
                (wid, aids),
            ).fetchall()
            alert_ids = [str(row["id"]) for row in alert_rows]
            if alert_ids:
                conn.execute(
                    "DELETE FROM migration_monitoring_email_deliveries WHERE workspace_id = %s AND alert_id = ANY(%s)",
                    (wid, alert_ids),
                )
                conn.execute(
                    "DELETE FROM migration_monitoring_slack_deliveries WHERE workspace_id = %s AND alert_id = ANY(%s)",
                    (wid, alert_ids),
                )
                conn.execute(
                    "DELETE FROM migration_monitoring_alerts WHERE workspace_id = %s AND id = ANY(%s)",
                    (wid, alert_ids),
                )
            conn.execute(
                "DELETE FROM migration_monitoring_snapshots WHERE workspace_id = %s AND analysis_id = ANY(%s)",
                (wid, aids),
            )
            conn.execute(
                "DELETE FROM migration_monitoring_refresh_history WHERE workspace_id = %s AND analysis_id = ANY(%s)",
                (wid, aids),
            )
            conn.commit()
        return
    with _lock:
        state = _load_state()
        bucket = _ws(state, wid)
        aid_set = set(aids)
        removed_alert_ids = {
            str(row.get("id") or "")
            for row in bucket.get("alerts", [])
            if str(row.get("analysis_id") or "") in aid_set
        }
        bucket["alerts"] = [
            row for row in bucket.get("alerts", [])
            if str(row.get("analysis_id") or "") not in aid_set
        ]
        snapshots = bucket.setdefault("snapshots", {})
        for aid in aids:
            snapshots.pop(aid, None)
        bucket["refresh_history"] = [
            row for row in bucket.get("refresh_history", [])
            if str(row.get("analysis_id") or "") not in aid_set
        ]
        deliveries = bucket.setdefault("email_deliveries", {})
        for key, row in list(deliveries.items()):
            if str(row.get("alert_id") or "") in removed_alert_ids:
                deliveries.pop(key, None)
        slack_deliveries = bucket.setdefault("slack_deliveries", {})
        for key, row in list(slack_deliveries.items()):
            if str(row.get("alert_id") or "") in removed_alert_ids:
                slack_deliveries.pop(key, None)
        _save_state(state)


def get_preferences(workspace_id: str) -> dict[str, Any]:
    if _use_postgres():
        with _pg_connect() as conn:
            row = conn.execute(
                "SELECT email_alerts, weekly_digest, lifecycle, availability, risk FROM migration_notification_preferences WHERE workspace_id = %s",
                (workspace_id,),
            ).fetchone()
        prefs = dict(_DEFAULT_PREFS) if not row else {
            "email_alerts": bool(row["email_alerts"]),
            "weekly_digest": bool(row["weekly_digest"]),
            "lifecycle": bool(row["lifecycle"]),
            "availability": bool(row["availability"]),
            "risk": bool(row["risk"]),
        }
    else:
        with _lock:
            state = _load_state()
            prefs = dict(_ws(state, workspace_id)["preferences"])
    prefs["email_delivery_enabled"] = email_delivery_enabled()
    prefs["delivery_sink"] = (
        "mock-record" if not email_delivery_enabled() else "configured-transport"
    )
    return prefs


def get_workspace_slack_integration(workspace_id: str) -> dict[str, Any]:
    """Return connection status without exposing the encrypted or raw URL."""
    if _use_postgres():
        with _pg_connect() as conn:
            row = conn.execute(
                "SELECT slack_alerts, slack_webhook_ciphertext FROM migration_notification_preferences WHERE workspace_id = %s",
                (str(workspace_id or "").strip(),),
            ).fetchone()
        enabled = bool(row and row["slack_alerts"])
        configured = bool(row and row["slack_webhook_ciphertext"])
    else:
        with _lock:
            prefs = _ws(_load_state(), str(workspace_id or "").strip())["preferences"]
            enabled = bool(prefs.get("slack_alerts"))
            configured = bool(prefs.get("slack_webhook_ciphertext"))
    try:
        from apps.api.slack_notifications import encryption_key_configured

        key_ready = encryption_key_configured()
    except Exception:  # noqa: BLE001
        key_ready = False
    return {
        "enabled": enabled and configured,
        "configured": configured,
        "encryption_ready": key_ready,
    }


def set_workspace_slack_integration(
    workspace_id: str,
    *,
    enabled: bool,
    webhook_ciphertext: str | None,
    replace_webhook: bool,
) -> dict[str, Any]:
    """Update a workspace Slack connection without returning secret material."""
    wid = str(workspace_id or "").strip()
    if not wid:
        raise ValueError("workspace_id is required")
    if _use_postgres():
        with _pg_connect() as conn:
            if replace_webhook:
                conn.execute(
                    """
                    INSERT INTO migration_notification_preferences
                      (workspace_id, slack_alerts, slack_webhook_ciphertext, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (workspace_id) DO UPDATE SET
                      slack_alerts = EXCLUDED.slack_alerts,
                      slack_webhook_ciphertext = EXCLUDED.slack_webhook_ciphertext,
                      updated_at = NOW()
                    """,
                    (wid, bool(enabled), webhook_ciphertext),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO migration_notification_preferences
                      (workspace_id, slack_alerts, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (workspace_id) DO UPDATE SET
                      slack_alerts = EXCLUDED.slack_alerts,
                      updated_at = NOW()
                    """,
                    (wid, bool(enabled)),
                )
            conn.commit()
    else:
        with _lock:
            state = _load_state()
            prefs = _ws(state, wid)["preferences"]
            prefs["slack_alerts"] = bool(enabled)
            if replace_webhook:
                prefs["slack_webhook_ciphertext"] = webhook_ciphertext
            _save_state(state)
    return get_workspace_slack_integration(wid)


def workspace_slack_ciphertext(workspace_id: str) -> str:
    if _use_postgres():
        with _pg_connect() as conn:
            row = conn.execute(
                "SELECT slack_webhook_ciphertext FROM migration_notification_preferences WHERE workspace_id = %s AND slack_alerts = TRUE",
                (str(workspace_id or "").strip(),),
            ).fetchone()
        return str(row["slack_webhook_ciphertext"] or "") if row else ""
    with _lock:
        prefs = _ws(_load_state(), str(workspace_id or "").strip())["preferences"]
        return str(prefs.get("slack_webhook_ciphertext") or "") if prefs.get("slack_alerts") else ""


def list_retryable_slack_alert_ids(workspace_id: str) -> list[str]:
    wid = str(workspace_id or "").strip()
    if not wid:
        return []
    if _use_postgres():
        with _pg_connect() as conn:
            rows = conn.execute(
                """
                SELECT alert_id FROM migration_monitoring_slack_deliveries
                 WHERE workspace_id = %s AND status = 'sending'
                   AND (lease_until IS NULL OR lease_until < NOW())
                """,
                (wid,),
            ).fetchall()
        return [str(row["alert_id"]) for row in rows]
    now = datetime.now(timezone.utc)
    with _lock:
        deliveries = _ws(_load_state(), wid).setdefault("slack_deliveries", {})
        ids: list[str] = []
        for row in deliveries.values():
            if row.get("status") != "sending":
                continue
            try:
                lease = datetime.fromisoformat(str(row.get("lease_until") or "").replace("Z", "+00:00"))
                if lease.tzinfo is None:
                    lease = lease.replace(tzinfo=timezone.utc)
            except ValueError:
                lease = now
            if lease <= now:
                ids.append(str(row.get("alert_id") or ""))
        return [alert_id for alert_id in ids if alert_id]


def claim_scheduled_slack_alert(workspace_id: str, alert_id: str) -> bool:
    wid = str(workspace_id or "").strip()
    aid = str(alert_id or "").strip()
    if not wid or not aid:
        return False
    if _use_postgres():
        with _pg_connect() as conn:
            row = conn.execute(
                """
                INSERT INTO migration_monitoring_slack_deliveries
                  (workspace_id, alert_id, status, lease_until, updated_at)
                VALUES (%s, %s, 'sending', NOW() + INTERVAL '5 minutes', NOW())
                ON CONFLICT (workspace_id, alert_id) DO UPDATE SET
                  status = 'sending', lease_until = NOW() + INTERVAL '5 minutes',
                  updated_at = NOW()
                WHERE migration_monitoring_slack_deliveries.status <> 'sent'
                  AND (migration_monitoring_slack_deliveries.lease_until IS NULL
                       OR migration_monitoring_slack_deliveries.lease_until < NOW())
                RETURNING 1 AS claimed
                """,
                (wid, aid),
            ).fetchone()
            conn.commit()
        return bool(row)
    now = datetime.now(timezone.utc)
    key = _email_delivery_key(wid, "slack", aid)
    with _lock:
        state = _load_state()
        deliveries = _ws(state, wid).setdefault("slack_deliveries", {})
        prior = deliveries.get(key) or {}
        if prior.get("status") == "sent":
            return False
        if prior.get("status") == "sending":
            try:
                lease = datetime.fromisoformat(str(prior.get("lease_until") or "").replace("Z", "+00:00"))
                if lease.tzinfo is None:
                    lease = lease.replace(tzinfo=timezone.utc)
            except ValueError:
                lease = now
            if lease > now:
                return False
        deliveries[key] = {
            "workspace_id": wid,
            "alert_id": aid,
            "status": "sending",
            "lease_until": (now + timedelta(minutes=5)).isoformat(),
        }
        _save_state(state)
    return True


def finish_scheduled_slack_alert(
    workspace_id: str, alert_id: str, *, delivered: bool
) -> None:
    wid = str(workspace_id or "").strip()
    aid = str(alert_id or "").strip()
    if not wid or not aid:
        return
    if _use_postgres():
        with _pg_connect() as conn:
            if delivered:
                conn.execute(
                    """
                    UPDATE migration_monitoring_slack_deliveries
                       SET status = 'sent', lease_until = NULL, updated_at = NOW()
                     WHERE workspace_id = %s AND alert_id = %s
                    """,
                    (wid, aid),
                )
            else:
                conn.execute(
                    """
                    UPDATE migration_monitoring_slack_deliveries
                       SET lease_until = NOW() - INTERVAL '1 second', updated_at = NOW()
                     WHERE workspace_id = %s AND alert_id = %s AND status = 'sending'
                    """,
                    (wid, aid),
                )
            conn.commit()
        return
    key = _email_delivery_key(wid, "slack", aid)
    with _lock:
        state = _load_state()
        deliveries = _ws(state, wid).setdefault("slack_deliveries", {})
        prior = deliveries.get(key) or {}
        if not prior:
            return
        if delivered:
            prior.update({"status": "sent", "lease_until": None, "sent_at": utc_now()})
        else:
            prior["lease_until"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        deliveries[key] = prior
        _save_state(state)


def clear_scheduled_slack_alert_delivery(workspace_id: str, alert_id: str) -> None:
    wid = str(workspace_id or "").strip()
    aid = str(alert_id or "").strip()
    if not wid or not aid:
        return
    if _use_postgres():
        with _pg_connect() as conn:
            conn.execute(
                "DELETE FROM migration_monitoring_slack_deliveries WHERE workspace_id = %s AND alert_id = %s",
                (wid, aid),
            )
            conn.commit()
        return
    key = _email_delivery_key(wid, "slack", aid)
    with _lock:
        state = _load_state()
        _ws(state, wid).setdefault("slack_deliveries", {}).pop(key, None)
        _save_state(state)


def get_workspace_monitoring_capacity(workspace_id: str) -> int | None:
    """Return an enforced workspace capacity; None preserves legacy/unlimited behavior."""
    wid = str(workspace_id or "").strip()
    if _use_postgres():
        with _pg_connect() as conn:
            row = conn.execute(
                "SELECT max_parts FROM migration_workspace_monitoring_capacity WHERE workspace_id = %s",
                (wid,),
            ).fetchone()
        return None if not row or row["max_parts"] is None else max(0, int(row["max_parts"]))
    with _lock:
        caps = _load_state().setdefault("workspace_monitoring_capacities", {})
        value = caps.get(wid)
        return None if value is None else max(0, int(value))


def set_workspace_monitoring_capacity(workspace_id: str, max_parts: int | None) -> None:
    wid = str(workspace_id or "").strip()
    if not wid:
        raise ValueError("workspace_id is required")
    if max_parts is not None and int(max_parts) < 0:
        raise ValueError("max_parts must be non-negative")
    value = None if max_parts is None else int(max_parts)
    if _use_postgres():
        with _pg_connect() as conn:
            conn.execute(
                """
                INSERT INTO migration_workspace_monitoring_capacity (workspace_id, max_parts, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (workspace_id) DO UPDATE SET
                  max_parts = EXCLUDED.max_parts,
                  updated_at = NOW()
                """,
                (wid, value),
            )
            conn.commit()
        return
    with _lock:
        state = _load_state()
        state.setdefault("workspace_monitoring_capacities", {})[wid] = value
        _save_state(state)


def update_preferences(workspace_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    allowed = {"email_alerts", "weekly_digest", "lifecycle", "availability", "risk"}
    current = get_preferences(workspace_id)
    for key, value in (updates or {}).items():
        if key in allowed:
            current[key] = bool(value)
    if _use_postgres():
        with _pg_connect() as conn:
            conn.execute(
                """
                INSERT INTO migration_notification_preferences
                  (workspace_id, email_alerts, weekly_digest, lifecycle, availability, risk, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (workspace_id) DO UPDATE SET
                  email_alerts = EXCLUDED.email_alerts,
                  weekly_digest = EXCLUDED.weekly_digest,
                  lifecycle = EXCLUDED.lifecycle,
                  availability = EXCLUDED.availability,
                  risk = EXCLUDED.risk,
                  updated_at = NOW()
                """,
                (
                    workspace_id,
                    current["email_alerts"],
                    current["weekly_digest"],
                    current["lifecycle"],
                    current["availability"],
                    current["risk"],
                ),
            )
            conn.commit()
    else:
        with _lock:
            state = _load_state()
            prefs = _ws(state, workspace_id)["preferences"]
            for key in allowed:
                prefs[key] = bool(current[key])
            _save_state(state)
    return get_preferences(workspace_id)


def get_user_preferences(
    workspace_id: str,
    user_id: str,
    verified_email: str,
) -> dict[str, Any]:
    """Return one member's monitoring choices and server-verified address.

    ``verified_email`` is always supplied by the authenticated token context;
    the browser cannot choose or overwrite the notification recipient.
    """
    wid = str(workspace_id or "").strip()
    uid = str(user_id or "").strip()
    email = str(verified_email or "").strip().lower()
    if not wid or not uid or not email:
        raise ValueError("workspace, authenticated user, and verified email are required")
    defaults = {
        **_DEFAULT_PREFS,
        "supplier_checks": False,
        "email": email,
    }
    if _use_postgres():
        with _pg_connect() as conn:
            row = conn.execute(
                """
                SELECT email_alerts, weekly_digest, supplier_checks, lifecycle, availability, risk
                FROM migration_monitoring_member_preferences
                WHERE workspace_id = %s AND user_id = %s
                """,
                (wid, uid),
            ).fetchone()
        if row:
            defaults.update({
                "email_alerts": bool(row["email_alerts"]),
                "weekly_digest": bool(row["weekly_digest"]),
                "supplier_checks": bool(row["supplier_checks"]),
                "lifecycle": bool(row["lifecycle"]),
                "availability": bool(row["availability"]),
                "risk": bool(row["risk"]),
            })
    else:
        with _lock:
            state = _load_state()
            stored = _ws(state, wid).setdefault("user_preferences", {}).get(uid) or {}
            defaults.update({key: bool(stored.get(key, defaults[key])) for key in (
                "email_alerts", "weekly_digest", "supplier_checks", "lifecycle", "availability", "risk"
            )})
    defaults["email"] = email
    defaults["email_delivery_enabled"] = email_delivery_enabled()
    defaults["email_transport_ready"] = email_transport_ready()
    return defaults


def update_user_preferences(
    workspace_id: str,
    user_id: str,
    verified_email: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Persist opt-ins scoped to the authenticated workspace member."""
    wid = str(workspace_id or "").strip()
    uid = str(user_id or "").strip()
    email = str(verified_email or "").strip().lower()
    if not wid or not uid or not email:
        raise ValueError("workspace, authenticated user, and verified email are required")
    allowed = {"email_alerts", "weekly_digest", "supplier_checks", "lifecycle", "availability", "risk"}
    current = get_user_preferences(wid, uid, email)
    for key, value in (updates or {}).items():
        if key in allowed:
            current[key] = bool(value)
    if _use_postgres():
        with _pg_connect() as conn:
            conn.execute(
                """
                INSERT INTO migration_monitoring_member_preferences
                  (workspace_id, user_id, email, email_alerts, weekly_digest, supplier_checks,
                   lifecycle, availability, risk, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (workspace_id, user_id) DO UPDATE SET
                  email = EXCLUDED.email,
                  email_alerts = EXCLUDED.email_alerts,
                  weekly_digest = EXCLUDED.weekly_digest,
                  supplier_checks = EXCLUDED.supplier_checks,
                  lifecycle = EXCLUDED.lifecycle,
                  availability = EXCLUDED.availability,
                  risk = EXCLUDED.risk,
                  updated_at = NOW()
                """,
                (
                    wid, uid, email, current["email_alerts"], current["weekly_digest"], current["supplier_checks"],
                    current["lifecycle"], current["availability"], current["risk"],
                ),
            )
            conn.commit()
    else:
        with _lock:
            state = _load_state()
            bucket = _ws(state, wid).setdefault("user_preferences", {})
            bucket[uid] = {
                "email": email,
                **{key: bool(current[key]) for key in allowed},
            }
            _save_state(state)
    return get_user_preferences(wid, uid, email)


def list_user_preferences(
    workspace_id: str | None = None,
    *,
    supplier_checks: bool | None = None,
    email_alerts: bool | None = None,
    weekly_digest: bool | None = None,
) -> list[dict[str, Any]]:
    """List only opted-in member preferences for a scheduler cycle."""
    filters = []
    params: list[Any] = []
    if workspace_id:
        filters.append("workspace_id = %s")
        params.append(str(workspace_id))
    if supplier_checks is not None:
        filters.append("supplier_checks = %s")
        params.append(bool(supplier_checks))
    if email_alerts is not None:
        filters.append("email_alerts = %s")
        params.append(bool(email_alerts))
    if weekly_digest is not None:
        filters.append("weekly_digest = %s")
        params.append(bool(weekly_digest))
    if _use_postgres():
        query = (
            "SELECT workspace_id, user_id, email, email_alerts, weekly_digest, supplier_checks, "
            "lifecycle, availability, risk FROM migration_monitoring_member_preferences"
        )
        if filters:
            query += " WHERE " + " AND ".join(filters)
        with _pg_connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]
    with _lock:
        state = _load_state()
        rows = []
        for wid, bucket in (state.get("workspaces") or {}).items():
            if workspace_id and wid != workspace_id:
                continue
            for uid, prefs in (bucket.get("user_preferences") or {}).items():
                row = {"workspace_id": wid, "user_id": uid, **dict(prefs)}
                if supplier_checks is not None and bool(row.get("supplier_checks")) != supplier_checks:
                    continue
                if email_alerts is not None and bool(row.get("email_alerts")) != email_alerts:
                    continue
                if weekly_digest is not None and bool(row.get("weekly_digest")) != weekly_digest:
                    continue
                rows.append(row)
        return rows


def get_live_snapshot(
    workspace_id: str, analysis_id: str, part_number: str
) -> dict[str, Any] | None:
    if _use_postgres():
        with _pg_connect() as conn:
            row = conn.execute(
                "SELECT payload FROM migration_monitoring_snapshots "
                "WHERE workspace_id = %s AND analysis_id = %s AND part_number = %s",
                (workspace_id, analysis_id, part_number),
            ).fetchone()
        if not row:
            return None
        payload = row["payload"]
        return json.loads(payload) if isinstance(payload, str) else dict(payload)
    with _lock:
        state = _load_state()
        row = (
            _ws(state, workspace_id).setdefault("snapshots", {})
            .get(analysis_id, {})
            .get(part_number)
        )
        return dict(row) if row else None


def list_live_snapshots(workspace_id: str, analysis_id: str) -> list[dict[str, Any]]:
    """List saved live supplier snapshots for one workspace analysis."""
    wid = str(workspace_id or "").strip()
    aid = str(analysis_id or "").strip()
    if not wid or not aid:
        return []
    if _use_postgres():
        with _pg_connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM migration_monitoring_snapshots "
                "WHERE workspace_id = %s AND analysis_id = %s ORDER BY part_number",
                (wid, aid),
            ).fetchall()
        snapshots: list[dict[str, Any]] = []
        for row in rows:
            payload = row["payload"]
            snapshot = json.loads(payload) if isinstance(payload, str) else dict(payload)
            if isinstance(snapshot, dict):
                snapshots.append(snapshot)
        return snapshots
    with _lock:
        state = _load_state()
        bucket = (state.get("workspaces") or {}).get(wid) or {}
        rows = (bucket.get("snapshots") or {}).get(aid) or {}
        return [
            dict(snapshot)
            for _, snapshot in sorted(rows.items())
            if isinstance(snapshot, dict)
        ]


def save_live_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Upsert a matched live supplier observation for one analysis part."""
    wid = str(snapshot.get("workspace_id") or "").strip()
    aid = str(snapshot.get("analysis_id") or "").strip()
    part = str(snapshot.get("part_number") or "").strip()
    if not wid or not aid or not part:
        raise ValueError("workspace, analysis, and part are required for monitoring snapshots")
    saved = {**snapshot, "workspace_id": wid, "analysis_id": aid, "part_number": part}
    if _use_postgres():
        with _pg_connect() as conn:
            conn.execute(
                """
                INSERT INTO migration_monitoring_snapshots
                  (workspace_id, analysis_id, part_number, payload, retrieved_at)
                VALUES (%s, %s, %s, %s::jsonb, %s::timestamptz)
                ON CONFLICT (workspace_id, analysis_id, part_number) DO UPDATE SET
                  payload = EXCLUDED.payload,
                  retrieved_at = EXCLUDED.retrieved_at
                """,
                (wid, aid, part, json.dumps(saved), saved.get("retrieved_at") or utc_now()),
            )
            conn.commit()
        return saved
    with _lock:
        state = _load_state()
        snapshots = _ws(state, wid).setdefault("snapshots", {})
        snapshots.setdefault(aid, {})[part] = saved
        _save_state(state)
    return saved


def _email_delivery_key(workspace_id: str, user_id: str, alert_id: str) -> str:
    value = "\0".join((workspace_id, user_id, alert_id)).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def claim_scheduled_alert_email(
    workspace_id: str, user_id: str, alert: dict[str, Any]
) -> bool:
    """Acquire a short lease so overlapping scheduler jobs cannot double-send."""
    wid = str(workspace_id or "").strip()
    uid = str(user_id or "").strip()
    alert_id = str(alert.get("id") or "").strip()
    if not wid or not uid or not alert_id:
        return False
    if _use_postgres():
        with _pg_connect() as conn:
            row = conn.execute(
                """
                INSERT INTO migration_monitoring_email_deliveries
                  (workspace_id, user_id, alert_id, status, lease_until, updated_at)
                VALUES (%s, %s, %s, 'sending', NOW() + INTERVAL '5 minutes', NOW())
                ON CONFLICT (workspace_id, user_id, alert_id) DO UPDATE SET
                  status = 'sending',
                  lease_until = NOW() + INTERVAL '5 minutes',
                  updated_at = NOW()
                WHERE migration_monitoring_email_deliveries.status <> 'sent'
                  AND (
                    migration_monitoring_email_deliveries.status <> 'sending'
                    OR migration_monitoring_email_deliveries.lease_until IS NULL
                    OR migration_monitoring_email_deliveries.lease_until < NOW()
                  )
                RETURNING 1 AS claimed
                """,
                (wid, uid, alert_id),
            ).fetchone()
            conn.commit()
        return bool(row)

    now = datetime.now(timezone.utc)
    key = _email_delivery_key(wid, uid, alert_id)
    with _lock:
        state = _load_state()
        deliveries = _ws(state, wid).setdefault("email_deliveries", {})
        prior = deliveries.get(key) or {}
        if prior.get("status") == "sent":
            return False
        if prior.get("status") == "sending":
            try:
                lease = datetime.fromisoformat(
                    str(prior.get("lease_until") or "").replace("Z", "+00:00")
                )
            except ValueError:
                lease = now
            if lease > now:
                return False
        deliveries[key] = {
            "workspace_id": wid,
            "user_id": uid,
            "alert_id": alert_id,
            "status": "sending",
            "lease_until": (now + timedelta(minutes=5)).isoformat(),
        }
        _save_state(state)
    return True


def finish_scheduled_alert_email(
    workspace_id: str,
    user_id: str,
    alert: dict[str, Any],
    *,
    delivered: bool,
    retry: bool = True,
) -> None:
    """Record success, retry transient failures, or discard opted-out notices."""
    wid = str(workspace_id or "").strip()
    uid = str(user_id or "").strip()
    alert_id = str(alert.get("id") or "").strip()
    if not wid or not uid or not alert_id:
        return
    sent_at = utc_now()
    if _use_postgres():
        with _pg_connect() as conn:
            if delivered:
                conn.execute(
                    """
                    UPDATE migration_monitoring_email_deliveries
                    SET status = 'sent', sent_at = %s::timestamptz,
                        lease_until = NULL, updated_at = NOW()
                    WHERE workspace_id = %s AND user_id = %s AND alert_id = %s
                    """,
                    (sent_at, wid, uid, alert_id),
                )
            elif retry:
                conn.execute(
                    """
                    UPDATE migration_monitoring_email_deliveries
                    SET lease_until = NOW() - INTERVAL '1 second', updated_at = NOW()
                    WHERE workspace_id = %s AND user_id = %s AND alert_id = %s
                      AND status = 'sending'
                    """,
                    (wid, uid, alert_id),
                )
            else:
                conn.execute(
                    "DELETE FROM migration_monitoring_email_deliveries "
                    "WHERE workspace_id = %s AND user_id = %s AND alert_id = %s "
                    "AND status = 'sending'",
                    (wid, uid, alert_id),
                )
            conn.commit()
        return

    key = _email_delivery_key(wid, uid, alert_id)
    with _lock:
        state = _load_state()
        deliveries = _ws(state, wid).setdefault("email_deliveries", {})
        if delivered:
            deliveries[key] = {
                "workspace_id": wid,
                "user_id": uid,
                "alert_id": alert_id,
                "status": "sent",
                "sent_at": sent_at,
            }
        elif retry:
            prior = deliveries.get(key) or {}
            if prior.get("status") == "sending":
                prior["lease_until"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
                deliveries[key] = prior
        else:
            deliveries.pop(key, None)
        _save_state(state)


def claim_weekly_digest_email(workspace_id: str, user_id: str) -> bool:
    """Claim a member's weekly digest slot without exposing recipient data."""
    wid = str(workspace_id or "").strip()
    uid = str(user_id or "").strip()
    if not wid or not uid:
        return False
    if _use_postgres():
        with _pg_connect() as conn:
            row = conn.execute(
                """
                INSERT INTO migration_monitoring_digest_deliveries
                  (workspace_id, user_id, status, lease_until, updated_at)
                VALUES (%s, %s, 'sending', NOW() + INTERVAL '5 minutes', NOW())
                ON CONFLICT (workspace_id, user_id) DO UPDATE SET
                  status = 'sending',
                  lease_until = NOW() + INTERVAL '5 minutes',
                  updated_at = NOW()
                WHERE (migration_monitoring_digest_deliveries.sent_at IS NULL
                   OR migration_monitoring_digest_deliveries.sent_at < NOW() - INTERVAL '7 days')
                  AND (migration_monitoring_digest_deliveries.status <> 'sending'
                    OR migration_monitoring_digest_deliveries.lease_until IS NULL
                    OR migration_monitoring_digest_deliveries.lease_until < NOW())
                RETURNING user_id
                """,
                (wid, uid),
            ).fetchone()
            conn.commit()
        return bool(row)

    now = datetime.now(timezone.utc)
    with _lock:
        state = _load_state()
        deliveries = _ws(state, wid).setdefault("digest_deliveries", {})
        prior = deliveries.get(uid) or {}
        sent_at = prior.get("sent_at")
        if sent_at:
            try:
                parsed_sent_at = datetime.fromisoformat(str(sent_at).replace("Z", "+00:00"))
                if parsed_sent_at.tzinfo is None:
                    parsed_sent_at = parsed_sent_at.replace(tzinfo=timezone.utc)
                if parsed_sent_at > now - timedelta(days=7):
                    return False
            except ValueError:
                pass
        if prior.get("status") == "sending":
            try:
                lease = datetime.fromisoformat(
                    str(prior.get("lease_until") or "").replace("Z", "+00:00")
                )
            except ValueError:
                lease = now
            if lease > now:
                return False
        deliveries[uid] = {
            **prior,
            "status": "sending",
            "lease_until": (now + timedelta(minutes=5)).isoformat(),
            "updated_at": now.isoformat(),
        }
        _save_state(state)
    return True


def finish_weekly_digest_email(
    workspace_id: str, user_id: str, *, delivered: bool
) -> None:
    """Record a digest receipt or release its lease for a later retry."""
    wid = str(workspace_id or "").strip()
    uid = str(user_id or "").strip()
    if not wid or not uid:
        return
    now = utc_now()
    if _use_postgres():
        with _pg_connect() as conn:
            conn.execute(
                """
                UPDATE migration_monitoring_digest_deliveries
                   SET status = %s,
                       sent_at = CASE WHEN %s THEN %s::timestamptz ELSE sent_at END,
                       lease_until = NULL,
                       updated_at = NOW()
                 WHERE workspace_id = %s AND user_id = %s
                """,
                ("sent" if delivered else "failed", delivered, now, wid, uid),
            )
            conn.commit()
        return
    with _lock:
        state = _load_state()
        deliveries = _ws(state, wid).setdefault("digest_deliveries", {})
        prior = deliveries.get(uid) or {}
        deliveries[uid] = {
            **prior,
            "status": "sent" if delivered else "failed",
            "sent_at": now if delivered else prior.get("sent_at"),
            "lease_until": None,
            "updated_at": now,
        }
        _save_state(state)


def list_retryable_scheduled_alert_ids(workspace_id: str, user_id: str) -> list[str]:
    """Return failed delivery claims whose lease expired and may be retried."""
    wid = str(workspace_id or "").strip()
    uid = str(user_id or "").strip()
    if not wid or not uid:
        return []
    if _use_postgres():
        with _pg_connect() as conn:
            rows = conn.execute(
                """
                SELECT alert_id FROM migration_monitoring_email_deliveries
                WHERE workspace_id = %s AND user_id = %s AND status = 'sending'
                  AND (lease_until IS NULL OR lease_until < NOW())
                ORDER BY updated_at ASC
                """,
                (wid, uid),
            ).fetchall()
        return [str(row["alert_id"]) for row in rows]
    now = datetime.now(timezone.utc)
    with _lock:
        state = _load_state()
        deliveries = _ws(state, wid).setdefault("email_deliveries", {})
        retryable = []
        for row in deliveries.values():
            if row.get("user_id") != uid or row.get("status") != "sending":
                continue
            try:
                lease = datetime.fromisoformat(
                    str(row.get("lease_until") or "").replace("Z", "+00:00")
                )
            except ValueError:
                lease = now
            if lease <= now:
                retryable.append(str(row.get("alert_id") or ""))
        return [alert_id for alert_id in retryable if alert_id]


def clear_scheduled_alert_email_deliveries(
    workspace_id: str, alert_id: str
) -> None:
    """Allow a resolved alert to notify again if it becomes active later."""
    wid = str(workspace_id or "").strip()
    aid = str(alert_id or "").strip()
    if not wid or not aid:
        return
    if _use_postgres():
        with _pg_connect() as conn:
            conn.execute(
                "DELETE FROM migration_monitoring_email_deliveries "
                "WHERE workspace_id = %s AND alert_id = %s AND status = 'sent'",
                (wid, aid),
            )
            conn.commit()
        return
    with _lock:
        state = _load_state()
        deliveries = _ws(state, wid).setdefault("email_deliveries", {})
        for key, row in list(deliveries.items()):
            if str(row.get("alert_id") or "") == aid and row.get("status") == "sent":
                deliveries.pop(key, None)
        _save_state(state)


def _alert_identity_key(alert: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(alert.get("analysis_id") or "").strip(),
        str(alert.get("part_number") or "").strip(),
        str(alert.get("alert_type") or "").strip(),
    )


def reconcile_alerts(
    workspace_id: str,
    *,
    analysis_id: str,
    active_alerts: list[dict[str, Any]],
    part_number: str | None = None,
) -> list[dict[str, Any]]:
    """Mark persisted alerts inactive when they no longer apply to the scope.

    Active derived alerts are written with ``active=True``. Persisted rows for
    the same analysis (or part) that are absent from ``active_alerts`` are kept
    for history but flagged ``active=False`` so read views do not show them as
    current.
    """
    report_id = str(analysis_id or "").strip()
    part = str(part_number or "").strip() or None
    if not report_id:
        return []
    active_keys = {_alert_identity_key(a) for a in active_alerts}
    for alert in active_alerts:
        alert["active"] = True
        alert["status"] = str(alert.get("status") or "active")
    persisted = persist_alerts(workspace_id, active_alerts) if active_alerts else []
    existing = list_alerts(workspace_id, analysis_id=report_id)
    inactivated: list[dict[str, Any]] = []
    for row in existing:
        key = _alert_identity_key(row)
        if key[0] != report_id:
            continue
        if part and key[1].casefold() != part.casefold():
            continue
        if key in active_keys:
            continue
        if row.get("active") is False or str(row.get("status") or "").lower() == "inactive":
            continue
        stale = dict(row)
        stale["active"] = False
        stale["status"] = "inactive"
        stale["resolved_at"] = utc_now()
        inactivated.append(stale)
    if inactivated:
        persist_alerts(workspace_id, inactivated)
        for row in inactivated:
            clear_scheduled_alert_email_deliveries(
                workspace_id, str(row.get("id") or "")
            )
            clear_scheduled_slack_alert_delivery(
                workspace_id, str(row.get("id") or "")
            )
    return [
        row
        for row in list_alerts(workspace_id, analysis_id=report_id)
        if row.get("active") is not False
        and str(row.get("status") or "active").lower() != "inactive"
        and (not part or str(row.get("part_number") or "").casefold() == part.casefold())
    ]


def persist_alerts(workspace_id: str, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Upsert alert rows for a workspace; returns durable copies for those analyses."""
    analysis_ids = {
        str(alert.get("analysis_id") or "").strip()
        for alert in alerts
        if str(alert.get("analysis_id") or "").strip()
    }
    if _use_postgres():
        with _pg_connect() as conn:
            for alert in alerts:
                alert_id = str(alert.get("id") or f"alert-{uuid.uuid4().hex[:12]}")
                payload = dict(alert)
                payload["id"] = alert_id
                payload["workspace_id"] = workspace_id
                conn.execute(
                    """
                    INSERT INTO migration_monitoring_alerts
                      (id, workspace_id, analysis_id, part_number, alert_type, severity, message, acknowledged, payload, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, COALESCE(%s::timestamptz, NOW()), NOW())
                    ON CONFLICT (workspace_id, analysis_id, part_number, alert_type) DO UPDATE SET
                      severity = EXCLUDED.severity,
                      message = EXCLUDED.message,
                      payload = EXCLUDED.payload,
                      updated_at = NOW()
                    """,
                    (
                        alert_id,
                        workspace_id,
                        alert.get("analysis_id"),
                        alert.get("part_number"),
                        alert.get("alert_type"),
                        alert.get("severity"),
                        alert.get("message") or alert.get("details") or "",
                        bool(alert.get("acknowledged")),
                        json.dumps(payload),
                        alert.get("created_at"),
                    ),
                )
            conn.commit()
        # Return only the requested analysis scope(s), never the full workspace dump.
        if len(analysis_ids) == 1:
            return list_alerts(workspace_id, analysis_id=next(iter(analysis_ids)))
        if analysis_ids:
            scoped: list[dict[str, Any]] = []
            for analysis_id in analysis_ids:
                scoped.extend(list_alerts(workspace_id, analysis_id=analysis_id))
            return scoped
        return list_alerts(workspace_id)

    with _lock:
        state = _load_state()
        bucket = _ws(state, workspace_id)
        existing = {
            (a.get("analysis_id"), a.get("part_number"), a.get("alert_type")): a
            for a in bucket["alerts"]
        }
        for alert in alerts:
            key = (alert.get("analysis_id"), alert.get("part_number"), alert.get("alert_type"))
            previous = dict(existing.get(key) or {})
            row = dict(previous)
            row.update(alert)
            if previous.get("id"):
                row["id"] = previous["id"]
            if previous.get("created_at"):
                row["created_at"] = previous["created_at"]
            row.setdefault("id", f"alert-{uuid.uuid4().hex[:12]}")
            row.setdefault("workspace_id", workspace_id)
            row.setdefault("created_at", utc_now())
            row["updated_at"] = utc_now()
            row.setdefault("acknowledged", False)
            existing[key] = row
        bucket["alerts"] = list(existing.values())
        _save_state(state)
        if analysis_ids:
            return [
                dict(row)
                for row in bucket["alerts"]
                if str(row.get("analysis_id") or "").strip() in analysis_ids
            ]
        return list(bucket["alerts"])


def list_alerts(
    workspace_id: str, analysis_id: str | None = None
) -> list[dict[str, Any]]:
    scoped_id = str(analysis_id or "").strip() or None
    if _use_postgres():
        with _pg_connect() as conn:
            if scoped_id:
                rows = conn.execute(
                    """
                    SELECT payload, acknowledged, id
                    FROM migration_monitoring_alerts
                    WHERE workspace_id = %s AND analysis_id = %s
                    ORDER BY updated_at DESC
                    """,
                    (workspace_id, scoped_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT payload, acknowledged, id FROM migration_monitoring_alerts WHERE workspace_id = %s ORDER BY updated_at DESC",
                    (workspace_id,),
                ).fetchall()
        out = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            item = dict(payload)
            item["id"] = row["id"]
            item["acknowledged"] = bool(row["acknowledged"])
            out.append(item)
        return out
    with _lock:
        state = _load_state()
        alerts = list(_ws(state, workspace_id)["alerts"])
        if scoped_id:
            return [
                dict(row)
                for row in alerts
                if str(row.get("analysis_id") or "").strip() == scoped_id
            ]
        return alerts


def acknowledge_alert(workspace_id: str, alert_id: str) -> dict[str, Any] | None:
    if _use_postgres():
        with _pg_connect() as conn:
            row = conn.execute(
                """
                UPDATE migration_monitoring_alerts
                SET acknowledged = TRUE, updated_at = NOW(),
                    payload = jsonb_set(COALESCE(payload, '{}'::jsonb), '{acknowledged}', 'true'::jsonb, true)
                WHERE workspace_id = %s AND id = %s
                RETURNING payload, id, acknowledged
                """,
                (workspace_id, alert_id),
            ).fetchone()
            conn.commit()
        if not row:
            return None
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        item = dict(payload)
        item["id"] = row["id"]
        item["acknowledged"] = True
        item["acknowledged_at"] = utc_now()
        return item
    with _lock:
        state = _load_state()
        bucket = _ws(state, workspace_id)
        for alert in bucket["alerts"]:
            if alert.get("id") == alert_id:
                alert["acknowledged"] = True
                alert["acknowledged_at"] = utc_now()
                _save_state(state)
                return dict(alert)
    return None


def record_refresh(
    workspace_id: str,
    *,
    analysis_id: str | None,
    alert_count: int,
    mode: str = "synthetic-preview",
    scope: str = "analysis",
    part_number: str | None = None,
    scheduled: bool = False,
) -> dict[str, Any]:
    """Record an explicit refresh. Never called from read-only GET paths."""
    entry = {
        "id": f"refresh-{uuid.uuid4().hex[:10]}",
        "workspace_id": workspace_id,
        "analysis_id": analysis_id,
        "alert_count": alert_count,
        "mode": mode,
        "scope": scope,
        "part_number": part_number,
        "ran_at": utc_now(),
        "scheduled": bool(scheduled),
        "gap": "" if scheduled else "On-demand refresh. Scheduled runs are separately gated.",
    }
    if _use_postgres():
        with _pg_connect() as conn:
            conn.execute(
                """
                INSERT INTO migration_monitoring_refresh_history
                  (id, workspace_id, analysis_id, alert_count, mode, ran_at, payload)
                VALUES (%s, %s, %s, %s, %s, NOW(), %s::jsonb)
                """,
                (
                    entry["id"],
                    workspace_id,
                    analysis_id,
                    alert_count,
                    mode,
                    json.dumps(entry),
                ),
            )
            conn.commit()
        return entry
    with _lock:
        state = _load_state()
        history = _ws(state, workspace_id)["refresh_history"]
        history.insert(0, entry)
        del history[50:]
        _save_state(state)
    return entry


def list_refresh_history(workspace_id: str) -> list[dict[str, Any]]:
    if _use_postgres():
        with _pg_connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM migration_monitoring_refresh_history WHERE workspace_id = %s ORDER BY ran_at DESC LIMIT 50",
                (workspace_id,),
            ).fetchall()
        out = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            out.append(dict(payload))
        return out
    with _lock:
        state = _load_state()
        return list(_ws(state, workspace_id)["refresh_history"])


def deliver_alert_email(
    workspace_id: str,
    alert: dict[str, Any],
    *,
    user_id: str | None = None,
    recipient_email: str | None = None,
    sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Send or mock-record an alert only to the authenticated member's address."""
    prefs = (
        get_user_preferences(workspace_id, user_id, recipient_email or "")
        if user_id
        else get_preferences(workspace_id)
    )
    payload = {
        "workspace_id": workspace_id,
        "alert_id": alert.get("id"),
        "part_number": alert.get("part_number"),
        "alert_type": alert.get("alert_type"),
        "severity": alert.get("severity"),
        "recorded_at": utc_now(),
    }
    if not prefs.get("email_alerts"):
        return {"ok": True, "delivered": False, "reason": "preferences_disabled", "payload": payload}
    alert_type = str(alert.get("alert_type") or "").casefold()
    category = (
        "lifecycle" if any(term in alert_type for term in ("lifecycle", "pcn", "product change notice")) else
        "availability" if any(term in alert_type for term in ("stock", "availability", "inventory", "lead time", "lead_time")) else
        "risk"
    )
    if not prefs.get(category, True):
        return {"ok": True, "delivered": False, "reason": f"{category}_notifications_disabled", "payload": payload}
    if not email_delivery_enabled():
        with _lock:
            _EMAIL_SINK.append({**payload, "sink": "mock-record"})
        return {
            "ok": True,
            "delivered": False,
            "reason": "email_transport_disabled",
            "mock_recorded": True,
            "payload": payload,
        }
    active = sink or getattr(deliver_alert_email, "_default_sink", None)
    if active is not None:
        active(payload)
        return {"ok": True, "delivered": True, "payload": payload, "mode": "sink"}
    if _configured_email_transport():
        recipient = str(recipient_email or prefs.get("email") or "").strip().lower()
        if not recipient:
            return {
                "ok": False,
                "delivered": False,
                "reason": "no_sink_configured",
                "payload": payload,
            }
        try:
            from src.email_delivery import send_transactional_email

            part = str(alert.get("part_number") or "component")
            subject = f"Cadivor monitoring alert · {part}"
            body = str(alert.get("alert_message") or alert.get("alert_type") or "Monitoring alert")
            import html

            send_transactional_email(
                to_email=recipient,
                subject=subject,
                html_body=f"<p>{html.escape(body)}</p>",
                text_body=body,
            )
            return {"ok": True, "delivered": True, "payload": payload, "mode": "resend"}
        except Exception:  # noqa: BLE001
            return {
                "ok": False,
                "delivered": False,
                "reason": "no_sink_configured",
                "payload": payload,
            }
    return {"ok": False, "delivered": False, "reason": "no_sink_configured", "payload": payload}

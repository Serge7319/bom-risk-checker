"""Durable monitoring alerts and notification preferences.

Uses the dedicated migration Postgres when CADIVOR_MIGRATION_DATABASE_URL is set;
otherwise an ephemeral file/memory store for local tests. Alert email delivery
uses an injectable sink; production delivery stays disabled until
CADIVOR_MONITORING_EMAIL_ENABLED=1 with a verified transport. Default sink
records payloads in-memory for tests.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from apps.api.workspace_store import allow_ephemeral_file_store, get_store, migration_database_url


_lock = threading.Lock()
_EMAIL_SINK: list[dict[str, Any]] = []
_DEFAULT_PREFS = {
    "email_alerts": False,
    "lifecycle": True,
    "availability": True,
    "risk": True,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def email_delivery_enabled() -> bool:
    return (os.environ.get("CADIVOR_MONITORING_EMAIL_ENABLED") or "").strip() == "1"


def reset_email_sink_for_tests() -> None:
    with _lock:
        _EMAIL_SINK.clear()


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
        return json.loads(path.read_text(encoding="utf-8"))
    return getattr(_load_state, "_mem", {"workspaces": {}})  # type: ignore[attr-defined]


def _save_state(state: dict[str, Any]) -> None:
    path = _file_path()
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        return
    setattr(_load_state, "_mem", state)


def reset_monitoring_store_for_tests() -> None:
    with _lock:
        setattr(_load_state, "_mem", {"workspaces": {}})
        path = _file_path()
        if path and path.exists():
            path.unlink()
        _EMAIL_SINK.clear()
        if _use_postgres():
            with _pg_connect() as conn:
                conn.execute("DELETE FROM migration_monitoring_alerts")
                conn.execute("DELETE FROM migration_notification_preferences")
                conn.execute("DELETE FROM migration_monitoring_refresh_history")
                conn.commit()


def _ws(state: dict[str, Any], workspace_id: str) -> dict[str, Any]:
    workspaces = state.setdefault("workspaces", {})
    return workspaces.setdefault(
        workspace_id,
        {"alerts": [], "preferences": dict(_DEFAULT_PREFS), "refresh_history": []},
    )


def get_preferences(workspace_id: str) -> dict[str, Any]:
    if _use_postgres():
        with _pg_connect() as conn:
            row = conn.execute(
                "SELECT email_alerts, lifecycle, availability, risk FROM migration_notification_preferences WHERE workspace_id = %s",
                (workspace_id,),
            ).fetchone()
        prefs = dict(_DEFAULT_PREFS) if not row else {
            "email_alerts": bool(row["email_alerts"]),
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


def update_preferences(workspace_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    allowed = {"email_alerts", "lifecycle", "availability", "risk"}
    current = get_preferences(workspace_id)
    for key, value in (updates or {}).items():
        if key in allowed:
            current[key] = bool(value)
    if _use_postgres():
        with _pg_connect() as conn:
            conn.execute(
                """
                INSERT INTO migration_notification_preferences
                  (workspace_id, email_alerts, lifecycle, availability, risk, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (workspace_id) DO UPDATE SET
                  email_alerts = EXCLUDED.email_alerts,
                  lifecycle = EXCLUDED.lifecycle,
                  availability = EXCLUDED.availability,
                  risk = EXCLUDED.risk,
                  updated_at = NOW()
                """,
                (
                    workspace_id,
                    current["email_alerts"],
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


def persist_alerts(workspace_id: str, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Upsert alert rows for a workspace; returns durable copies."""
    if _use_postgres():
        saved: list[dict[str, Any]] = []
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
            rows = conn.execute(
                "SELECT payload FROM migration_monitoring_alerts WHERE workspace_id = %s ORDER BY updated_at DESC",
                (workspace_id,),
            ).fetchall()
            for row in rows:
                payload = row["payload"]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                saved.append(dict(payload))
        return saved

    saved = []
    with _lock:
        state = _load_state()
        bucket = _ws(state, workspace_id)
        existing = {
            (a.get("analysis_id"), a.get("part_number"), a.get("alert_type")): a
            for a in bucket["alerts"]
        }
        for alert in alerts:
            key = (alert.get("analysis_id"), alert.get("part_number"), alert.get("alert_type"))
            row = dict(existing.get(key) or {})
            row.update(alert)
            row.setdefault("id", f"alert-{uuid.uuid4().hex[:12]}")
            row.setdefault("workspace_id", workspace_id)
            row.setdefault("created_at", utc_now())
            row["updated_at"] = utc_now()
            row.setdefault("acknowledged", False)
            existing[key] = row
        bucket["alerts"] = list(existing.values())
        saved = list(bucket["alerts"])
        _save_state(state)
    return saved


def list_alerts(workspace_id: str) -> list[dict[str, Any]]:
    if _use_postgres():
        with _pg_connect() as conn:
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
        return list(_ws(state, workspace_id)["alerts"])


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
) -> dict[str, Any]:
    entry = {
        "id": f"refresh-{uuid.uuid4().hex[:10]}",
        "workspace_id": workspace_id,
        "analysis_id": analysis_id,
        "alert_count": alert_count,
        "mode": mode,
        "ran_at": utc_now(),
        "scheduled": False,
        "gap": "On-demand refresh only. Cron/scheduler not attached to migration API yet.",
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
    sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Send or mock-record an alert notification. Never sends unless enabled."""
    prefs = get_preferences(workspace_id)
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
    if sink is None:
        return {"ok": False, "delivered": False, "reason": "no_sink_configured", "payload": payload}
    sink(payload)
    return {"ok": True, "delivered": True, "payload": payload}

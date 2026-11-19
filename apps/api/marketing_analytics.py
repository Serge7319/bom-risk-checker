"""Privacy-minimal first-party marketing event intake and funnel summaries.

The event schema intentionally excludes emails, IPs, BOM contents, and component
identifiers. A browser session UUID is one-way hashed before it is stored.
"""
from __future__ import annotations

import hashlib
import re
import threading
from datetime import datetime, timezone
from typing import Any

from apps.api.workspace_store import PersistenceNotConfiguredError, allow_ephemeral_file_store, migration_database_url

EVENTS = frozenset({
    "page_view", "cta_click", "free_audit_started", "free_audit_completed",
    "signup_started", "signup_completed", "bom_uploaded", "first_analysis_completed",
    "trial_started", "upgrade_clicked", "checkout_started", "subscription_created",
    "demo_requested", "one_time_report_purchased", "free_audit_email_requested",
    "free_audit_trial_clicked", "first_blocker_viewed",
})
UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")
_SAFE = re.compile(r"^[\w .:+~/=-]{1,80}$", re.UNICODE)
_SESSION = re.compile(r"^[0-9a-f-]{36}$", re.IGNORECASE)
_LOCK = threading.RLock()
_TEST_STORE: Any | None = None
_STORE: Any | None = None


class MarketingAnalyticsError(RuntimeError):
    pass


def sanitize_utm(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key in UTM_KEYS:
        raw = value.get(key)
        if not isinstance(raw, str):
            continue
        clean = " ".join(raw.split())[:80]
        if clean and "@" not in clean and _SAFE.fullmatch(clean):
            result[key] = clean
    return result


def validate_event(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    event_name = str(payload.get("event") or "").strip().lower()
    if event_name not in EVENTS:
        return None
    source = str(payload.get("source") or "").strip().lower()
    if source not in {"marketing", "app"}:
        return None
    page = str(payload.get("page") or "").strip()
    if not page.startswith("/") or page.startswith("//") or len(page) > 160 or "?" in page or "#" in page:
        return None
    session_id = str(payload.get("session_id") or "").strip()
    if not _SESSION.fullmatch(session_id):
        session_id = ""
    props = payload.get("properties")
    props = props if isinstance(props, dict) else {}
    # Keep only small, non-sensitive categorical properties. Free text and IDs
    # are dropped even when a browser sends them.
    safe_props: dict[str, str] = {}
    for key in ("location", "cta", "flow", "plan", "intent"):
        value = props.get(key)
        if isinstance(value, str):
            clean = " ".join(value.split())[:80]
            if clean and "@" not in clean and _SAFE.fullmatch(clean):
                safe_props[key] = clean
    return {
        "event": event_name,
        "source": source,
        "page": page,
        "session_id": hashlib.sha256(session_id.lower().encode("utf-8")).hexdigest() if session_id else None,
        **sanitize_utm(payload.get("utm")),
        "properties": safe_props,
    }


class _FileStore:
    backend = "file"

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def record(self, event: dict[str, Any]) -> None:
        with _LOCK:
            self.rows.append({**event, "created_at": datetime.now(timezone.utc).isoformat()})

    def summary(self, days: int = 30) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc).timestamp() - max(1, min(days, 180)) * 86400
        with _LOCK:
            rows = [row for row in self.rows if datetime.fromisoformat(row["created_at"]).timestamp() >= cutoff]
        return _summary(rows, days)


class _PostgresStore:
    backend = "postgres"

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._ready = False
        self._ready_lock = threading.Lock()

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def ensure_schema(self) -> None:
        with self._ready_lock:
            if self._ready:
                return
            with self._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS migration_marketing_events (
                      id BIGSERIAL PRIMARY KEY,
                      event_name TEXT NOT NULL,
                      source TEXT NOT NULL,
                      page TEXT NOT NULL,
                      session_hash TEXT,
                      utm_source TEXT NOT NULL DEFAULT '',
                      utm_medium TEXT NOT NULL DEFAULT '',
                      utm_campaign TEXT NOT NULL DEFAULT '',
                      utm_content TEXT NOT NULL DEFAULT '',
                      properties JSONB NOT NULL DEFAULT '{}'::jsonb,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS migration_marketing_events_date_idx
                      ON migration_marketing_events (created_at DESC);
                    CREATE INDEX IF NOT EXISTS migration_marketing_events_funnel_idx
                      ON migration_marketing_events (utm_source, event_name, created_at DESC);
                """)
                conn.commit()
            self._ready = True

    def record(self, event: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO migration_marketing_events
                  (event_name, source, page, session_hash, utm_source, utm_medium,
                   utm_campaign, utm_content, properties)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                event["event"], event["source"], event["page"], event["session_id"],
                event.get("utm_source", ""), event.get("utm_medium", ""),
                event.get("utm_campaign", ""), event.get("utm_content", ""),
                Jsonb(event["properties"]),
            ))
            conn.execute("DELETE FROM migration_marketing_events WHERE created_at < NOW() - INTERVAL '180 days'")
            conn.commit()

    def summary(self, days: int = 30) -> dict[str, Any]:
        self.ensure_schema()
        bounded_days = max(1, min(int(days), 180))
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT event_name AS event,
                       COALESCE(NULLIF(utm_source, ''), '(direct)') AS traffic_source,
                       COUNT(*) AS events,
                       COUNT(DISTINCT session_hash) AS sessions,
                       ARRAY_AGG(DISTINCT source ORDER BY source) AS origins
                FROM migration_marketing_events
                WHERE created_at >= NOW() - (%s * INTERVAL '1 day')
                GROUP BY event_name, traffic_source
                ORDER BY traffic_source, event_name
            """, (bounded_days,)).fetchall()
            funnel_rows = conn.execute("""
                SELECT traffic_source,
                       COUNT(*) FILTER (WHERE audit_completed) AS audit_sessions,
                       COUNT(*) FILTER (WHERE audit_completed AND email_requested) AS email_sessions,
                       COUNT(*) FILTER (WHERE audit_completed AND trial_started) AS trial_sessions,
                       ROUND(AVG(EXTRACT(EPOCH FROM (blocker_at - analysis_at)))
                         FILTER (WHERE analysis_at IS NOT NULL
                           AND blocker_at IS NOT NULL AND blocker_at >= analysis_at))
                         AS avg_seconds_to_first_blocker
                FROM (
                  SELECT COALESCE(NULLIF(utm_source, ''), '(direct)') AS traffic_source,
                         session_hash,
                         BOOL_OR(event_name = 'free_audit_completed') AS audit_completed,
                         BOOL_OR(event_name = 'free_audit_email_requested') AS email_requested,
                         BOOL_OR(event_name = 'trial_started') AS trial_started,
                         MIN(created_at) FILTER (WHERE event_name = 'first_analysis_completed') AS analysis_at,
                         MIN(created_at) FILTER (WHERE event_name = 'first_blocker_viewed') AS blocker_at
                  FROM migration_marketing_events
                  WHERE created_at >= NOW() - (%s * INTERVAL '1 day')
                    AND session_hash IS NOT NULL
                  GROUP BY traffic_source, session_hash
                ) AS session_events
                GROUP BY traffic_source
                ORDER BY traffic_source
            """, (bounded_days,)).fetchall()
        return _attach_visit_conversion(
            [dict(row) for row in rows], bounded_days,
            audit_funnel=[dict(row) for row in funnel_rows],
        )


def set_store_for_tests(store: Any | None) -> None:
    global _TEST_STORE
    _TEST_STORE = store


def get_store() -> Any:
    global _STORE
    if _TEST_STORE is not None:
        return _TEST_STORE
    database_url = migration_database_url()
    if database_url:
        if not isinstance(_STORE, _PostgresStore) or _STORE.database_url != database_url:
            _STORE = _PostgresStore(database_url)
        return _STORE
    if not allow_ephemeral_file_store():
        raise PersistenceNotConfiguredError("Marketing analytics storage is not configured for this deployment.")
    if not isinstance(_STORE, _FileStore):
        _STORE = _FileStore()
    return _STORE


def record_event(payload: Any) -> bool:
    event = validate_event(payload)
    if event is None:
        return False
    try:
        get_store().record(event)
        return True
    except PersistenceNotConfiguredError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MarketingAnalyticsError("The analytics event could not be stored.") from exc


def _summary(rows: list[dict[str, Any]], days: int) -> dict[str, Any]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    sessions: dict[tuple[str, str], set[str]] = {}
    origins: dict[tuple[str, str], set[str]] = {}
    session_events: dict[tuple[str, str], set[str]] = {}
    event_times: dict[tuple[str, str], dict[str, datetime]] = {}
    for row in rows:
        key = (row.get("event", ""), row.get("utm_source") or "(direct)")
        group = grouped.setdefault(
            key,
            {
                "event": key[0],
                "traffic_source": key[1],
                "events": 0,
                "sessions": 0,
                "origins": [],
            },
        )
        group["events"] += 1
        session = row.get("session_id")
        if session:
            sessions.setdefault(key, set()).add(session)
            if row.get("event") in {
                "free_audit_completed", "free_audit_email_requested", "trial_started"
            }:
                session_events.setdefault((key[1], session), set()).add(str(row.get("event")))
            event = str(row.get("event") or "")
            if event in {"first_analysis_completed", "first_blocker_viewed"}:
                try:
                    stamp = datetime.fromisoformat(
                        str(row.get("created_at")).replace("Z", "+00:00")
                    )
                except (TypeError, ValueError):
                    stamp = None
                if stamp is not None:
                    event_times.setdefault((key[1], session), {})[event] = stamp
        origin = str(row.get("source") or "").strip()
        if origin:
            origins.setdefault(key, set()).add(origin)
    for key, group in grouped.items():
        group["sessions"] = len(sessions.get(key, set()))
        group["origins"] = sorted(origins.get(key, set()))
    funnel: dict[str, dict[str, int]] = {}
    for (source, _session), events in session_events.items():
        if "free_audit_completed" not in events:
            continue
        counts = funnel.setdefault(
            source, {"audit_sessions": 0, "email_sessions": 0, "trial_sessions": 0}
        )
        counts["audit_sessions"] += 1
        if "free_audit_email_requested" in events:
            counts["email_sessions"] += 1
        if "trial_started" in events:
            counts["trial_sessions"] += 1
    first_value_latency: dict[str, list[float]] = {}
    for (source, _session), timestamps in event_times.items():
        start = timestamps.get("first_analysis_completed")
        end = timestamps.get("first_blocker_viewed")
        if start and end and end >= start:
            first_value_latency.setdefault(source, []).append((end - start).total_seconds())
    for source in first_value_latency:
        funnel.setdefault(source, {"audit_sessions": 0, "email_sessions": 0, "trial_sessions": 0})
    audit_funnel = [
        {
            "traffic_source": source,
            **counts,
            "avg_seconds_to_first_blocker": (
                round(sum(first_value_latency[source]) / len(first_value_latency[source]))
                if first_value_latency.get(source) else None
            ),
        }
        for source, counts in sorted(funnel.items())
    ]
    return _attach_visit_conversion(list(grouped.values()), days, audit_funnel=audit_funnel)


def _attach_visit_conversion(
    rows: list[dict[str, Any]],
    days: int,
    *,
    audit_funnel: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Add unique page-view session counts and visit conversion rates by source."""
    visits_by_source = {
        str(row.get("traffic_source") or "(direct)"): int(row.get("sessions") or 0)
        for row in rows
        if row.get("event") == "page_view"
    }
    enriched: list[dict[str, Any]] = []
    for row in rows:
        source = str(row.get("traffic_source") or "(direct)")
        visits = visits_by_source.get(source, 0)
        sessions = int(row.get("sessions") or 0)
        enriched.append({
            **row,
            "visit_sessions": visits,
            "conversion_from_visit_pct": (
                round(sessions / visits * 100, 1)
                if visits and row.get("event") != "page_view"
                else None
            ),
        })
    enriched.sort(key=lambda row: (str(row.get("traffic_source") or ""), str(row.get("event") or "")))
    if audit_funnel is None:
        session_events: dict[tuple[str, str], set[str]] = {}
        for row in rows:
            session = row.get("session_id")
            if not session:
                continue
            source = str(row.get("utm_source") or row.get("traffic_source") or "(direct)")
            event = str(row.get("event") or "")
            if event in {"free_audit_completed", "free_audit_email_requested", "trial_started"}:
                session_events.setdefault((source, session), set()).add(event)
        sessions_by_source: dict[str, dict[str, Any]] = {}
        for (source, _session), events in session_events.items():
            counts = sessions_by_source.setdefault(
                source, {"audit_sessions": 0, "email_sessions": 0, "trial_sessions": 0}
            )
            if "free_audit_completed" in events:
                counts["audit_sessions"] += 1
                if "free_audit_email_requested" in events:
                    counts["email_sessions"] += 1
                if "trial_started" in events:
                    counts["trial_sessions"] += 1
        audit_funnel = [
            {"traffic_source": source, **counts}
            for source, counts in sorted(sessions_by_source.items())
        ]
    funnel_by_source = []
    for row in audit_funnel:
        audit_sessions = int(row.get("audit_sessions") or 0)
        email_sessions = int(row.get("email_sessions") or 0)
        trial_sessions = int(row.get("trial_sessions") or 0)
        funnel_by_source.append({
            "traffic_source": str(row.get("traffic_source") or "(direct)"),
            "audit_sessions": audit_sessions,
            "email_sessions": email_sessions,
            "trial_sessions": trial_sessions,
            "audit_to_email_pct": round(email_sessions / audit_sessions * 100, 1) if audit_sessions else None,
            "audit_to_trial_pct": round(trial_sessions / audit_sessions * 100, 1) if audit_sessions else None,
            "avg_seconds_to_first_blocker": (
                int(row["avg_seconds_to_first_blocker"])
                if row.get("avg_seconds_to_first_blocker") is not None else None
            ),
        })
    return {
        "ok": True,
        "days": days,
        "rows": enriched,
        "audit_funnel_by_source": funnel_by_source,
        "retention_days": 180,
        "conversion_basis": "same anonymous session, completed audit as denominator; consented analytics only",
    }

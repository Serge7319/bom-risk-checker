"""Persist accepted Terms of Service / Privacy Policy versions at signup."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Canonical published versions — keep in sync with marketing-web legal pages.
TERMS_VERSION = "cadivor.com-terms-v1"
PRIVACY_VERSION = "cadivor.com-privacy-v1"
TERMS_URL = "https://www.cadivor.com/#/terms"
PRIVACY_URL = "https://www.cadivor.com/#/privacy"

_LOCK = threading.RLock()
_MEMORY: list[dict[str, Any]] = []


def published_versions() -> dict[str, str]:
    return {
        "terms_version": TERMS_VERSION,
        "privacy_version": PRIVACY_VERSION,
        "terms_url": TERMS_URL,
        "privacy_url": PRIVACY_URL,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _database_url() -> str:
    return (os.environ.get("CADIVOR_MIGRATION_DATABASE_URL") or "").strip()


def _file_path() -> Path | None:
    raw = (os.environ.get("CADIVOR_LEGAL_ACCEPTANCE_PATH") or "").strip()
    if raw:
        return Path(raw)
    data = (os.environ.get("CADIVOR_SANDBOX_DATA_DIR") or "").strip()
    if data:
        return Path(data) / "legal_acceptances.json"
    return None


def reset_legal_acceptances_for_tests() -> None:
    with _LOCK:
        _MEMORY.clear()
        path = _file_path()
        if path and path.exists():
            path.unlink()


def record_acceptance(
    *,
    email: str,
    source: str,
    terms_version: str | None = None,
    privacy_version: str | None = None,
    user_id: str | None = None,
    workspace_name: str | None = None,
) -> dict[str, Any]:
    email_n = (email or "").strip().lower()
    if not email_n:
        raise ValueError("email required")
    row = {
        "id": f"legal-{len(_MEMORY)+1}-{int(datetime.now(timezone.utc).timestamp())}",
        "email": email_n,
        "user_id": user_id,
        "workspace_name": workspace_name,
        "source": source,
        "terms_version": (terms_version or TERMS_VERSION).strip() or TERMS_VERSION,
        "privacy_version": (privacy_version or PRIVACY_VERSION).strip()
        or PRIVACY_VERSION,
        "accepted_at": utc_now(),
    }
    db_url = _database_url()
    if db_url:
        _record_postgres(db_url, row)
        return row
    with _LOCK:
        _MEMORY.append(dict(row))
        path = _file_path()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            existing: list[dict[str, Any]] = []
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    existing = []
            if not isinstance(existing, list):
                existing = []
            existing.append(dict(row))
            path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return row


def list_acceptances(*, email: str | None = None) -> list[dict[str, Any]]:
    email_n = (email or "").strip().lower()
    db_url = _database_url()
    if db_url:
        return _list_postgres(db_url, email_n or None)
    with _LOCK:
        rows = list(_MEMORY)
        path = _file_path()
        if path and path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    rows = loaded
            except Exception:  # noqa: BLE001
                pass
        if email_n:
            return [r for r in rows if str(r.get("email") or "").lower() == email_n]
        return list(rows)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS migration_legal_acceptances (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  user_id TEXT,
  workspace_name TEXT,
  source TEXT NOT NULL,
  terms_version TEXT NOT NULL,
  privacy_version TEXT NOT NULL,
  accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS migration_legal_acceptances_email_idx
  ON migration_legal_acceptances (lower(email), accepted_at DESC);
"""


def ensure_schema(database_url: str | None = None) -> None:
    url = (database_url or _database_url()).strip()
    if not url:
        return
    import psycopg

    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA)
        conn.commit()


def _record_postgres(database_url: str, row: dict[str, Any]) -> None:
    import psycopg

    ensure_schema(database_url)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO migration_legal_acceptances
                  (id, email, user_id, workspace_name, source, terms_version, privacy_version, accepted_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::timestamptz)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    row["id"],
                    row["email"],
                    row.get("user_id"),
                    row.get("workspace_name"),
                    row["source"],
                    row["terms_version"],
                    row["privacy_version"],
                    row["accepted_at"],
                ),
            )
        conn.commit()


def _list_postgres(database_url: str, email: str | None) -> list[dict[str, Any]]:
    import psycopg
    from psycopg.rows import dict_row

    ensure_schema(database_url)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            if email:
                cur.execute(
                    """
                    SELECT id, email, user_id, workspace_name, source,
                           terms_version, privacy_version, accepted_at
                    FROM migration_legal_acceptances
                    WHERE lower(email) = lower(%s)
                    ORDER BY accepted_at DESC
                    """,
                    (email,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, email, user_id, workspace_name, source,
                           terms_version, privacy_version, accepted_at
                    FROM migration_legal_acceptances
                    ORDER BY accepted_at DESC
                    LIMIT 200
                    """
                )
            rows = list(cur.fetchall() or [])
    out = []
    for row in rows:
        item = dict(row)
        if hasattr(item.get("accepted_at"), "isoformat"):
            item["accepted_at"] = item["accepted_at"].isoformat()
        out.append(item)
    return out

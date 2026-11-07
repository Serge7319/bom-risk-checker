"""Persist accepted Terms of Service / Privacy Policy versions at signup."""

from __future__ import annotations

import json
import os
import threading
import uuid
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


class LegalAcceptanceError(Exception):
    """Handled consent failure — callers must not create accounts after this."""

    def __init__(self, detail: str, *, status_code: int = 503, code: str = "consent_storage_failed"):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.code = code


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


def _ephemeral_consent_allowed() -> bool:
    """Local/test memory+file consent only when explicitly opted in.

    Unlike workspace_store.allow_ephemeral_file_store(), this does not treat
    "no Railway env" as permission to store production consent in memory.
    """
    return (os.environ.get("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE") or "").strip() == "1"


def _file_path() -> Path | None:
    """File-backed consent store for local tests only (ephemeral flag required)."""
    if not _ephemeral_consent_allowed():
        return None
    raw = (os.environ.get("CADIVOR_LEGAL_ACCEPTANCE_PATH") or "").strip()
    if raw:
        return Path(raw)
    data = (os.environ.get("CADIVOR_SANDBOX_DATA_DIR") or "").strip()
    if data:
        return Path(data) / "legal_acceptances.json"
    return None


def durable_storage_available() -> bool:
    """True when consent can be stored in Postgres or an explicit test store."""
    if _database_url():
        return True
    return _ephemeral_consent_allowed()


def require_durable_storage() -> None:
    if durable_storage_available():
        return
    raise LegalAcceptanceError(
        "Cadivor could not record Terms acceptance because durable consent storage is unavailable. Account creation was not started.",
        status_code=503,
        code="consent_storage_unavailable",
    )


def canonical_versions(
    terms_version: str | None = None,
    privacy_version: str | None = None,
) -> tuple[str, str]:
    """Return server canonical versions; reject forged client values."""
    terms = (terms_version or "").strip()
    privacy = (privacy_version or "").strip()
    if terms and terms != TERMS_VERSION:
        raise LegalAcceptanceError(
            "The Terms of Service version does not match Cadivor's published terms. Refresh the page and try again.",
            status_code=400,
            code="terms_version_mismatch",
        )
    if privacy and privacy != PRIVACY_VERSION:
        raise LegalAcceptanceError(
            "The Privacy Policy version does not match Cadivor's published policy. Refresh the page and try again.",
            status_code=400,
            code="privacy_version_mismatch",
        )
    return TERMS_VERSION, PRIVACY_VERSION


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
    """Persist consent. Uses UUID ids. Fails closed when durable storage is missing."""
    require_durable_storage()
    email_n = (email or "").strip().lower()
    if not email_n:
        raise LegalAcceptanceError(
            "Cadivor could not record Terms acceptance because the email address was missing.",
            status_code=400,
            code="consent_email_required",
        )
    terms_v, privacy_v = canonical_versions(terms_version, privacy_version)
    row = {
        "id": str(uuid.uuid4()),
        "email": email_n,
        "user_id": user_id,
        "workspace_name": workspace_name,
        "source": source,
        "terms_version": terms_v,
        "privacy_version": privacy_v,
        "accepted_at": utc_now(),
    }
    db_url = _database_url()
    if db_url:
        try:
            _record_postgres(db_url, row)
        except LegalAcceptanceError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LegalAcceptanceError(
                "Cadivor could not record Terms acceptance. Account creation was not started.",
                status_code=503,
                code="consent_storage_failed",
            ) from exc
        return row

    # Local / test ephemeral path only (_ephemeral_consent_allowed already required).
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
    if not _ephemeral_consent_allowed():
        return []
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



def find_recent_acceptance(
    *,
    email: str,
    source: str,
    terms_version: str,
    privacy_version: str,
    max_age_seconds: int = 24 * 60 * 60,
) -> dict[str, Any] | None:
    """Return a recent matching acceptance to avoid unlimited audit rows on retries."""
    email_n = (email or "").strip().lower()
    if not email_n:
        return None
    now = datetime.now(timezone.utc)
    for row in list_acceptances(email=email_n):
        if str(row.get("source") or "") != source:
            continue
        if str(row.get("terms_version") or "") != terms_version:
            continue
        if str(row.get("privacy_version") or "") != privacy_version:
            continue
        raw = str(row.get("accepted_at") or "")
        try:
            accepted = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if accepted.tzinfo is None:
            accepted = accepted.replace(tzinfo=timezone.utc)
        if (now - accepted).total_seconds() <= max_age_seconds:
            return row
    return None


def record_acceptance_for_signup(
    *,
    email: str,
    source: str,
    terms_version: str | None = None,
    privacy_version: str | None = None,
    user_id: str | None = None,
    workspace_name: str | None = None,
) -> dict[str, Any]:
    """Record consent once per email/source/versions window; optionally attach user_id.

    Identity policy:
    - Prefer ``user_id`` when the auth provider returns one at signup time.
    - Otherwise the durable audit identity is the normalized email address
      (email-only) until a later verified login can attach ``user_id``.
    """
    terms_v, privacy_v = canonical_versions(terms_version, privacy_version)
    existing = find_recent_acceptance(
        email=email,
        source=source,
        terms_version=terms_v,
        privacy_version=privacy_v,
    )
    if existing:
        if user_id and not existing.get("user_id"):
            return attach_user_id(acceptance_id=str(existing["id"]), user_id=user_id) or existing
        return existing
    return record_acceptance(
        email=email,
        source=source,
        terms_version=terms_v,
        privacy_version=privacy_v,
        user_id=user_id,
        workspace_name=workspace_name,
    )


def attach_user_id(*, acceptance_id: str, user_id: str) -> dict[str, Any] | None:
    """Link a stored acceptance to the created auth user when known."""
    user_n = (user_id or "").strip()
    if not acceptance_id or not user_n:
        return None
    db_url = _database_url()
    if db_url:
        import psycopg

        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE migration_legal_acceptances
                    SET user_id = %s
                    WHERE id = %s
                    RETURNING id, email, user_id, workspace_name, source,
                              terms_version, privacy_version, accepted_at
                    """,
                    (user_n, acceptance_id),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            return None
        keys = [
            "id",
            "email",
            "user_id",
            "workspace_name",
            "source",
            "terms_version",
            "privacy_version",
            "accepted_at",
        ]
        return {keys[i]: row[i] for i in range(len(keys))}

    if not _ephemeral_consent_allowed():
        return None
    with _LOCK:
        for row in _MEMORY:
            if str(row.get("id")) == acceptance_id:
                row["user_id"] = user_n
                path = _file_path()
                if path and path.exists():
                    try:
                        loaded = json.loads(path.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        loaded = list(_MEMORY)
                    if isinstance(loaded, list):
                        for item in loaded:
                            if str(item.get("id")) == acceptance_id:
                                item["user_id"] = user_n
                        path.write_text(json.dumps(loaded, indent=2), encoding="utf-8")
                return dict(row)
    return None


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
CREATE INDEX IF NOT EXISTS migration_legal_acceptances_user_id_idx
  ON migration_legal_acceptances (user_id)
  WHERE user_id IS NOT NULL;
"""


_SCHEMA_SECURITY = """
ALTER TABLE migration_legal_acceptances ENABLE ROW LEVEL SECURITY;
ALTER TABLE migration_legal_acceptances FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE migration_legal_acceptances FROM PUBLIC;
"""


def ensure_schema(database_url: str | None = None) -> None:
    url = (database_url or _database_url()).strip()
    if not url:
        return
    import psycopg

    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA)
            try:
                cur.execute(_SCHEMA_SECURITY)
            except Exception:
                # Disposable Postgres roles may lack FORCE RLS; table DDL still applied.
                conn.rollback()
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
            if cur.rowcount != 1:
                raise LegalAcceptanceError(
                    "Cadivor could not record Terms acceptance. Account creation was not started.",
                    status_code=503,
                    code="consent_storage_failed",
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

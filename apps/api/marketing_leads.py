"""Durable intake for public Cadivor contact, demo, and student requests.

Production records use the migration Postgres database. The local file store is
available only in local preview/tests; a deployed service never silently loses
submissions into ephemeral storage.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.api.workspace_store import (
    PersistenceNotConfiguredError,
    allow_ephemeral_file_store,
    migration_database_url,
)

_LOCK = threading.RLock()
CONTACT_CONSENT_VERSION = "contact-request-v1"
_DEFAULT_PATH = Path(
    os.environ.get(
        "CADIVOR_MARKETING_LEAD_STORE",
        str(
            Path(__file__).resolve().parents[2]
            / ".evidence"
            / "nextjs_migration"
            / "marketing_leads.json"
        ),
    )
)


class MarketingLeadError(RuntimeError):
    """Raised when a public request cannot be stored durably."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict[str, Any]:
    return {"version": 1, "leads": {}}


class FileMarketingLeadStore:
    """Small local/test store; never used as a deployed fallback."""

    backend = "file"

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else _DEFAULT_PATH
        self._data = _empty()
        self._load()

    def _load(self) -> None:
        with _LOCK:
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("leads"), dict):
                    self._data = loaded
            except (OSError, json.JSONDecodeError):
                self._data = _empty()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def create_submission(self, fields: dict[str, Any]) -> dict[str, Any]:
        with _LOCK:
            row = {
                "id": str(uuid.uuid4()),
                "created_at": _now(),
                "notification_status": "pending",
                **fields,
            }
            self._data.setdefault("leads", {})[row["id"]] = row
            self._save()
            return dict(row)

    def update_notification(self, lead_id: str, status: str) -> None:
        with _LOCK:
            row = self._data.setdefault("leads", {}).get(str(lead_id))
            if not row:
                return
            row["notification_status"] = status
            row["notified_at"] = _now() if status == "sent" else None
            self._save()

    def clear(self) -> None:
        with _LOCK:
            self._data = _empty()
            self._save()


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS migration_marketing_leads (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  company TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT '',
  team_size TEXT NOT NULL DEFAULT '',
  bom_volume TEXT NOT NULL DEFAULT '',
  plan_interest TEXT NOT NULL DEFAULT '',
  topic TEXT NOT NULL,
  message TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '',
  utm JSONB NOT NULL DEFAULT '{}'::jsonb,
  notification_status TEXT NOT NULL DEFAULT 'pending',
  consent_version TEXT NOT NULL DEFAULT 'contact-request-v1',
  consented_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  notified_at TIMESTAMPTZ
);
ALTER TABLE migration_marketing_leads
  ADD COLUMN IF NOT EXISTS plan_interest TEXT NOT NULL DEFAULT '';
ALTER TABLE migration_marketing_leads
  ADD COLUMN IF NOT EXISTS consent_version TEXT NOT NULL DEFAULT 'contact-request-v1';
ALTER TABLE migration_marketing_leads
  ADD COLUMN IF NOT EXISTS consented_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
CREATE INDEX IF NOT EXISTS migration_marketing_leads_created_idx
  ON migration_marketing_leads (created_at DESC);
CREATE INDEX IF NOT EXISTS migration_marketing_leads_topic_idx
  ON migration_marketing_leads (topic, created_at DESC);
"""


class PostgresMarketingLeadStore:
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
                conn.execute(_SCHEMA_SQL)
                conn.commit()
            self._ready = True

    def create_submission(self, fields: dict[str, Any]) -> dict[str, Any]:
        from psycopg.types.json import Jsonb

        self.ensure_schema()
        lead_id = str(uuid.uuid4())
        with self._connect() as conn:
            row = conn.execute(
                """INSERT INTO migration_marketing_leads
                   (id, name, email, company, role, team_size, bom_volume,
                    plan_interest, topic, message, source, utm, notification_status,
                    consent_version, consented_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           'pending', %s, %s)
                   RETURNING id, created_at, consented_at""",
                (
                    lead_id,
                    fields["name"],
                    fields["email"],
                    fields["company"],
                    fields["role"],
                    fields["team_size"],
                    fields["bom_volume"],
                    fields["plan_interest"],
                    fields["topic"],
                    fields["message"],
                    fields["source"],
                    Jsonb(fields["utm"]),
                    fields["consent_version"],
                    fields["consented_at"],
                ),
            ).fetchone()
            conn.commit()
        return {
            "id": lead_id,
            "created_at": row["created_at"],
            "consented_at": row["consented_at"],
            **fields,
        }

    def update_notification(self, lead_id: str, status: str) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """UPDATE migration_marketing_leads
                   SET notification_status = %s,
                       notified_at = CASE WHEN %s = 'sent' THEN NOW() ELSE NULL END
                   WHERE id = %s""",
                (status, status, str(lead_id)),
            )
            conn.commit()


_STORE: Any | None = None
_TEST_STORE: Any | None = None


def set_store_for_tests(store: Any | None) -> None:
    """Install an isolated store for tests without changing production wiring."""
    global _TEST_STORE
    _TEST_STORE = store


def get_store() -> Any:
    global _STORE
    if _TEST_STORE is not None:
        return _TEST_STORE
    database_url = migration_database_url()
    if database_url:
        if not isinstance(_STORE, PostgresMarketingLeadStore) or _STORE.database_url != database_url:
            _STORE = PostgresMarketingLeadStore(database_url)
        return _STORE
    if not allow_ephemeral_file_store():
        raise PersistenceNotConfiguredError(
            "Marketing request storage is not configured for this deployment."
        )
    if not isinstance(_STORE, FileMarketingLeadStore):
        _STORE = FileMarketingLeadStore()
    return _STORE


def create_submission(fields: dict[str, Any]) -> dict[str, Any]:
    try:
        stamped = {
            "consent_version": CONTACT_CONSENT_VERSION,
            "consented_at": _now(),
            **fields,
        }
        return get_store().create_submission(stamped)
    except PersistenceNotConfiguredError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MarketingLeadError("The request could not be saved.") from exc


def update_notification(lead_id: str, status: str) -> None:
    try:
        get_store().update_notification(lead_id, status)
    except Exception as exc:  # noqa: BLE001
        raise MarketingLeadError("The notification status could not be saved.") from exc


def contact_inbox(topic: str | None = None) -> str:
    from src.email_routing import resolve_inbox

    return str(os.environ.get("CADIVOR_CONTACT_INBOX") or resolve_inbox(topic)).strip()


def send_contact_notification(lead: dict[str, Any]) -> None:
    """Notify Cadivor's shared inbox; no submitter confirmation email is sent."""
    import html

    from src.email_delivery import (
        EmailDeliveryError,
        email_delivery_configured,
        send_transactional_email,
    )

    if not email_delivery_configured():
        raise EmailDeliveryError("Contact email delivery is not configured.")
    topic = str(lead.get("topic") or "general").replace("-", " ").title()
    fields = (
        ("Name", lead.get("name")),
        ("Work email", lead.get("email")),
        ("Company", lead.get("company")),
        ("Role", lead.get("role")),
        ("Team size", lead.get("team_size")),
        ("BOM volume", lead.get("bom_volume")),
        ("Plan interest", lead.get("plan_interest")),
        ("Topic", topic),
        ("Source", lead.get("source")),
    )
    rows = "".join(
        f"<tr><th align=\"left\">{html.escape(str(label))}</th>"
        f"<td>{html.escape(str(value or '—'))}</td></tr>"
        for label, value in fields
    )
    message_html = html.escape(str(lead.get("message") or "")).replace("\n", "<br>")
    subject_name = " ".join(str(lead.get("name") or "").split())[:80]
    return send_transactional_email(
        to_email=contact_inbox(str(lead.get("topic") or "general")),
        reply_to=str(lead.get("email") or ""),
        subject=f"Cadivor {topic} request — {subject_name}",
        html_body=(
            "<div style=\"font-family:Arial,sans-serif;color:#15345d;line-height:1.5\">"
            f"<h2>New Cadivor {html.escape(topic.lower())} request</h2>"
            f"<table cellpadding=\"8\" cellspacing=\"0\">{rows}</table>"
            f"<h3>Message</h3><p>{message_html}</p></div>"
        ),
        text_body=(
            f"New Cadivor {topic} request\n\n"
            + "\n".join(f"{label}: {value or '—'}" for label, value in fields)
            + f"\n\nMessage:\n{lead.get('message', '')}"
        ),
    )

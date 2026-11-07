"""Team data for the Next app: invitations, workspace settings, profile, preferences.

Lives in the same dedicated migration database as workspace membership
(``CADIVOR_MIGRATION_DATABASE_URL``) so invitation acceptance and the
membership write share one authority. File storage is limited to local/tests
(same rules as ``workspace_store``). Never touches the Streamlit Supabase
``workspace_*`` tables.

Invitation tokens are stored only as SHA-256 hashes; the raw token exists in
the invitation email link alone.
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
_DEFAULT_PATH = Path(
    os.environ.get(
        "CADIVOR_TEAM_STORE",
        str(
            Path(__file__).resolve().parents[2]
            / ".evidence"
            / "nextjs_migration"
            / "team_store.json"
        ),
    )
)

INVITE_FIELDS = (
    "status",
    "role",
    "token_hash",
    "updated_at",
    "expires_at",
    "accepted_at",
    "accepted_by",
    "last_sent_at",
    "send_count",
)
PROFILE_FIELDS = (
    "full_name",
    "company_name",
    "job_title",
    "country",
    "language",
    "timezone",
)
PREFERENCE_FIELDS = (
    "appearance",
    "density",
    "default_units",
    "default_currency",
    "monitoring_notifications",
    "notification_preferences",
)
WORKSPACE_FIELDS = ("name", "timezone", "unit_system", "owner_id")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return value


def _clean_row(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    return {key: _iso(value) for key, value in dict(row).items()}


def _empty() -> dict[str, Any]:
    return {
        "version": 1,
        "workspaces": {},
        "invites": {},
        "activity": [],
        "profiles": {},
        "preferences": {},
    }


class TeamStore:
    """Interface documentation; see File/Postgres implementations."""

    backend = "abstract"


class FileTeamStore(TeamStore):
    backend = "file"
    durable_across_redeploy = False

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else _DEFAULT_PATH
        self._data = _empty()
        self.load()

    def load(self) -> None:
        with _LOCK:
            data = _empty()
            if self.path.exists():
                try:
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        data.update(loaded)
                except (OSError, json.JSONDecodeError):
                    pass
            for key, default in _empty().items():
                if not isinstance(data.get(key), type(default)):
                    data[key] = default
            self._data = data

    def save(self) -> None:
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def clear(self) -> None:
        with _LOCK:
            self._data = _empty()
            self.save()

    # -- workspaces ------------------------------------------------------
    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        with _LOCK:
            row = self._data["workspaces"].get(workspace_id)
            return dict(row) if row else None

    def upsert_workspace(self, workspace_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        with _LOCK:
            row = self._data["workspaces"].get(workspace_id) or {
                "workspace_id": workspace_id,
                "created_at": _now(),
            }
            for key in WORKSPACE_FIELDS:
                if key in fields and fields[key] is not None:
                    row[key] = fields[key]
            row["updated_at"] = _now()
            self._data["workspaces"][workspace_id] = row
            self.save()
            return dict(row)

    # -- invitations -----------------------------------------------------
    def create_invite(self, row: dict[str, Any]) -> dict[str, Any]:
        with _LOCK:
            email = str(row["email"]).lower()
            for existing in self._data["invites"].values():
                if (
                    existing["workspace_id"] == row["workspace_id"]
                    and existing["email"] == email
                    and existing["status"] == "pending"
                ):
                    raise ValueError("pending_invite_exists")
            invite_id = str(row.get("id") or uuid.uuid4())
            saved = {
                "accepted_at": None,
                "accepted_by": None,
                "last_sent_at": None,
                "send_count": 0,
                **row,
                "id": invite_id,
                "email": email,
            }
            self._data["invites"][invite_id] = saved
            self.save()
            return dict(saved)

    def get_invite(self, invite_id: str) -> dict[str, Any] | None:
        with _LOCK:
            row = self._data["invites"].get(invite_id)
            return dict(row) if row else None

    def find_invite_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        with _LOCK:
            for row in self._data["invites"].values():
                if row.get("token_hash") == token_hash:
                    return dict(row)
        return None

    def list_invites(self, workspace_id: str) -> list[dict[str, Any]]:
        with _LOCK:
            rows = [
                dict(row)
                for row in self._data["invites"].values()
                if row.get("workspace_id") == workspace_id
            ]
        return sorted(rows, key=lambda r: str(r.get("created_at") or ""), reverse=True)

    def find_pending_invite(self, workspace_id: str, email: str) -> dict[str, Any] | None:
        email_n = email.strip().lower()
        with _LOCK:
            for row in self._data["invites"].values():
                if (
                    row["workspace_id"] == workspace_id
                    and row["email"] == email_n
                    and row["status"] == "pending"
                ):
                    return dict(row)
        return None

    def list_pending_for_email(self, email: str) -> list[dict[str, Any]]:
        email_n = email.strip().lower()
        with _LOCK:
            rows = [
                dict(row)
                for row in self._data["invites"].values()
                if row["email"] == email_n and row["status"] == "pending"
            ]
        return sorted(rows, key=lambda r: str(r.get("created_at") or ""))

    def update_invite(
        self,
        invite_id: str,
        fields: dict[str, Any],
        *,
        expect_status: str | None = None,
    ) -> dict[str, Any] | None:
        """Compare-and-set update; returns None when the guard does not match."""
        with _LOCK:
            row = self._data["invites"].get(invite_id)
            if not row:
                return None
            if expect_status is not None and row.get("status") != expect_status:
                return None
            for key, value in fields.items():
                if key in INVITE_FIELDS:
                    row[key] = value
            self.save()
            return dict(row)

    # -- activity --------------------------------------------------------
    def add_activity(self, row: dict[str, Any]) -> None:
        with _LOCK:
            self._data["activity"].append(
                {
                    "id": str(uuid.uuid4()),
                    "created_at": _now(),
                    "metadata": {},
                    **row,
                }
            )
            # Bounded history keeps the preview file small.
            if len(self._data["activity"]) > 5000:
                self._data["activity"] = self._data["activity"][-5000:]
            self.save()

    def list_activity(self, workspace_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with _LOCK:
            rows = [
                dict(row)
                for row in self._data["activity"]
                if row.get("workspace_id") == workspace_id
            ]
        rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return rows[: max(1, int(limit))]

    # -- profile / preferences -------------------------------------------
    def get_profile(self, user_id: str) -> dict[str, Any] | None:
        with _LOCK:
            row = self._data["profiles"].get(user_id)
            return dict(row) if row else None

    def get_profiles(self, user_ids: list[str]) -> dict[str, dict[str, Any]]:
        with _LOCK:
            return {
                uid: dict(self._data["profiles"][uid])
                for uid in user_ids
                if uid in self._data["profiles"]
            }

    def upsert_profile(self, user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        with _LOCK:
            row = self._data["profiles"].get(user_id) or {
                "user_id": user_id,
                "created_at": _now(),
            }
            for key in PROFILE_FIELDS:
                if key in fields:
                    row[key] = fields[key]
            row["updated_at"] = _now()
            self._data["profiles"][user_id] = row
            self.save()
            return dict(row)

    def get_preferences(self, user_id: str) -> dict[str, Any] | None:
        with _LOCK:
            row = self._data["preferences"].get(user_id)
            return json.loads(json.dumps(row)) if row else None

    def upsert_preferences(self, user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        with _LOCK:
            row = self._data["preferences"].get(user_id) or {
                "user_id": user_id,
                "created_at": _now(),
            }
            for key in PREFERENCE_FIELDS:
                if key in fields:
                    row[key] = fields[key]
            row["updated_at"] = _now()
            self._data["preferences"][user_id] = row
            self.save()
            return json.loads(json.dumps(row))


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS migration_workspaces (
  workspace_id TEXT PRIMARY KEY,
  name TEXT,
  owner_id TEXT,
  timezone TEXT NOT NULL DEFAULT 'UTC',
  unit_system TEXT NOT NULL DEFAULT 'metric',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS migration_workspace_invites (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  email TEXT NOT NULL,
  role TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  token_hash TEXT NOT NULL,
  invited_by TEXT,
  invited_by_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL,
  accepted_at TIMESTAMPTZ,
  accepted_by TEXT,
  last_sent_at TIMESTAMPTZ,
  send_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS migration_ws_invites_ws_idx
  ON migration_workspace_invites (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS migration_ws_invites_email_idx
  ON migration_workspace_invites (lower(email), status);
CREATE UNIQUE INDEX IF NOT EXISTS migration_ws_invites_token_uidx
  ON migration_workspace_invites (token_hash);
CREATE UNIQUE INDEX IF NOT EXISTS migration_ws_invites_pending_uidx
  ON migration_workspace_invites (workspace_id, lower(email))
  WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS migration_workspace_activity (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  actor_id TEXT,
  actor_name TEXT,
  action TEXT NOT NULL,
  summary TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS migration_ws_activity_ws_idx
  ON migration_workspace_activity (workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS migration_customer_profiles (
  user_id TEXT PRIMARY KEY,
  full_name TEXT,
  company_name TEXT,
  job_title TEXT,
  country TEXT,
  language TEXT,
  timezone TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS migration_user_preferences (
  user_id TEXT PRIMARY KEY,
  appearance TEXT,
  density TEXT,
  default_units TEXT,
  default_currency TEXT,
  monitoring_notifications BOOLEAN,
  notification_preferences JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


class PostgresTeamStore(TeamStore):
    backend = "postgres"
    durable_across_redeploy = True

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.path = Path("postgres://migration-postgres")
        self._ready = False

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.database_url, row_factory=dict_row)

    def ensure_schema(self) -> None:
        with _LOCK:
            if self._ready:
                return
            with self._connect() as conn:
                conn.execute(_SCHEMA_SQL)
                conn.commit()
            self._ready = True

    def clear(self) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                "TRUNCATE migration_workspaces, migration_workspace_invites, "
                "migration_workspace_activity, migration_customer_profiles, "
                "migration_user_preferences"
            )
            conn.commit()

    # -- workspaces ------------------------------------------------------
    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn:
            return _clean_row(
                conn.execute(
                    "SELECT * FROM migration_workspaces WHERE workspace_id = %s",
                    (workspace_id,),
                ).fetchone()
            )

    def upsert_workspace(self, workspace_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()
        values = {k: fields[k] for k in WORKSPACE_FIELDS if fields.get(k) is not None}
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO migration_workspaces (workspace_id) VALUES (%s) "
                "ON CONFLICT (workspace_id) DO NOTHING",
                (workspace_id,),
            )
            if values:
                assignments = ", ".join(f"{key} = %s" for key in values)
                conn.execute(
                    f"UPDATE migration_workspaces SET {assignments}, updated_at = NOW() "
                    "WHERE workspace_id = %s",
                    (*values.values(), workspace_id),
                )
            row = conn.execute(
                "SELECT * FROM migration_workspaces WHERE workspace_id = %s",
                (workspace_id,),
            ).fetchone()
            conn.commit()
            return _clean_row(row) or {}

    # -- invitations -----------------------------------------------------
    def create_invite(self, row: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()
        invite_id = str(row.get("id") or uuid.uuid4())
        with self._connect() as conn:
            try:
                saved = conn.execute(
                    """
                    INSERT INTO migration_workspace_invites
                      (id, workspace_id, email, role, status, token_hash, invited_by,
                       invited_by_name, created_at, updated_at, expires_at,
                       last_sent_at, send_count)
                    VALUES (%s, %s, lower(%s), %s, 'pending', %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        invite_id,
                        row["workspace_id"],
                        row["email"],
                        row["role"],
                        row["token_hash"],
                        row.get("invited_by"),
                        row.get("invited_by_name"),
                        row.get("created_at") or _now(),
                        row.get("updated_at") or _now(),
                        row["expires_at"],
                        row.get("last_sent_at"),
                        int(row.get("send_count") or 0),
                    ),
                ).fetchone()
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                if "migration_ws_invites_pending_uidx" in str(exc):
                    raise ValueError("pending_invite_exists") from exc
                raise
            return _clean_row(saved) or {}

    def get_invite(self, invite_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn:
            return _clean_row(
                conn.execute(
                    "SELECT * FROM migration_workspace_invites WHERE id = %s",
                    (invite_id,),
                ).fetchone()
            )

    def find_invite_by_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn:
            return _clean_row(
                conn.execute(
                    "SELECT * FROM migration_workspace_invites WHERE token_hash = %s",
                    (token_hash,),
                ).fetchone()
            )

    def list_invites(self, workspace_id: str) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM migration_workspace_invites WHERE workspace_id = %s "
                "ORDER BY created_at DESC",
                (workspace_id,),
            ).fetchall()
            return [_clean_row(r) or {} for r in rows]

    def find_pending_invite(self, workspace_id: str, email: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn:
            return _clean_row(
                conn.execute(
                    "SELECT * FROM migration_workspace_invites "
                    "WHERE workspace_id = %s AND lower(email) = lower(%s) AND status = 'pending'",
                    (workspace_id, email),
                ).fetchone()
            )

    def list_pending_for_email(self, email: str) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM migration_workspace_invites "
                "WHERE lower(email) = lower(%s) AND status = 'pending' ORDER BY created_at",
                (email,),
            ).fetchall()
            return [_clean_row(r) or {} for r in rows]

    def update_invite(
        self,
        invite_id: str,
        fields: dict[str, Any],
        *,
        expect_status: str | None = None,
    ) -> dict[str, Any] | None:
        self.ensure_schema()
        values = {k: v for k, v in fields.items() if k in INVITE_FIELDS}
        if not values:
            return self.get_invite(invite_id)
        assignments = ", ".join(f"{key} = %s" for key in values)
        sql = f"UPDATE migration_workspace_invites SET {assignments} WHERE id = %s"
        params: list[Any] = [*values.values(), invite_id]
        if expect_status is not None:
            sql += " AND status = %s"
            params.append(expect_status)
        sql += " RETURNING *"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
            conn.commit()
            return _clean_row(row)

    # -- activity --------------------------------------------------------
    def add_activity(self, row: dict[str, Any]) -> None:
        self.ensure_schema()
        from psycopg.types.json import Jsonb

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO migration_workspace_activity
                  (id, workspace_id, actor_id, actor_name, action, summary, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    row["workspace_id"],
                    row.get("actor_id"),
                    row.get("actor_name"),
                    row["action"],
                    row["summary"],
                    Jsonb(row.get("metadata") or {}),
                ),
            )
            conn.commit()

    def list_activity(self, workspace_id: str, limit: int = 50) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM migration_workspace_activity WHERE workspace_id = %s "
                "ORDER BY created_at DESC LIMIT %s",
                (workspace_id, max(1, int(limit))),
            ).fetchall()
            return [_clean_row(r) or {} for r in rows]

    # -- profile / preferences -------------------------------------------
    def get_profile(self, user_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn:
            return _clean_row(
                conn.execute(
                    "SELECT * FROM migration_customer_profiles WHERE user_id = %s",
                    (user_id,),
                ).fetchone()
            )

    def get_profiles(self, user_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not user_ids:
            return {}
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM migration_customer_profiles WHERE user_id = ANY(%s)",
                (list(user_ids),),
            ).fetchall()
            return {str(r["user_id"]): _clean_row(r) or {} for r in rows}

    def upsert_profile(self, user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()
        values = {k: fields[k] for k in PROFILE_FIELDS if k in fields}
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO migration_customer_profiles (user_id) VALUES (%s) "
                "ON CONFLICT (user_id) DO NOTHING",
                (user_id,),
            )
            if values:
                assignments = ", ".join(f"{key} = %s" for key in values)
                conn.execute(
                    f"UPDATE migration_customer_profiles SET {assignments}, "
                    "updated_at = NOW() WHERE user_id = %s",
                    (*values.values(), user_id),
                )
            row = conn.execute(
                "SELECT * FROM migration_customer_profiles WHERE user_id = %s",
                (user_id,),
            ).fetchone()
            conn.commit()
            return _clean_row(row) or {}

    def get_preferences(self, user_id: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn:
            return _clean_row(
                conn.execute(
                    "SELECT * FROM migration_user_preferences WHERE user_id = %s",
                    (user_id,),
                ).fetchone()
            )

    def upsert_preferences(self, user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()
        from psycopg.types.json import Jsonb

        values = {k: fields[k] for k in PREFERENCE_FIELDS if k in fields}
        if "notification_preferences" in values:
            values["notification_preferences"] = Jsonb(values["notification_preferences"])
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO migration_user_preferences (user_id) VALUES (%s) "
                "ON CONFLICT (user_id) DO NOTHING",
                (user_id,),
            )
            if values:
                assignments = ", ".join(f"{key} = %s" for key in values)
                conn.execute(
                    f"UPDATE migration_user_preferences SET {assignments}, "
                    "updated_at = NOW() WHERE user_id = %s",
                    (*values.values(), user_id),
                )
            row = conn.execute(
                "SELECT * FROM migration_user_preferences WHERE user_id = %s",
                (user_id,),
            ).fetchone()
            conn.commit()
            return _clean_row(row) or {}


_STORE: Any | None = None


def get_team_store(path: Path | None = None) -> Any:
    """Postgres when configured; otherwise the explicit local/test file store."""
    global _STORE
    if path is not None:
        return FileTeamStore(path)
    db_url = migration_database_url()
    if db_url:
        if not isinstance(_STORE, PostgresTeamStore) or _STORE.database_url != db_url:
            _STORE = PostgresTeamStore(db_url)
        return _STORE
    if not allow_ephemeral_file_store():
        raise PersistenceNotConfiguredError(
            "Workspace database storage is not configured for this deployment. "
            "Temporary file storage is disabled on Railway unless "
            "CADIVOR_ALLOW_EPHEMERAL_FILE_STORE=1."
        )
    if not isinstance(_STORE, FileTeamStore):
        _STORE = FileTeamStore()
    return _STORE


def reset_team_store_for_tests(path: Path) -> FileTeamStore:
    global _STORE
    _STORE = FileTeamStore(path)
    _STORE.clear()
    return _STORE

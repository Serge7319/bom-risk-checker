"""Reconcile a missing migration-ledger marker on a *disposable* Postgres only.

When schema objects already exist (for example they were created by
``PostgresWorkspaceStore.ensure_schema`` or applied by hand) but the legacy
ledger row is missing, this helper inserts the ledger marker **without
re-running production SQL**. It never accepts or executes migration SQL; it
only reads catalog metadata and writes one ledger row.

The ledger follows the Supabase CLI layout
(``supabase_migrations.schema_migrations``: ``version``, ``statements``,
``name``). It refuses to touch anything that does not look like a local /
disposable database.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

DEFAULT_LEDGER_TABLE = "supabase_migrations.schema_migrations"

STATUS_RECORDED = "recorded"
STATUS_ALREADY_RECORDED = "already_recorded"
STATUS_OBJECTS_MISSING = "objects_missing"

_FORBIDDEN_HOST_MARKERS = ("railway", "rlwy", "supabase", "cadivor", "amazonaws", "neon.tech")
_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class NotDisposableDatabaseError(RuntimeError):
    """Raised when the ledger helper is pointed at a non-disposable database."""


def _scalar(row: Any) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()), None)
    return row[0]


def _quote_ledger(ledger_table: str) -> tuple[str, str, str]:
    parts = str(ledger_table or "").split(".")
    if len(parts) != 2 or not all(_IDENT_RE.match(part) for part in parts):
        raise ValueError(f"ledger_table must be schema.table, got {ledger_table!r}")
    schema, table = parts
    return schema, table, f'"{schema}"."{table}"'


def assert_disposable_connection(conn: Any) -> None:
    """Refuse non-local hosts and anything that looks like Railway/Supabase/customer DBs."""
    info = getattr(conn, "info", None)
    host = str(getattr(info, "host", "") or "").strip().casefold()
    dbname = str(getattr(info, "dbname", "") or "").strip().casefold()
    haystack = f"{host} {dbname}"
    if any(marker in haystack for marker in _FORBIDDEN_HOST_MARKERS):
        raise NotDisposableDatabaseError(
            "Refusing to reconcile a migration ledger on a non-disposable database."
        )
    # Unix-socket hosts start with "/" (local server); otherwise require loopback.
    if host not in _LOCAL_HOSTS and not host.startswith("/"):
        raise NotDisposableDatabaseError(
            f"Refusing to reconcile a migration ledger on remote host {host!r}."
        )


def ensure_ledger_table(conn: Any, ledger_table: str = DEFAULT_LEDGER_TABLE) -> None:
    """Create the ledger table when absent (disposable databases only)."""
    assert_disposable_connection(conn)
    schema, _table, quoted = _quote_ledger(ledger_table)
    conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {quoted} ("
        "version text PRIMARY KEY, statements text[], name text)"
    )


def _relation_exists(conn: Any, qualified: str) -> bool:
    return bool(_scalar(conn.execute("SELECT to_regclass(%s) IS NOT NULL", (qualified,)).fetchone()))


def _column_exists(conn: Any, schema: str, table: str, column: str) -> bool:
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s AND column_name = %s)",
        (schema, table, column),
    ).fetchone()
    return bool(_scalar(row))


def schema_objects_exist(
    conn: Any,
    *,
    required_tables: Iterable[str] = (),
    required_columns: Iterable[tuple[str, str]] = (),
    schema: str = "public",
) -> bool:
    """True only when every required table and ``(table, column)`` pair exists."""
    tables = list(required_tables)
    columns = list(required_columns)
    if not tables and not columns:
        # Never record a marker without evidence that the schema is present.
        return False
    for table in tables:
        if not _relation_exists(conn, f"{schema}.{table}"):
            return False
    for table, column in columns:
        if not _column_exists(conn, schema, table, column):
            return False
    return True


def ledger_has_version(
    conn: Any, version: str, ledger_table: str = DEFAULT_LEDGER_TABLE
) -> bool:
    _schema, _table, quoted = _quote_ledger(ledger_table)
    if not _relation_exists(conn, ledger_table):
        return False
    row = conn.execute(f"SELECT 1 FROM {quoted} WHERE version = %s", (version,)).fetchone()
    return row is not None


def reconcile_migration_marker(
    conn: Any,
    *,
    version: str,
    name: str,
    required_tables: Sequence[str] = (),
    required_columns: Sequence[tuple[str, str]] = (),
    ledger_table: str = DEFAULT_LEDGER_TABLE,
    schema: str = "public",
) -> str:
    """Insert the ledger marker when objects exist but the ledger row is missing.

    Returns ``recorded``, ``already_recorded``, or ``objects_missing``. The
    production migration SQL is never executed here; if the objects are not
    present the marker is NOT inserted so the real migration can still run.
    """
    assert_disposable_connection(conn)
    version = str(version or "").strip()
    if not version:
        raise ValueError("version is required")
    ensure_ledger_table(conn, ledger_table)
    if ledger_has_version(conn, version, ledger_table):
        return STATUS_ALREADY_RECORDED
    if not schema_objects_exist(
        conn,
        required_tables=required_tables,
        required_columns=required_columns,
        schema=schema,
    ):
        return STATUS_OBJECTS_MISSING
    _schema, _table, quoted = _quote_ledger(ledger_table)
    conn.execute(
        f"INSERT INTO {quoted} (version, name, statements) "
        "VALUES (%s, %s, ARRAY[]::text[]) ON CONFLICT (version) DO NOTHING",
        (version, str(name or version)),
    )
    return STATUS_RECORDED

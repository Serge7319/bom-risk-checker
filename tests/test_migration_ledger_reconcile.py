"""Migration-ledger reconcile helper: records a marker without re-running SQL."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.api.migration_ledger import (
    DEFAULT_LEDGER_TABLE,
    STATUS_ALREADY_RECORDED,
    STATUS_OBJECTS_MISSING,
    STATUS_RECORDED,
    NotDisposableDatabaseError,
    reconcile_migration_marker,
)


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConn:
    """Minimal psycopg-like connection that records every executed statement."""

    def __init__(self, *, host="localhost", dbname="postgres", tables=(), columns=()):
        self.info = SimpleNamespace(host=host, dbname=dbname)
        self.tables = {f"public.{name}" for name in tables}
        self.columns = set(columns)
        self.ledger_exists = False
        self.ledger: dict[str, str] = {}
        self.statements: list[str] = []

    def execute(self, sql, params=()):
        self.statements.append(" ".join(str(sql).split()))
        folded = self.statements[-1].upper()
        if folded.startswith("CREATE SCHEMA"):
            return _Cursor(None)
        if folded.startswith("CREATE TABLE IF NOT EXISTS"):
            self.ledger_exists = True
            return _Cursor(None)
        if folded.startswith("SELECT TO_REGCLASS"):
            qualified = params[0]
            if qualified == DEFAULT_LEDGER_TABLE:
                return _Cursor((self.ledger_exists,))
            return _Cursor((qualified in self.tables,))
        if "INFORMATION_SCHEMA.COLUMNS" in folded:
            _schema, table, column = params
            return _Cursor(((table, column) in self.columns,))
        if folded.startswith("SELECT 1 FROM"):
            return _Cursor((1,) if params[0] in self.ledger else None)
        if folded.startswith("INSERT INTO"):
            self.ledger.setdefault(params[0], params[1])
            return _Cursor(None)
        raise AssertionError(f"unexpected SQL: {sql}")


def _production_statements(conn: _FakeConn) -> list[str]:
    """Statements that would mutate non-ledger objects (must stay empty)."""
    return [
        stmt
        for stmt in conn.statements
        if stmt.upper().startswith(("CREATE", "ALTER", "DROP", "TRUNCATE", "INSERT", "UPDATE", "DELETE"))
        and "schema_migrations" not in stmt
        and not stmt.upper().startswith("CREATE SCHEMA")
    ]


def test_inserts_marker_when_objects_exist_without_running_production_sql():
    conn = _FakeConn(
        tables=("migration_decision_records",),
        columns={("migration_decision_records", "analysis_id")},
    )
    status = reconcile_migration_marker(
        conn,
        version="20261024",
        name="decision_records",
        required_tables=("migration_decision_records",),
        required_columns=(("migration_decision_records", "analysis_id"),),
    )
    assert status == STATUS_RECORDED
    assert conn.ledger == {"20261024": "decision_records"}
    assert _production_statements(conn) == []
    assert not any("migration_decision_records" in s and s.upper().startswith(("CREATE", "ALTER")) for s in conn.statements)


def test_reconcile_is_idempotent_and_never_duplicates():
    conn = _FakeConn(tables=("migration_decision_records",))
    kwargs = dict(
        version="20261024",
        name="decision_records",
        required_tables=("migration_decision_records",),
    )
    assert reconcile_migration_marker(conn, **kwargs) == STATUS_RECORDED
    assert reconcile_migration_marker(conn, **kwargs) == STATUS_ALREADY_RECORDED
    assert list(conn.ledger) == ["20261024"]


def test_missing_objects_do_not_get_a_marker_so_real_migration_can_run():
    conn = _FakeConn(tables=())
    status = reconcile_migration_marker(
        conn,
        version="20261024",
        name="decision_records",
        required_tables=("migration_decision_records",),
    )
    assert status == STATUS_OBJECTS_MISSING
    assert conn.ledger == {}


def test_missing_required_column_does_not_record():
    conn = _FakeConn(tables=("migration_decision_records",), columns=())
    status = reconcile_migration_marker(
        conn,
        version="20261024",
        name="decision_records",
        required_tables=("migration_decision_records",),
        required_columns=(("migration_decision_records", "analysis_id"),),
    )
    assert status == STATUS_OBJECTS_MISSING
    assert conn.ledger == {}


def test_no_object_evidence_never_records():
    conn = _FakeConn()
    assert (
        reconcile_migration_marker(conn, version="20261024", name="x") == STATUS_OBJECTS_MISSING
    )
    assert conn.ledger == {}


@pytest.mark.parametrize(
    "host",
    [
        "containers-us-west-1.railway.app",
        "db.abcd.supabase.co",
        "prod.cadivor.example",
        "10.0.0.5",
    ],
)
def test_refuses_non_disposable_hosts_before_any_write(host):
    conn = _FakeConn(host=host, tables=("migration_decision_records",))
    with pytest.raises(NotDisposableDatabaseError):
        reconcile_migration_marker(
            conn,
            version="20261024",
            name="decision_records",
            required_tables=("migration_decision_records",),
        )
    assert conn.statements == []

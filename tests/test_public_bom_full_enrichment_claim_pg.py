"""Real PostgreSQL concurrency tests for full-enrichment email quota / leases."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from uuid import uuid4

import pytest

EMBEDDED = pytest.importorskip("embedded_postgres")
psycopg = pytest.importorskip("psycopg")

ROOT = Path(__file__).resolve().parents[1]
# Worktree may omit the original create-table migration; try main repo next.
_BASE_CANDIDATES = [
    ROOT / "supabase/migrations/20261003_public_bom_stress_test.sql",
    ROOT.parents[2] / "supabase/migrations/20261003_public_bom_stress_test.sql",
]
BASE_SCHEMA = next((path for path in _BASE_CANDIDATES if path.exists()), None)
ABUSE_MIGRATION = (
    ROOT / "supabase/migrations/20261114_public_bom_abuse_protections.sql"
)

EMAIL = "quota@company.com"
IP_HASH = "a" * 64


@pytest.fixture(scope="module")
def disposable_pg(tmp_path_factory):
    root = tmp_path_factory.mktemp("public-bom-claim-pg")
    pgdata = root / "pgdata"
    pgdata.mkdir()
    server = EMBEDDED.get_server(pgdata, cleanup_mode="delete")
    uri = server.get_uri(database="postgres")
    assert "railway" not in uri.lower()
    assert "supabase" not in uri.lower()
    _bootstrap(uri)
    yield {"uri": uri, "server": server}
    try:
        server.__exit__(None, None, None)  # type: ignore[attr-defined]
    except Exception:
        pass


def _exec(uri: str, sql: str, params=None):
    with psycopg.connect(uri) as conn:
        # Do not pass an empty params tuple — migration SQL uses %rowtype etc.
        if params is None:
            conn.execute(sql)
        else:
            conn.execute(sql, params)
        conn.commit()


def _bootstrap(uri: str) -> None:
    _exec(
        uri,
        """
        do $$ begin
          create role anon nologin;
        exception when duplicate_object then null;
        end $$;
        do $$ begin
          create role authenticated nologin;
        exception when duplicate_object then null;
        end $$;
        do $$ begin
          create role service_role nologin;
        exception when duplicate_object then null;
        end $$;
        """,
    )
    # Prefer the checked-in create-table migration when available.
    if BASE_SCHEMA is not None:
        _exec(uri, BASE_SCHEMA.read_text())
    else:
        _exec(
            uri,
            """
            create extension if not exists pgcrypto;
            create table if not exists public.cadivor_public_bom_stress_tests (
                id uuid primary key default gen_random_uuid(),
                created_at timestamptz not null default now(),
                ip_hash text not null,
                filename text,
                row_count integer not null default 0,
                results jsonb not null default '[]'::jsonb,
                work_email text,
                status text not null default 'reserved'
                    check (status in ('reserved', 'ready', 'lead_captured'))
            );
            """,
        )
    _exec(uri, ABUSE_MIGRATION.read_text())


def _insert_report(uri: str, *, email: str = EMAIL, qa_mode: bool = False) -> str:
    report_id = str(uuid4())
    with psycopg.connect(uri) as conn:
        conn.execute(
            """
            insert into public.cadivor_public_bom_stress_tests(
                id, ip_hash, work_email, status, qa_mode, filename, row_count
            ) values (%s, %s, %s, 'lead_captured', %s, 'bom.csv', 8)
            """,
            (report_id, IP_HASH, email, qa_mode),
        )
        conn.commit()
    return report_id


def _claim(
    uri: str,
    email: str,
    report_id: str,
    *,
    lease_seconds: int = 900,
    bypass: bool = False,
) -> str:
    with psycopg.connect(uri) as conn:
        row = conn.execute(
            """
            select public.cadivor_claim_public_bom_full_enrichment(
                %s, %s::uuid, 30, %s, %s
            )
            """,
            (email, report_id, bypass, lease_seconds),
        ).fetchone()
        conn.commit()
        return str(row[0])


def test_concurrent_claims_two_reports_only_one_wins(disposable_pg):
    uri = disposable_pg["uri"]
    a = _insert_report(uri)
    b = _insert_report(uri)

    results: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(_claim, uri, EMAIL, a),
            pool.submit(_claim, uri, EMAIL, b),
            pool.submit(_claim, uri, EMAIL, a),
            pool.submit(_claim, uri, EMAIL, b),
        ]
        for fut in as_completed(futures):
            results.append(fut.result())

    claimed = [status for status in results if status == "claimed"]
    blocked = [
        status
        for status in results
        if status in {"quota_exceeded", "in_progress"}
    ]
    assert len(claimed) == 1, results
    assert len(blocked) == 3, results
    assert "quota_exceeded" in results


def test_same_report_retries_are_idempotent_in_progress(disposable_pg):
    uri = disposable_pg["uri"]
    report_id = _insert_report(uri, email="retry@company.com")

    results: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(_claim, uri, "retry@company.com", report_id)
            for _ in range(6)
        ]
        for fut in as_completed(futures):
            results.append(fut.result())

    assert results.count("claimed") == 1, results
    assert results.count("in_progress") == 5, results
    assert "quota_exceeded" not in results


def test_stale_lease_can_be_reclaimed_then_blocks_second_report(disposable_pg):
    uri = disposable_pg["uri"]
    email = "stale@company.com"
    first = _insert_report(uri, email=email)
    second = _insert_report(uri, email=email)

    # Take a short lease, then wait it out via backdating.
    assert _claim(uri, email, first, lease_seconds=60) == "claimed"
    with psycopg.connect(uri) as conn:
        conn.execute(
            """
            update public.cadivor_public_bom_stress_tests
            set full_enrichment_lease_expires_at = now() - interval '1 second'
            where id = %s::uuid
            """,
            (first,),
        )
        conn.commit()

    # Stale lease no longer blocks a different report.
    assert _claim(uri, email, second, lease_seconds=900) == "claimed"
    # Same-report retry while second holds the active lease → quota for first.
    assert _claim(uri, email, first, lease_seconds=900) == "quota_exceeded"


def test_already_complete_is_idempotent(disposable_pg):
    uri = disposable_pg["uri"]
    email = "done@company.com"
    report_id = _insert_report(uri, email=email)
    assert _claim(uri, email, report_id) == "claimed"
    with psycopg.connect(uri) as conn:
        conn.execute(
            """
            update public.cadivor_public_bom_stress_tests
            set full_enriched_at = now(),
                full_enrichment_lease_expires_at = null
            where id = %s::uuid
            """,
            (report_id,),
        )
        conn.commit()
    assert _claim(uri, email, report_id) == "already_complete"
    other = _insert_report(uri, email=email)
    assert _claim(uri, email, other) == "quota_exceeded"

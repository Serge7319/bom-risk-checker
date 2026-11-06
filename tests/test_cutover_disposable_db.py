"""Cutover readiness against a disposable embedded Postgres (never live DBs)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.fixtures.sandbox_auth_accounts import SANDBOX_SEED_USERS

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/synthetic_bom_25parts.csv"
EVIDENCE_DIR = Path(__file__).resolve().parents[1] / "apps" / ".evidence_cutover"
EMBEDDED = pytest.importorskip("embedded_postgres")


@pytest.fixture(scope="module")
def disposable_pg(tmp_path_factory):
    """Start an ephemeral Postgres that is destroyed after the module."""
    root = tmp_path_factory.mktemp("cutover-pg")
    pgdata = root / "pgdata"
    pgdata.mkdir()
    server = EMBEDDED.get_server(pgdata, cleanup_mode="delete")
    uri = server.get_uri(database="postgres")
    # Guardrails: refuse anything that looks like Railway/customer hosts.
    assert "railway" not in uri.lower()
    assert "supabase" not in uri.lower()
    assert "cadivor" not in uri.lower()
    yield {"server": server, "uri": uri, "pgdata": pgdata}
    # Drop handle so cleanup_mode=delete can stop/delete.
    try:
        server.__exit__(None, None, None)  # type: ignore[attr-defined]
    except Exception:
        pass


@pytest.fixture
def cutover_env(disposable_pg, tmp_path, monkeypatch):
    uri = disposable_pg["uri"]
    monkeypatch.setenv("CADIVOR_MIGRATION_DATABASE_URL", uri)
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "cutover-disposable-auth-secret")
    monkeypatch.delenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    monkeypatch.delenv("CADIVOR_USE_SUPABASE_AUTH", raising=False)
    monkeypatch.delenv("CADIVOR_MONITORING_EMAIL_ENABLED", raising=False)
    monkeypatch.delenv("CADIVOR_MIGRATION_SUPPLIER_LIVE", raising=False)

    from apps.api import sandbox_auth
    from apps.api import workspace_store
    from apps.api import monitoring_store
    from apps.api import synthetic_analyze as sa
    from apps.api.postgres_store import PostgresWorkspaceStore

    # Force fresh postgres-backed stores (do not call reset_auth_store_for_tests —
    # it pops CADIVOR_MIGRATION_DATABASE_URL).
    sandbox_auth._STORE = sandbox_auth._PostgresAuthStore(uri)
    sandbox_auth._STORE.clear()
    sandbox_auth._SEEDED = False
    sandbox_auth.seed_demo_users(SANDBOX_SEED_USERS, store=sandbox_auth._STORE)

    workspace_store._STORE = PostgresWorkspaceStore(uri)
    workspace_store._STORE.clear()
    monitoring_store.reset_monitoring_store_for_tests()
    sa._REPORTS.clear()

    yield {
        "uri": uri,
        "pgdata": disposable_pg["pgdata"],
        "accounts": SANDBOX_SEED_USERS,
    }


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _analyze(client: TestClient, headers: dict[str, str]) -> dict:
    with FIXTURE.open("rb") as handle:
        res = client.post(
            "/boms/analyze",
            headers=headers,
            files={"file": ("synthetic_bom_25parts.csv", handle, "text/csv")},
            data={"project_name": "Cutover Drill", "bom_name": "Synthetic"},
        )
    assert res.status_code == 200, res.text
    return res.json()


def test_tenant_isolation_reads_and_mutations(cutover_env):
    from apps.api.main import app

    client = TestClient(app)
    a = SANDBOX_SEED_USERS[0]
    b = SANDBOX_SEED_USERS[1]
    headers_a = _login(client, a["email"], a["password"])
    headers_b = _login(client, b["email"], b["password"])

    report_a = _analyze(client, headers_a)
    analysis_a = report_a["analysis_id"]
    assert report_a["workspace_id"] == a["workspace_id"]

    # B cannot read A's report
    denied = client.get(f"/reports/{analysis_a}", headers=headers_b)
    assert denied.status_code == 404

    # B cannot delete A's report
    del_denied = client.delete(f"/reports/{analysis_a}", headers=headers_b)
    assert del_denied.status_code == 404

    # A can read own report
    ok = client.get(f"/reports/{analysis_a}", headers=headers_a)
    assert ok.status_code == 200
    assert ok.json()["workspace_id"] == a["workspace_id"]

    # Monitoring prefs/alerts are tenant-scoped
    client.put(
        "/tools/monitoring/preferences",
        headers=headers_a,
        json={"email_alerts": True, "lifecycle": True},
    )
    client.get("/tools/monitoring", headers=headers_a, params={"analysis_id": analysis_a})
    alerts_a = client.get("/tools/monitoring/alerts", headers=headers_a).json()["alerts"]
    prefs_b = client.get("/tools/monitoring/preferences", headers=headers_b).json()["preferences"]
    alerts_b = client.get("/tools/monitoring/alerts", headers=headers_b).json()["alerts"]
    assert prefs_b.get("email_alerts") is False
    assert alerts_b == []
    if alerts_a:
        # B cannot acknowledge A's alert id
        ack = client.post(
            "/tools/monitoring/acknowledge",
            headers=headers_b,
            json={"alert_id": alerts_a[0]["id"]},
        )
        assert ack.status_code == 404


def test_backup_restore_and_recovery(cutover_env, tmp_path):
    from apps.api.main import app
    from apps.api import workspace_store
    from apps.api.postgres_store import PostgresWorkspaceStore
    import psycopg

    client = TestClient(app)
    a = SANDBOX_SEED_USERS[0]
    headers_a = _login(client, a["email"], a["password"])
    report_a = _analyze(client, headers_a)
    analysis_a = report_a["analysis_id"]
    before = client.get(f"/reports/{analysis_a}", headers=headers_a)
    assert before.status_code == 200
    parts_before = before.json().get("total_parts") or len(before.json().get("parts") or [])

    dump_path = tmp_path / "cutover_disposable.dump"
    # Call embedded binaries directly — the helper wraps pg_dump with invalid -D.
    import subprocess
    from embedded_postgres._commands import POSTGRES_BIN_PATH

    dump_bin = POSTGRES_BIN_PATH / "pg_dump"
    restore_bin = POSTGRES_BIN_PATH / "pg_restore"
    subprocess.run(
        [str(dump_bin), f"--dbname={cutover_env['uri']}", "-Fc", f"--file={dump_path}"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert dump_path.exists() and dump_path.stat().st_size > 0

    # Wipe application tables (simulate loss)
    store = workspace_store.get_store()
    store.clear()
    missing = client.get(f"/reports/{analysis_a}", headers=headers_a)
    assert missing.status_code == 404

    # Restore
    subprocess.run(
        [
            str(restore_bin),
            f"--dbname={cutover_env['uri']}",
            "--clean",
            "--if-exists",
            str(dump_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    # Rebind store after restore
    workspace_store._STORE = PostgresWorkspaceStore(cutover_env["uri"])
    recovered = client.get(f"/reports/{analysis_a}", headers=headers_a)
    assert recovered.status_code == 200, recovered.text
    parts_after = recovered.json().get("total_parts") or len(recovered.json().get("parts") or [])
    assert parts_after == parts_before

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "backup_restore.json").write_text(
        json.dumps(
            {
                "pass": True,
                "dump_bytes": dump_path.stat().st_size,
                "analysis_id": analysis_a,
                "parts_before": parts_before,
                "parts_after": parts_after,
                "database": "disposable-embedded-postgres",
                "not_customer_db": True,
                "not_live_migration_db": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_performance_synthetic_analyze_and_report(cutover_env):
    from apps.api.main import app

    client = TestClient(app)
    a = SANDBOX_SEED_USERS[0]
    headers_a = _login(client, a["email"], a["password"])

    t0 = time.perf_counter()
    report = _analyze(client, headers_a)
    analyze_ms = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    loaded = client.get(f"/reports/{report['analysis_id']}", headers=headers_a)
    report_ms = (time.perf_counter() - t1) * 1000
    assert loaded.status_code == 200

    # Soft budget for local disposable DB (not a production SLA claim).
    assert analyze_ms < 15000, analyze_ms
    assert report_ms < 2000, report_ms

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "performance.json").write_text(
        json.dumps(
            {
                "pass": True,
                "analyze_ms": round(analyze_ms, 2),
                "report_get_ms": round(report_ms, 2),
                "fixture": str(FIXTURE.name),
                "database": "disposable-embedded-postgres",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_supplier_monitoring_billing_connectors_compliance_on_disposable_db(cutover_env):
    from apps.api.main import app

    client = TestClient(app)
    a = SANDBOX_SEED_USERS[0]
    headers = _login(client, a["email"], a["password"])
    analysis_id = _analyze(client, headers)["analysis_id"]

    lookup = client.post("/tools/supplier-lookup", headers=headers, json={"mpn": "RES10K"})
    assert lookup.status_code == 200
    assert lookup.json()["synthetic"] is True
    assert lookup.json()["match"]["source_url"]

    compare = client.post(
        "/tools/compare-parts",
        headers=headers,
        json={"part_a": "RES10K", "part_b": "CAP100U", "analysis_id": analysis_id},
    )
    assert compare.status_code in (200, 400)

    decision = client.post(
        "/decision-records",
        headers=headers,
        json={
            "analysis_id": analysis_id,
            "part_a": "RES10K",
            "part_b": "CAP100U",
            "decision": "hold_for_review",
            "reviewer": "Disposable DB reviewer",
            "rationale": "Verify the exact part specifications before release.",
        },
    )
    assert decision.status_code == 201, decision.text
    decision_id = decision.json()["record"]["id"]
    assert decision.json()["record"]["qualification_status"] == "not-qualified-by-cadivor"
    persisted_decisions = client.get(
        f"/decision-records?analysis_id={analysis_id}", headers=headers
    )
    assert persisted_decisions.status_code == 200
    assert persisted_decisions.json()["records"][0]["id"] == decision_id

    procurement = client.get(
        "/tools/procurement", headers=headers, params={"analysis_id": analysis_id}
    )
    assert procurement.status_code == 200

    billing = client.get("/billing/status", headers=headers)
    assert billing.status_code == 200
    assert billing.json()["checkout_enabled"] is False

    usage = client.get("/plan/usage", headers=headers)
    assert usage.status_code == 200
    assert usage.json()["enforced"] is True

    connectors = client.get("/integrations/connectors", headers=headers)
    assert connectors.status_code == 200
    assert connectors.json()["ready_count"] >= 1

    for pack in ("rohs", "reach", "conflict_minerals", "audit"):
        res = client.get(f"/compliance/{pack}", headers=headers, params={"analysis_id": analysis_id})
        assert res.status_code == 200
        body = res.json()
        if pack == "audit":
            assert body["compliance_claimed"] is False
        else:
            assert body["summary"]["compliance_claimed"] is False

def test_concurrent_analysis_writes_are_persisted(cutover_env, monkeypatch):
    """Parallel synthetic uploads must commit distinct workspace reports."""
    from concurrent.futures import ThreadPoolExecutor

    from apps.api import plan_limits
    from apps.api.main import app

    # Isolate storage concurrency from the independent monthly quota gate.
    monkeypatch.setattr(plan_limits, "assert_analysis_allowed", lambda **_: {})

    account = SANDBOX_SEED_USERS[0]
    headers = _login(TestClient(app), account["email"], account["password"])
    payload = FIXTURE.read_bytes()
    total = 8

    def upload(index: int) -> tuple[int, dict]:
        with TestClient(app) as client:
            response = client.post(
                "/boms/analyze",
                headers=headers,
                data={
                    "project_name": "Concurrent Write Test",
                    "bom_name": f"Concurrent BOM {index}",
                    "revision": "A",
                },
                files={
                    "file": (
                        f"concurrent_bom_{index}.csv",
                        payload,
                        "text/csv",
                    )
                },
            )
        try:
            body = response.json()
        except ValueError:
            body = {"detail": response.text}
        return response.status_code, body

    with ThreadPoolExecutor(max_workers=total) as pool:
        results = list(pool.map(upload, range(total)))

    failures = [
        f"upload {index}: HTTP {status} {body}"
        for index, (status, body) in enumerate(results)
        if status != 200
    ]
    assert not failures, "\\n".join(failures)

    analysis_ids = [body["analysis_id"] for _, body in results]
    assert len(set(analysis_ids)) == total

    # Confirm every distinct concurrent write can be read from Postgres.
    client = TestClient(app)
    for analysis_id in analysis_ids:
        saved = client.get(f"/reports/{analysis_id}", headers=headers)
        assert saved.status_code == 200, saved.text
        assert saved.json()["workspace_id"] == account["workspace_id"]


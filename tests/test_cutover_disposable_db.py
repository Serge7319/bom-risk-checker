"""Cutover readiness against a disposable embedded Postgres (never live DBs)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.fixtures.sandbox_auth_accounts import SANDBOX_SEED_USERS
from tests.two_user_isolation_suite import (
    PREFERENCES_A,
    PREFERENCES_B,
    assert_denied_for_other_user,
    assert_other_user_only_sees_own,
    assert_owner_still_has_everything,
    assert_unauthenticated_denied,
    seed_workspace,
)

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
    client.post("/tools/monitoring/refresh", headers=headers_a, params={"analysis_id": analysis_a})
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


def test_two_user_postgres_matrix_workspaces_boms_reports_decisions_monitoring(cutover_env):
    """Acceptance D3 on disposable Postgres: User B denied everything of A; B sees own only.

    Monitoring GET is read-only; alerts are persisted via
    ``POST /tools/monitoring/refresh`` inside ``seed_workspace``. No production
    account is created and no email transport is configured.
    """
    from apps.api.main import app

    client = TestClient(app)
    a, b = SANDBOX_SEED_USERS[0], SANDBOX_SEED_USERS[1]
    headers_a = _login(client, a["email"], a["password"])
    headers_b = _login(client, b["email"], b["password"])

    seeded_a = seed_workspace(client, headers_a, owner="A", preferences=PREFERENCES_A)
    seeded_b = seed_workspace(client, headers_b, owner="B", preferences=PREFERENCES_B)
    assert seeded_a["workspace_id"] == a["workspace_id"]
    assert seeded_b["workspace_id"] == b["workspace_id"]

    denied_b = assert_denied_for_other_user(client, headers_b, seeded_a)
    denied_a = assert_denied_for_other_user(client, headers_a, seeded_b)
    assert len(denied_b) == len(denied_a) >= 30
    assert_unauthenticated_denied(client, seeded_a)

    assert_owner_still_has_everything(client, headers_a, seeded_a)
    allowed_b = assert_other_user_only_sees_own(client, headers_b, seeded_b)
    assert len(allowed_b) >= 12
    # B deleting their own project/report never touched A (verified in Postgres).
    assert_owner_still_has_everything(client, headers_a, seeded_a)


def test_saved_bom_management_moves_preserves_and_deletes_scoped_history(cutover_env):
    from apps.api.main import app
    from apps.api import monitoring_store, workspace_store
    import psycopg

    client = TestClient(app)
    a, b = SANDBOX_SEED_USERS[0], SANDBOX_SEED_USERS[1]
    headers_a = _login(client, a["email"], a["password"])
    headers_b = _login(client, b["email"], b["password"])

    def analyze(project_name: str, bom_name: str, revision: str, mpn: str) -> dict:
        payload = f"MPN,Quantity\n{mpn},1\n".encode()
        response = client.post(
            "/boms/analyze",
            headers=headers_a,
            files={"file": (f"{bom_name}-{revision}.csv", payload, "text/csv")},
            data={"project_name": project_name, "bom_name": bom_name, "revision": revision},
        )
        assert response.status_code == 200, response.text
        return response.json()

    source_a = analyze("Drone", "Controller", "A", "MPU-6050")
    source_b = analyze("Drone", "Controller", "B", "MPU-6050")
    destination = analyze("Power Supply", "Power BOM", "A", "TPS5430")
    source_id = source_a["analysis_id"]
    bom_id = source_a["bom_id"]
    workspace_id = a["workspace_id"]
    store = workspace_store.get_store()
    decision = store.create_decision_record(
        {
            "analysis_id": source_id,
            "part_a": "MPU-6050",
            "part_b": "SEN0142",
            "decision": "approve_alternate",
        },
        workspace_id=workspace_id,
    )
    store.create_procurement_quote(
        {
            "analysis_id": source_id,
            "requested_mpn": "MPU-6050",
            "requested_manufacturer": "",
            "supplier": "Test Distributor",
        },
        workspace_id=workspace_id,
    )
    alert_rows = monitoring_store.persist_alerts(
        workspace_id,
        [{
            "analysis_id": source_id,
            "part_number": "MPU-6050",
            "alert_type": "lifecycle-change",
            "severity": "high",
            "message": "Lifecycle changed",
        }],
    )
    assert alert_rows
    alert = alert_rows[0]
    user_id = client.get("/auth/me", headers=headers_a).json()["user_id"]
    assert monitoring_store.claim_scheduled_alert_email(workspace_id, user_id, alert)
    monitoring_store.save_live_snapshot({
        "workspace_id": workspace_id,
        "analysis_id": source_id,
        "part_number": "MPU-6050",
        "stock": 0,
    })
    monitoring_store.record_refresh(
        workspace_id,
        analysis_id=source_id,
        alert_count=1,
        mode="test",
    )

    cross_workspace = client.patch(
        f"/boms/{bom_id}", headers=headers_b, json={"project_id": destination["project_id"]}
    )
    assert cross_workspace.status_code == 404
    moved = client.patch(
        f"/boms/{bom_id}", headers=headers_a, json={"project_id": destination["project_id"]}
    )
    assert moved.status_code == 200, moved.text
    renamed = client.patch(
        f"/boms/{bom_id}", headers=headers_a, json={"name": "Flight Controller"}
    )
    assert renamed.status_code == 200, renamed.text

    for analysis_id in (source_id, source_b["analysis_id"]):
        current = client.get(f"/reports/{analysis_id}", headers=headers_a)
        assert current.status_code == 200, current.text
        assert current.json()["project_id"] == destination["project_id"]
        assert current.json()["project_name"] == "Power Supply — Flight Controller"
        assert current.json()["bom_name"] == "Flight Controller"
    assert decision["id"] in {
        item["id"]
        for item in store.list_decision_records(
            workspace_id=workspace_id, analysis_id=source_id
        )
    }
    assert store.list_procurement_quotes(workspace_id=workspace_id, analysis_id=source_id)

    deleted = client.delete(f"/boms/{bom_id}", headers=headers_a)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_analysis_count"] == 2
    for analysis_id in (source_id, source_b["analysis_id"]):
        assert client.get(f"/reports/{analysis_id}", headers=headers_a).status_code == 404
    assert store.list_decision_records(workspace_id=workspace_id, analysis_id=source_id) == []
    assert store.list_procurement_quotes(workspace_id=workspace_id, analysis_id=source_id) == []
    assert monitoring_store.list_alerts(workspace_id, analysis_id=source_id) == []
    assert monitoring_store.get_live_snapshot(workspace_id, source_id, "MPU-6050") is None
    assert all(row.get("analysis_id") != source_id for row in monitoring_store.list_refresh_history(workspace_id))
    with psycopg.connect(cutover_env["uri"]) as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM migration_monitoring_email_deliveries WHERE workspace_id = %s AND alert_id = %s",
            (workspace_id, alert["id"]),
        ).fetchone()[0] == 0
    assert client.get(f"/reports/{destination['analysis_id']}", headers=headers_a).status_code == 200



def test_single_saved_report_delete_preserves_sibling_and_cleans_history(cutover_env):
    from apps.api.main import app
    from apps.api import monitoring_store, workspace_store
    import psycopg

    client = TestClient(app)
    account = SANDBOX_SEED_USERS[0]
    headers = _login(client, account["email"], account["password"])
    workspace_id = account["workspace_id"]

    def analyze(revision: str) -> dict:
        payload = b"MPN,Quantity\nTPS5430,1\n"
        response = client.post(
            "/boms/analyze",
            headers=headers,
            files={"file": (f"Controller-{revision}.csv", payload, "text/csv")},
            data={"project_name": "Drone", "bom_name": "Controller", "revision": revision},
        )
        assert response.status_code == 200, response.text
        return response.json()

    saved_a = analyze("A")
    saved_b = analyze("B")
    assert saved_a["bom_id"] == saved_b["bom_id"]
    deleted_id = saved_b["analysis_id"]
    bom_id = saved_a["bom_id"]
    store = workspace_store.get_store()
    store.create_decision_record(
        {
            "analysis_id": deleted_id,
            "part_a": "TPS5430",
            "part_b": "TPS5431",
            "decision": "approve_alternate",
        },
        workspace_id=workspace_id,
    )
    store.create_procurement_quote(
        {
            "analysis_id": deleted_id,
            "requested_mpn": "TPS5430",
            "requested_manufacturer": "Texas Instruments",
            "supplier": "Test Distributor",
        },
        workspace_id=workspace_id,
    )
    alert_rows = monitoring_store.persist_alerts(
        workspace_id,
        [{
            "analysis_id": deleted_id,
            "part_number": "TPS5430",
            "alert_type": "lifecycle-change",
            "severity": "high",
            "message": "Lifecycle changed",
        }],
    )
    assert alert_rows
    alert = alert_rows[0]
    user_id = client.get("/auth/me", headers=headers).json()["user_id"]
    assert monitoring_store.claim_scheduled_alert_email(workspace_id, user_id, alert)
    monitoring_store.save_live_snapshot({
        "workspace_id": workspace_id,
        "analysis_id": deleted_id,
        "part_number": "TPS5430",
        "stock": 0,
    })
    monitoring_store.record_refresh(
        workspace_id, analysis_id=deleted_id, alert_count=1, mode="test"
    )
    with psycopg.connect(cutover_env["uri"]) as conn:
        conn.execute(
            """
            INSERT INTO migration_monitoring_slack_deliveries
                (workspace_id, alert_id, status) VALUES (%s, %s, 'sent')
            """,
            (workspace_id, alert["id"]),
        )

    response = client.delete(f"/reports/{deleted_id}", headers=headers)
    assert response.status_code == 200, response.text
    assert client.get(f"/reports/{deleted_id}", headers=headers).status_code == 404
    assert client.get(f"/reports/{saved_a['analysis_id']}", headers=headers).status_code == 200
    assert store.list_decision_records(workspace_id=workspace_id, analysis_id=deleted_id) == []
    assert store.list_procurement_quotes(workspace_id=workspace_id, analysis_id=deleted_id) == []
    assert monitoring_store.list_alerts(workspace_id, analysis_id=deleted_id) == []
    assert monitoring_store.get_live_snapshot(workspace_id, deleted_id, "TPS5430") is None
    assert all(
        row.get("analysis_id") != deleted_id
        for row in monitoring_store.list_refresh_history(workspace_id)
    )
    with psycopg.connect(cutover_env["uri"]) as conn:
        assert conn.execute(
            "SELECT latest_analysis_id FROM migration_boms WHERE id = %s", (bom_id,)
        ).fetchone()[0] == saved_a["analysis_id"]
        assert conn.execute(
            """
            SELECT latest_analysis_id FROM migration_revisions
            WHERE bom_id = %s AND revision = 'A'
            """,
            (bom_id,),
        ).fetchone()[0] == saved_a["analysis_id"]
        assert conn.execute(
            "SELECT COUNT(*) FROM migration_revisions WHERE bom_id = %s AND revision = 'B'",
            (bom_id,),
        ).fetchone()[0] == 0
        for table in (
            "migration_monitoring_email_deliveries",
            "migration_monitoring_slack_deliveries",
        ):
            assert conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE workspace_id = %s AND alert_id = %s",
                (workspace_id, alert["id"]),
            ).fetchone()[0] == 0

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
    connectors_body = connectors.json()
    assert connectors_body.get("file_workflow_count", 0) >= 1
    assert connectors_body.get("live_ready_count", connectors_body["ready_count"]) == 0
    assert connectors_body["ready_count"] == 0

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



def test_hold_for_review_single_record_under_correct_bom_on_workspace_store(cutover_env):
    """Railway-style Postgres workspace store: one hold record, correct BOM, no approval."""
    from apps.api.main import app
    from tests.test_hold_for_review_single_record import (
        assert_single_hold_for_review_under_bom,
    )

    client = TestClient(app)
    account = SANDBOX_SEED_USERS[0]
    headers = _login(client, account["email"], account["password"])
    record = assert_single_hold_for_review_under_bom(client, headers)
    assert record["workspace_id"] == account["workspace_id"]


def test_ledger_reconcile_inserts_marker_without_rerunning_production_sql(
    cutover_env, monkeypatch
):
    """Schema exists but the legacy ledger row is missing: insert marker only."""
    import psycopg

    from apps.api import migration_ledger as ledger
    from apps.api.postgres_store import PostgresWorkspaceStore

    # Production SQL (ensure_schema) must not be re-run by the reconcile helper.
    def _boom(self):  # noqa: ANN001
        raise AssertionError("reconcile must not re-run production schema SQL")

    monkeypatch.setattr(PostgresWorkspaceStore, "ensure_schema", _boom)

    class _RecordingConn:
        def __init__(self, inner):
            self._inner = inner
            self.statements: list[str] = []

        @property
        def info(self):
            return self._inner.info

        def execute(self, sql, params=None):
            self.statements.append(" ".join(str(sql).split()))
            return self._inner.execute(sql, params)

    version = "20990101000000"
    kwargs = dict(
        version=version,
        name="legacy_sandbox_workspace",
        required_tables=("migration_decision_records", "migration_projects"),
        required_columns=(("migration_decision_records", "analysis_id"),),
    )
    with psycopg.connect(cutover_env["uri"], autocommit=True) as raw:
        ledger.ensure_ledger_table(raw)
        raw.execute(
            f"DELETE FROM {ledger.DEFAULT_LEDGER_TABLE} WHERE version = %s", (version,)
        )
        assert not ledger.ledger_has_version(raw, version)

        conn = _RecordingConn(raw)
        assert ledger.reconcile_migration_marker(conn, **kwargs) == ledger.STATUS_RECORDED
        assert ledger.ledger_has_version(raw, version)
        # Only ledger writes + catalog reads: no production DDL / DML.
        writes = [
            stmt
            for stmt in conn.statements
            if stmt.upper().startswith(("CREATE", "ALTER", "DROP", "TRUNCATE", "INSERT", "UPDATE", "DELETE"))
            and "schema_migrations" not in stmt
            and not stmt.upper().startswith("CREATE SCHEMA")
        ]
        assert writes == []

        # Idempotent: second call never duplicates the marker.
        assert (
            ledger.reconcile_migration_marker(conn, **kwargs) == ledger.STATUS_ALREADY_RECORDED
        )
        count = raw.execute(
            f"SELECT count(*) FROM {ledger.DEFAULT_LEDGER_TABLE} WHERE version = %s",
            (version,),
        ).fetchone()[0]
        assert count == 1

        # Missing objects are never marked as applied.
        missing_version = "20990101000001"
        assert (
            ledger.reconcile_migration_marker(
                conn,
                version=missing_version,
                name="not_applied",
                required_tables=("migration_table_that_does_not_exist",),
            )
            == ledger.STATUS_OBJECTS_MISSING
        )
        assert not ledger.ledger_has_version(raw, missing_version)

        raw.execute(
            f"DELETE FROM {ledger.DEFAULT_LEDGER_TABLE} WHERE version = %s", (version,)
        )


def test_workspace_audit_helper_skips_workspace_less_rows(disposable_pg):
    """Workspace-less account cleanup must not violate the audit table contract."""
    import psycopg

    root = Path(__file__).resolve().parents[1]
    migration_sql = (
        root / "supabase" / "migrations"
        / "20261127140000_workspace_audit_null_context.sql"
    ).read_text(encoding="utf-8")
    conn = psycopg.connect(disposable_pg["uri"])
    try:
        conn.execute(
            "CREATE TABLE public.workspaces (id uuid PRIMARY KEY)"
        )
        conn.execute(
            "CREATE TABLE public.workspace_members ("
            "workspace_id uuid NOT NULL, user_id uuid NOT NULL, "
            "display_name text, email text, joined_at timestamptz)"
        )
        conn.execute(
            "CREATE TABLE public.workspace_audit_log ("
            "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
            "workspace_id uuid NOT NULL REFERENCES public.workspaces(id), "
            "actor_user_id uuid, actor_name text NOT NULL, actor_email text NOT NULL, "
            "action_type text NOT NULL, object_type text NOT NULL, "
            "object_id text NOT NULL, object_label text NOT NULL, "
            "summary text NOT NULL, metadata jsonb NOT NULL DEFAULT '{}'::jsonb, "
            "search_text text NOT NULL, created_at timestamptz NOT NULL DEFAULT now())"
        )
        conn.execute(migration_sql, prepare=False)

        actor_id = "00000000-0000-0000-0000-000000000001"
        conn.execute(
            "SELECT public.cadivor_write_audit_event("
            "NULL, %s::uuid, 'analysis.update', 'analyses', 'private-1', "
            "'Private analysis', 'Private analysis updated', '{}'::jsonb)",
            (actor_id,),
        )
        assert conn.execute(
            "SELECT count(*) FROM public.workspace_audit_log"
        ).fetchone()[0] == 0

        workspace_id = "00000000-0000-0000-0000-000000000002"
        conn.execute(
            "INSERT INTO public.workspaces (id) VALUES (%s::uuid)", (workspace_id,)
        )
        # A missing membership row must still produce non-NULL audit fields.
        conn.execute(
            "SELECT public.cadivor_write_audit_event("
            "%s::uuid, %s::uuid, 'analysis.update', 'analyses', 'shared-1', "
            "'Shared analysis', 'Shared analysis updated', '{}'::jsonb)",
            (workspace_id, actor_id),
        )
        audit = conn.execute(
            "SELECT workspace_id, actor_name, actor_email "
            "FROM public.workspace_audit_log"
        ).fetchone()
        assert str(audit[0]) == workspace_id
        assert audit[1:] == ("", "")
    finally:
        # The disposable DB is shared by this module's fixtures; leave no test schema behind.
        conn.rollback()
        conn.close()

"""API coverage for Next.js migration tool routes (sandbox / synthetic)."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/synthetic_bom_25parts.csv"


@pytest.fixture(autouse=True)
def _sandbox_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    from apps.api import synthetic_analyze as sa

    sa._REPORTS.clear()


def _auth_headers(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    assert res.status_code == 200
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _account_headers(client: TestClient, account: dict[str, str]) -> dict[str, str]:
    res = client.post(
        "/auth/login",
        json={"email": account["email"], "password": account["password"]},
    )
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_migration_tools_vertical_slice():
    client = TestClient(app)
    headers = _auth_headers(client)

    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("synthetic_bom_25parts.csv", FIXTURE.read_bytes(), "text/csv")},
    )
    assert analyze.status_code == 200
    analysis_id = analyze.json()["analysis_id"]

    reports = client.get("/reports", headers=headers)
    assert reports.status_code == 200
    assert any(r["id"] == analysis_id for r in reports.json()["reports"])

    monitoring = client.get(
        f"/tools/monitoring?analysis_id={analysis_id}", headers=headers
    )
    assert monitoring.status_code == 200
    body = monitoring.json()
    assert body["ok"] is True
    assert body["metrics"]["monitored_parts"] == 25
    assert "Supabase" in body["gap"] or "monitor" in body["gap"].lower()

    report = client.get(f"/reports/{analysis_id}", headers=headers).json()
    part_a = report["parts"][0]["MPN"]
    part_b = report["parts"][1]["MPN"]
    compare = client.post(
        "/tools/compare-parts",
        headers=headers,
        json={"part_a": part_a, "part_b": part_b, "analysis_id": analysis_id},
    )
    assert compare.status_code == 200
    cmp_body = compare.json()
    assert cmp_body["ok"] is True
    assert len(cmp_body["rows"]) >= 1
    assert "supplier" in cmp_body["gap"].lower() or "synthetic" in cmp_body["gap"].lower()

    for path in (
        f"/tools/procurement?analysis_id={analysis_id}",
        f"/tools/design-impact?analysis_id={analysis_id}",
        f"/tools/cost-optimization?analysis_id={analysis_id}&build_quantity=100",
        f"/tools/detailed-risk?analysis_id={analysis_id}",
        "/tools/portfolio",
    ):
        res = client.get(path, headers=headers)
        assert res.status_code == 200, path
        assert res.json().get("ok") is True

    supply = client.post(
        "/tools/supply-risk",
        headers=headers,
        json={
            "analysis_id": analysis_id,
            "build_quantity": 100,
            "stock_reduction_percent": 25,
        },
    )
    assert supply.status_code == 200
    assert supply.json()["ok"] is True

    health = client.get("/health")
    assert health.status_code == 200
    assert "monitoring" in health.json()["tools"]


def test_production_compare_reuses_the_legacy_supplier_and_datasheet_engine(monkeypatch):
    from apps.api import legacy_supplier_workflow, migration_tools

    calls = {}

    def capture(**kwargs):
        calls.update(kwargs)
        return {"ok": True, "mode": "legacy-supplier-engine"}

    monkeypatch.setattr(legacy_supplier_workflow, "production_analysis_enabled", lambda: True)
    monkeypatch.setattr(migration_tools, "_legacy_compare_parts_payload", capture)
    result = migration_tools.compare_parts_payload(
        workspace_id="workspace-synthetic",
        part_a="AM29F010B70EC",
        part_b="AM29F010B70EI",
        analysis_id="analysis-synthetic",
        use_latest_if_missing=False,
    )

    assert result["mode"] == "legacy-supplier-engine"
    assert calls["part_a"] == "AM29F010B70EC"
    assert calls["part_b"] == "AM29F010B70EI"
    assert calls["analysis_id"] == "analysis-synthetic"
    assert calls["extract_linked_datasheets"] is True


def test_compare_endpoint_accepts_optional_pdf_datasheets():
    from io import BytesIO
    from pypdf import PdfWriter

    client = TestClient(app)
    headers = _auth_headers(client)
    pdf = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)

    response = client.post(
        "/tools/compare-parts",
        headers=headers,
        data={"part_a": "AM29F010B70EC", "part_b": "AM29F010B70EI"},
        files={"datasheet_a": ("flash-memory.pdf", pdf.getvalue(), "application/pdf")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "uploaded-datasheet-review"
    assert body["rows"]
    assert body["family"] == "Flash memory"


def test_decision_records_round_trip_and_are_workspace_scoped():
    client = TestClient(app)
    headers_a = _account_headers(client, SANDBOX_SEED_USERS[0])
    headers_b = _account_headers(client, SANDBOX_SEED_USERS[1])
    analyze = client.post(
        "/boms/analyze",
        headers=headers_a,
        data={"project_name": "Decision test", "bom_name": "Synthetic controller", "revision": "B"},
        files={"file": ("synthetic_bom_25parts.csv", FIXTURE.read_bytes(), "text/csv")},
    )
    assert analyze.status_code == 200, analyze.text
    analysis_id = analyze.json()["analysis_id"]
    report = client.get(f"/reports/{analysis_id}", headers=headers_a).json()
    part_a, part_b = report["parts"][0]["MPN"], report["parts"][1]["MPN"]

    payload = {
        "analysis_id": analysis_id,
        "part_a": part_a,
        "part_b": part_b,
        "decision": "hold_for_review",
        "reviewer": "Engineering reviewer",
        "rationale": "Confirm package and lifecycle from manufacturer datasheets.",
        "validation_checks": ["manufacturer_datasheet_reviewed", "electrical_limits_verified"],
        "follow_up_action": "Confirm the exact package suffix before release.",
        "follow_up_owner": "Design Engineering",
        "follow_up_due_date": "2026-11-14",
        "residual_risk": "medium",
    }
    saved = client.post("/decision-records", headers=headers_a, json=payload)
    assert saved.status_code == 201, saved.text
    record = saved.json()["record"]
    assert record["analysis_id"] == analysis_id
    assert record["project_name"] == "Decision test"
    assert record["bom_name"] == "Synthetic controller"
    assert record["qualification_status"] == "not-qualified-by-cadivor"
    assert record["comparison_snapshot"]["rows"]
    assert record["validation_checks"] == payload["validation_checks"]
    assert record["follow_up_action"] == payload["follow_up_action"]
    assert record["follow_up_owner"] == payload["follow_up_owner"]
    assert record["follow_up_due_date"] == payload["follow_up_due_date"]
    assert record["residual_risk"] == "medium"

    listed = client.get("/decision-records", headers=headers_a)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["records"]] == [record["id"]]
    scoped = client.get(f"/decision-records?analysis_id={analysis_id}", headers=headers_a)
    assert [row["id"] for row in scoped.json()["records"]] == [record["id"]]

    # A different account cannot see or attach a record to account A's report.
    assert client.get("/decision-records", headers=headers_b).json()["records"] == []
    assert client.get(
        f"/decision-records?analysis_id={analysis_id}", headers=headers_b
    ).status_code == 404
    assert client.post("/decision-records", headers=headers_b, json=payload).status_code == 404
    assert client.post(
        "/decision-records", headers=headers_a,
        json={**payload, "analysis_id": "missing-analysis"},
    ).status_code == 404

    blocked_approval = client.post(
        "/decision-records",
        headers=headers_a,
        json={**payload, "decision": "approve_alternate"},
    )
    assert blocked_approval.status_code == 400
    assert "manufacturer datasheet" in blocked_approval.json()["detail"].lower()


def test_decision_record_preserves_uploaded_datasheet_comparison_snapshot():
    from io import BytesIO
    from pypdf import PdfWriter

    client = TestClient(app)
    headers = _auth_headers(client)
    pdf = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)

    response = client.post(
        "/decision-records",
        headers=headers,
        data={
            "part_a": "AM29F010B70EC",
            "part_b": "SST39SF010A-70-4C-TU",
            "decision": "hold_for_review",
            "reviewer": "Engineering reviewer",
            "rationale": "Review the exact manufacturer datasheets and board footprint.",
            "validation_checks": "[]",
            "residual_risk": "unknown",
        },
        files={"datasheet_a": ("am29f010b.pdf", pdf.getvalue(), "application/pdf")},
    )

    assert response.status_code == 201, response.text
    snapshot = response.json()["record"]["comparison_snapshot"]
    assert snapshot["mode"] == "uploaded-datasheet-review"
    assert "datasheet_identity" in snapshot
    assert "package_dimension_evidence" in snapshot


def test_compare_can_record_workspace_decision_without_linking_latest_bom():
    client = TestClient(app)
    headers = _auth_headers(client)
    analyze = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("synthetic_bom_25parts.csv", FIXTURE.read_bytes(), "text/csv")},
    )
    assert analyze.status_code == 200
    saved = client.post(
        "/decision-records",
        headers=headers,
        json={
            "part_a": "LM358",
            "part_b": "LM358P",
            "decision": "retain_current_part",
            "reviewer": "Engineering reviewer",
            "rationale": "No verified fit evidence was retrieved.",
        },
    )
    assert saved.status_code == 201, saved.text
    record = saved.json()["record"]
    assert record["analysis_id"] is None
    assert record["comparison_snapshot"]["mode"] == "synthetic-preview"

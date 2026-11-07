"""Synthetic migration API — no Stripe, email, or live suppliers."""
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

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "tests" / "fixtures" / "synthetic_bom_25parts.csv"


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


def test_health_and_synthetic_bom_flow():
    client = TestClient(app)
    health = client.get("/health").json()
    assert health["ok"] is True
    assert health["suppliers"] == "disabled"
    assert health["stripe"] == "one-time-report-managed-by-supabase-edge-function"
    assert health["stripe_checkout_enabled"] is False
    assert health["email"] == "disabled"
    assert health["auth"]["mode"] == "sandbox-jwt-membership"
    assert health["auth"]["smoke_login_default"] is False

    bad = client.post(
        "/auth/login",
        json={"email": "nope@example.com", "password": "x"},
    )
    assert bad.status_code == 401

    smoke_gone = client.post(
        "/auth/smoke-login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    assert smoke_gone.status_code == 410

    login = client.post(
        "/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert token.count(".") == 2
    assert token != "cadivor-nextjs-smoke-token"

    with CSV.open("rb") as handle:
        analyze = client.post(
            "/boms/analyze",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("synthetic_bom_25parts.csv", handle, "text/csv")},
        )
    assert analyze.status_code == 200, analyze.text
    body = analyze.json()
    assert body["total_parts"] == 25
    assert body["health_score"] is not None
    assert body["mode"] == "synthetic-preview"
    assert body["workspace_id"] == "ws-sandbox-a"

    report = client.get(
        f"/reports/{body['analysis_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert report.status_code == 200
    payload = report.json()
    assert payload["total_parts"] == 25
    assert len(payload["parts"]) == 25


def test_boms_validate_route_no_analysis_side_effects():
    """POST /boms/validate must not score risk, create a report, or mutate analyses."""
    from apps.api import synthetic_analyze as sa

    client = TestClient(app)
    login = client.post(
        "/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    before_ids = set(sa._REPORTS.keys())

    payload = b"MPN,Quantity,Manufacturer\nAAA,2,TI\nAAA,3,TI\nBBB,1,ST\n"
    response = client.post(
        "/boms/validate",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("dup.csv", payload, "text/csv")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["can_analyze"] is True
    assert body["row_count"] == 3
    assert body["unique_part_count"] == 2
    assert body["parsed_row_count"] == 2
    assert set(sa._REPORTS.keys()) == before_ids

    nested = (ROOT / "tests" / "fixtures" / "nested_bom_product.csv").read_bytes()
    nested_resp = client.post(
        "/boms/validate",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("nested_bom_product.csv", nested, "text/csv")},
    )
    assert nested_resp.status_code == 200, nested_resp.text
    nested_body = nested_resp.json()
    assert nested_body["row_count"] == 7
    assert nested_body["has_hierarchy_columns"] is True
    assert set(sa._REPORTS.keys()) == before_ids


def test_boms_validate_rejects_oversize_with_413():
    client = TestClient(app)
    login = client.post(
        "/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    token = login.json()["access_token"]
    from apps.api.bom_validation import MAX_BOM_UPLOAD_BYTES

    huge = b"x" * (MAX_BOM_UPLOAD_BYTES + 1)
    response = client.post(
        "/boms/validate",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("huge.csv", huge, "text/csv")},
    )
    assert response.status_code == 413, response.text
    body = response.json()
    assert body.get("code") == "payload_too_large"
    assert "10 MB" in body.get("detail", "")


def test_two_reports_keep_requested_analysis_selected_for_monitoring():
    """Monitoring must honor the explicit analysis_id from the report CTA."""
    client = TestClient(app)
    login = client.post(
        "/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    ids = []
    for name in ("first.csv", "second.csv"):
        csv = b"MPN,Quantity,Manufacturer\nPART-A,1,TI\nPART-B,2,ST\n"
        analyze = client.post(
            "/boms/analyze",
            headers=headers,
            files={"file": (name, csv, "text/csv")},
            data={"bom_name": name},
        )
        assert analyze.status_code == 200, analyze.text
        ids.append(analyze.json()["analysis_id"])
    first_id, second_id = ids
    assert first_id != second_id

    # Explicit query must select the intended report, not merely the latest.
    for chosen in (first_id, second_id):
        monitoring = client.get(
            f"/tools/monitoring?analysis_id={chosen}",
            headers=headers,
        )
        assert monitoring.status_code == 200, monitoring.text
        payload = monitoring.json()
        assert str(payload.get("analysis_id")) == str(chosen)


def test_bom_workflow_guide_states_runner():
    """CI entry: workflow stage contracts (initial/validating/ready/analyzing/success/error)."""
    from tests.test_bom_workflow_guide_states import BomWorkflowGuideStateTests

    case = BomWorkflowGuideStateTests("test_workflow_states_initial_validating_ready_analyzing_success_error")
    case.setUpClass()
    case.test_workflow_states_initial_validating_ready_analyzing_success_error()


def test_bom_analyze_job_account_isolation_runner():
    """CI entry: switching accounts while an analyze job is in flight."""
    from tests.test_bom_workflow_guide_states import BomWorkflowGuideStateTests

    case = BomWorkflowGuideStateTests("test_account_switch_while_analyze_job_running")
    case.setUpClass()
    case.test_account_switch_while_analyze_job_running()


def test_bom_analyze_job_workspace_isolation_runner():
    """CI entry: same user cannot observe workspace A jobs/drafts while in workspace B."""
    from tests.test_bom_workflow_guide_states import BomWorkflowGuideStateTests

    case = BomWorkflowGuideStateTests("test_same_user_workspace_isolation_for_jobs_and_drafts")
    case.setUpClass()
    case.test_same_user_workspace_isolation_for_jobs_and_drafts()


def test_bom_file_content_identity_runner():
    """CI entry: content identity distinguishes same name/size/mtime with different bytes."""
    from tests.test_bom_workflow_guide_states import BomWorkflowGuideStateTests

    case = BomWorkflowGuideStateTests("test_file_identity_distinguishes_same_meta_different_bytes")
    case.setUpClass()
    case.test_file_identity_distinguishes_same_meta_different_bytes()


def test_bom_validation_preview_module_suite():
    """CI entry: validation preview parity + no analyze side effects."""
    import unittest
    from tests.test_bom_validation_preview import BomValidationPreviewTests

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BomValidationPreviewTests)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    assert result.wasSuccessful(), result.failures + result.errors

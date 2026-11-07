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


def test_ci_includes_legal_acceptance_signup(capsys):
    """CI entry so legal acceptance signup tests always run with migration API suite."""
    import subprocess
    import sys

    targets = ["tests/test_legal_acceptance_signup.py"]
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "-v", "--tb=line"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    combined = proc.stdout + "\n" + proc.stderr
    # Bypass parent pytest capture so CI -q logs still name the nested files.
    with capsys.disabled():
        print("CI_NESTED_SUITE_START")
        for name in targets:
            print(f"CI_NESTED_SUITE_FILE={name}")
        print(combined)
        print("CI_NESTED_SUITE_END")
    assert proc.returncode == 0, combined
    assert "tests/test_legal_acceptance_signup.py" in combined
    assert "test_legal_acceptance_signup.py" in combined


def test_ci_includes_service_readiness_and_evidence_notice_files(capsys):
    """Run readiness + evidence-notice suites from the CI-included migration API module."""
    import subprocess
    import sys

    targets = [
        "tests/test_service_readiness.py",
        "tests/test_evidence_notice_behavior.py",
        "tests/test_evidence_notice_classification.py",
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "-v", "--tb=line"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    combined = proc.stdout + "\n" + proc.stderr
    # Bypass parent pytest capture so CI -q logs still name the nested files.
    with capsys.disabled():
        print("CI_NESTED_SUITE_START")
        for name in targets:
            print(f"CI_NESTED_SUITE_FILE={name}")
        print(combined)
        print("CI_NESTED_SUITE_END")
    assert proc.returncode == 0, combined
    for name in targets:
        assert name in combined
        assert name.split("/")[-1] in combined

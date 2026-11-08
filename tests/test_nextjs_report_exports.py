"""API tests for the workspace-scoped Next.js report downloads."""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import pytest
from openpyxl import load_workbook
from starlette.testclient import TestClient

from apps.api.main import app
from apps.api.report_exports import build_csv, build_report_export
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import SANDBOX_SEED_USERS, SMOKE_EMAIL, SMOKE_PASSWORD

ROOT = Path(__file__).resolve().parents[1]
CSV_FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_bom_25parts.csv"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    from apps.api import synthetic_analyze

    synthetic_analyze._REPORTS.clear()
    with TestClient(app) as test_client:
        yield test_client
    synthetic_analyze._REPORTS.clear()


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _create_report(client: TestClient, token: str) -> str:
    with CSV_FIXTURE.open("rb") as source:
        response = client.post(
            "/boms/analyze",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("motor controller rev C.csv", source, "text/csv")},
        )
    assert response.status_code == 200, response.text
    return response.json()["analysis_id"]


@pytest.mark.parametrize(
    ("file_format", "content_type"),
    [
        ("pdf", "application/pdf"),
        ("csv", "text/csv"),
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ],
)
def test_saved_report_exports_are_downloadable_and_workspace_scoped(
    client: TestClient, file_format: str, content_type: str
):
    token = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    analysis_id = _create_report(client, token)

    response = client.get(
        f"/reports/{analysis_id}/export/{file_format}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(content_type)
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "motor-controller-rev-C-risk-report" in response.headers["content-disposition"]

    if file_format == "pdf":
        assert response.content.startswith(b"%PDF-")
    elif file_format == "csv":
        text = response.content.decode("utf-8-sig")
        parsed = list(csv.DictReader(io.StringIO(text)))
        assert len(parsed) == 25
        assert {"MPN", "Risk Level", "Evidence Class", "Parent MPN"}.issubset(parsed[0])
        assert parsed[0]["Evidence Class"] == "synthetic-preview"
    else:
        assert zipfile.is_zipfile(io.BytesIO(response.content))

    other_token = _login(client, "sandbox-b@cadivor.test", "CadivorSandbox!b")
    denied = client.get(
        f"/reports/{analysis_id}/export/{file_format}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert denied.status_code == 404


def test_report_export_requires_auth_and_rejects_unknown_format(client: TestClient):
    token = _login(client, SMOKE_EMAIL, SMOKE_PASSWORD)
    analysis_id = _create_report(client, token)

    assert client.get(f"/reports/{analysis_id}/export/pdf").status_code == 401
    unsupported = client.get(
        f"/reports/{analysis_id}/export/docx",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert unsupported.status_code == 400
    assert "PDF, Excel, or CSV" in unsupported.json()["detail"]


def test_exports_preserve_synthetic_label_and_neutralize_formula_cells():
    report = {
        "project_name": "Demo",
        "bom_name": "demo.csv",
        "mode": "synthetic-preview",
        "parts": [
            {
                "MPN": "=1+1",
                "Manufacturer": "Example",
                "Risk Level": "Low",
                "source": "synthetic-preview",
            }
        ],
    }
    csv_text = build_csv(report).decode("utf-8-sig")
    assert "'=1+1" in csv_text
    assert "synthetic-preview" in csv_text

    workbook_bytes, media_type, extension = build_report_export(report, "xlsx")
    assert media_type.startswith("application/vnd.openxmlformats-officedocument")
    assert extension == "xlsx"
    assert zipfile.is_zipfile(io.BytesIO(workbook_bytes))
    workbook = load_workbook(io.BytesIO(workbook_bytes), data_only=False)
    # Mature Streamlit sheets must be present; Components remains for formula-safe audit rows.
    assert {"Summary", "Component Details", "High Risk Parts", "Alternative Candidates", "Components"}.issubset(
        set(workbook.sheetnames)
    )
    cell = workbook["Components"]["A2"]
    assert cell.data_type == "s"
    assert cell.value == "'=1+1"
    details = workbook["Component Details"]
    assert details["A2"].value == "'=1+1"

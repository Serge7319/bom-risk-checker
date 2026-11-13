"""UI/API smoke: Datasheet Q&A sends exact MPN/manufacturer and abstains on mismatch."""
from __future__ import annotations

import json
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
FIXTURE = ROOT / "tests/fixtures/datasheets/lm358dr_ti_excerpts.json"


def _pdf_bytes_from_excerpt_fixture() -> bytes:
    try:
        import fitz  # type: ignore
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"pymupdf required for PDF smoke: {exc}")
    data = json.loads(FIXTURE.read_text())
    doc = fitz.open()
    for page in data["pages"]:
        page_obj = doc.new_page()
        page_obj.insert_text((72, 72), str(page.get("text") or ""), fontsize=11)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    return TestClient(app)


def _login(client: TestClient) -> str:
    res = client.post(
        "/auth/login",
        json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
    )
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def test_ask_datasheet_client_appends_mpn_and_manufacturer():
    source = (ROOT / "apps/web/src/lib/api.ts").read_text()
    assert 'body.append("mpn", mpn)' in source
    assert 'body.append("manufacturer", manufacturer)' in source
    page = (ROOT / "apps/web/src/app/datasheet-qa/page.tsx").read_text()
    assert "mpn: selectedMpn" in page
    assert "manufacturer: manufacturer.trim()" in page
    assert 'id="mpn"' in page


def test_api_sends_identity_wrong_part_abstains_supported_cites_part(client: TestClient):
    token = _login(client)
    pdf = _pdf_bytes_from_excerpt_fixture()
    headers = {"Authorization": f"Bearer {token}"}

    wrong = client.post(
        "/tools/datasheet-qa",
        headers=headers,
        files={"file": ("lm358dr.pdf", pdf, "application/pdf")},
        data={
            "question": "What is the recommended operating supply voltage?",
            "mpn": "SN74LVC1G125DBVR",
            "manufacturer": "Texas Instruments",
        },
    )
    assert wrong.status_code == 200, wrong.text
    wrong_body = wrong.json()
    assert wrong_body["document"]["requested_mpn"] == "SN74LVC1G125DBVR"
    assert wrong_body["document"]["bound"] is False
    assert str(wrong_body.get("answer_kind") or "") == "needs_verification"
    assert "Needs verification" in str(wrong_body.get("answer") or "")

    supported = client.post(
        "/tools/datasheet-qa",
        headers=headers,
        files={"file": ("lm358dr.pdf", pdf, "application/pdf")},
        data={
            "question": "What is the recommended operating supply voltage?",
            "mpn": "LM358DR",
            "manufacturer": "Texas Instruments",
        },
    )
    assert supported.status_code == 200, supported.text
    body = supported.json()
    assert body["document"]["requested_mpn"] == "LM358DR"
    assert body["document"]["manufacturer"] == "Texas Instruments"
    assert body["document"]["bound"] is True
    answer = str(body.get("answer") or "")
    assert body.get("answer_kind") == "supported"
    assert "Needs verification" not in answer
    assert "3" in answer and "32" in answer
    citations = [str(c) for c in body.get("citations") or []]
    assert any("Page" in c for c in citations)
    assert body["document"]["requested_mpn"] == "LM358DR"
    assert body["document"]["bound"] is True
    source = body.get("source_document") or {}
    assert source.get("filename") or source.get("content_fingerprint")

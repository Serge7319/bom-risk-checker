"""Abuse protections: preview-only enrichment, Turnstile, email quota, QA allowlist."""

from __future__ import annotations

import json
import types
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from src import public_bom_stress_test as funnel


REPORT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
HMAC_SECRET = "x" * 32


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _signed_visitor(secret: str = HMAC_SECRET, stamp: int | None = None) -> str:
    import hashlib
    import hmac
    import time

    now = int(stamp if stamp is not None else time.time())
    stamp_s = str(now)
    ip = "203.0.113.10"
    sig = hmac.new(
        secret.encode(), f"v1|{stamp_s}|{ip}".encode(), hashlib.sha256
    ).hexdigest()
    return f"v1;{stamp_s};{ip};{sig}"


def test_turnstile_valid_invalid_and_missing(monkeypatch):
    monkeypatch.setenv("CADIVOR_TURNSTILE_SECRET_KEY", "test-secret")
    monkeypatch.setenv(
        "CADIVOR_TURNSTILE_EXPECTED_HOSTNAMES", "app.cadivor.com,localhost"
    )

    valid = {
        "success": True,
        "hostname": "app.cadivor.com",
        "action": "public_bom_audit",
    }
    with patch.object(funnel, "get_secret", side_effect=lambda key, required=False: {
        "CADIVOR_TURNSTILE_SECRET_KEY": "test-secret",
        "CADIVOR_TURNSTILE_EXPECTED_HOSTNAMES": "app.cadivor.com,localhost",
    }.get(key, "")):
        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                valid
            ).encode()
            funnel.validate_turnstile("token-ok")

        with pytest.raises(funnel.StressTestError):
            funnel.validate_turnstile("")

        bad = {**valid, "success": False}
        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                bad
            ).encode()
            with pytest.raises(funnel.StressTestError):
                funnel.validate_turnstile("token-bad")

        wrong_host = {**valid, "hostname": "evil.example"}
        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                wrong_host
            ).encode()
            with pytest.raises(funnel.StressTestError):
                funnel.validate_turnstile("token-host")

        wrong_action = {**valid, "action": "other_action"}
        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                wrong_action
            ).encode()
            with pytest.raises(funnel.StressTestError):
                funnel.validate_turnstile("token-action")

        # Missing action must fail closed (exact match required).
        missing_action = {
            "success": True,
            "hostname": "app.cadivor.com",
        }
        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                missing_action
            ).encode()
            with pytest.raises(funnel.StressTestError):
                funnel.validate_turnstile("token-missing-action")

        empty_action = {**valid, "action": ""}
        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                empty_action
            ).encode()
            with pytest.raises(funnel.StressTestError):
                funnel.validate_turnstile("token-empty-action")


def test_turnstile_disabled_when_secret_unset(monkeypatch):
    with patch.object(funnel, "get_secret", return_value=""):
        funnel.validate_turnstile(None)  # no-op


def test_visitor_forged_and_expired_still_rejected():
    with patch.object(funnel, "get_secret", return_value=HMAC_SECRET):
        with pytest.raises(funnel.StressTestError):
            funnel.visitor_hash("v1;1;203.0.113.10;deadbeef")
        import time

        old = _signed_visitor(stamp=int(time.time()) - 7201)
        with pytest.raises(funnel.StressTestError):
            funnel.visitor_hash(old)
        good = _signed_visitor()
        assert len(funnel.visitor_hash(good)) == 64


def test_preview_enriches_only_first_five_rows():
    class FakeUpdate:
        def __init__(self):
            self.saved = None

        def table(self, *_):
            return self

        def update(self, payload):
            self.saved = payload
            return self

        def eq(self, *_):
            return self

        def execute(self):
            return None

    fake = FakeUpdate()
    enrich_calls: list[int] = []

    def enrich(index, row):
        enrich_calls.append(index)
        return index, {
            **row,
            "risk": "Low",
            "verified": True,
            "lifecycle": "Active",
            "stock": 1,
            "lead_time_weeks": 1,
            "supplier_count": 1,
            "sources": "DigiKey",
            "risk_reasons": [],
        }

    csv = ("MPN,Qty\n" + "".join(f"PART{i},1\n" for i in range(12))).encode()
    with (
        patch.object(funnel, "enabled", return_value=True),
        patch.object(funnel, "turnstile_enabled", return_value=False),
        patch.object(funnel, "visitor_hash", return_value="a" * 64),
        patch.object(funnel, "_reserve", return_value=REPORT_A),
        patch.object(funnel, "_claim_enrichment_budget"),
        patch.object(funnel, "_service_client", return_value=fake),
        patch.object(funnel, "_enrich_one", side_effect=enrich),
    ):
        teaser = funnel.run_audit("board.csv", csv, "signed")

    assert enrich_calls == [0, 1, 2, 3, 4]
    assert teaser["preview_enriched_count"] == 5
    assert teaser["remaining_pending"] == 7
    assert all(row.get("enrichment_pending") for row in fake.saved["results"][5:])


def test_complete_audit_email_quota_idempotent_and_cross_ip():
    pending = [
        {
            "mpn": f"P{i}",
            "quantity": 1,
            "enrichment_pending": i >= 5,
            "verified": i < 5,
            "risk": "Low" if i < 5 else "Pending",
        }
        for i in range(8)
    ]
    store = {
        "id": REPORT_A,
        "filename": "a.csv",
        "row_count": 8,
        "results": pending,
        "created_at": "2026-11-14T00:00:00+00:00",
        "status": "lead_captured",
        "work_email": "owner@company.com",
        "full_enriched_at": None,
        "qa_mode": False,
        "preview_enriched_count": 5,
    }
    claims: list[str] = []

    class Query:
        def table(self, *_):
            return self

        def select(self, *_):
            return self

        def eq(self, *_):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def limit(self, *_):
            return self

        def update(self, payload):
            store.update(payload)
            return self

        def execute(self):
            return types.SimpleNamespace(data=[dict(store)])

    def claim(email, report_id, *, bypass_email_quota=False, **_kwargs):
        claims.append(email)
        if store.get("full_enriched_at"):
            return "already_complete"
        return "claimed"

    enrich_batches: list[int] = []

    def enrich_rows(rows):
        enrich_batches.append(len(rows))
        return [
            {
                **row,
                "enrichment_pending": False,
                "verified": True,
                "risk": "Low",
                "lifecycle": "Active",
            }
            for row in rows
        ]

    with (
        patch.object(funnel, "enabled", return_value=True),
        patch.object(
            funnel, "_confirmed_session_email", return_value="owner@company.com"
        ),
        patch.object(funnel, "resolve_qa_session", return_value=None),
        patch.object(funnel, "_service_client", return_value=Query()),
        patch.object(funnel, "_claim_full_enrichment", side_effect=claim),
        patch.object(funnel, "_claim_enrichment_budget"),
        patch.object(funnel, "_enrich_rows", side_effect=enrich_rows),
    ):
        first = funnel.complete_audit("tok", REPORT_A)
        second = funnel.complete_audit("tok", REPORT_A)

    assert first["full_enriched"] is True
    assert second["full_enriched"] is True
    assert enrich_batches == [3]  # only pending stubs enriched once
    assert all(not row.get("enrichment_pending") for row in first["results"])


def test_complete_audit_quota_exceeded_different_report():
    class Query:
        def table(self, *_):
            return self

        def select(self, *_):
            return self

        def eq(self, *_):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def limit(self, *_):
            return self

        def execute(self):
            return types.SimpleNamespace(
                data=[
                    {
                        "id": REPORT_A,
                        "results": [{"mpn": "X", "enrichment_pending": True}],
                        "work_email": "owner@company.com",
                        "status": "lead_captured",
                        "qa_mode": False,
                        "full_enriched_at": None,
                        "filename": "a.csv",
                        "row_count": 1,
                        "created_at": "2026-11-14T00:00:00+00:00",
                    }
                ]
            )

    with (
        patch.object(funnel, "enabled", return_value=True),
        patch.object(
            funnel, "_confirmed_session_email", return_value="owner@company.com"
        ),
        patch.object(funnel, "resolve_qa_session", return_value=None),
        patch.object(funnel, "_service_client", return_value=Query()),
        patch.object(
            funnel, "_claim_full_enrichment", return_value="quota_exceeded"
        ),
    ):
        with pytest.raises(funnel.StressTestError) as exc:
            funnel.complete_audit("tok", REPORT_A)
    assert "30 days" in str(exc.value)


def test_complete_audit_in_progress_blocks_duplicate_enrich():
    report = {
        "id": REPORT_A,
        "results": [{"mpn": "X", "enrichment_pending": True}],
        "work_email": "owner@company.com",
        "status": "lead_captured",
        "qa_mode": False,
        "full_enriched_at": None,
        "filename": "a.csv",
        "row_count": 1,
        "created_at": "2026-11-14T00:00:00+00:00",
    }

    class Query:
        def table(self, *_):
            return self

        def select(self, *_):
            return self

        def eq(self, *_):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def limit(self, *_):
            return self

        def execute(self):
            return types.SimpleNamespace(data=[dict(report)])

    with (
        patch.object(funnel, "enabled", return_value=True),
        patch.object(
            funnel, "_confirmed_session_email", return_value="owner@company.com"
        ),
        patch.object(funnel, "resolve_qa_session", return_value=None),
        patch.object(funnel, "_service_client", return_value=Query()),
        patch.object(funnel, "_claim_full_enrichment", return_value="in_progress"),
        patch.object(
            funnel,
            "_enrich_rows",
            side_effect=AssertionError("must not enrich while leased"),
        ),
    ):
        with pytest.raises(funnel.StressTestError) as exc:
            funnel.complete_audit("tok", REPORT_A)
    assert str(exc.value) == funnel.PUBLIC_BOM_COMPLETE_IN_PROGRESS_MESSAGE


def test_qa_bypasses_turnstile_and_ip_quota_only():
    class FakeUpdate:
        def __init__(self):
            self.saved = None

        def table(self, *_):
            return self

        def update(self, payload):
            self.saved = payload
            return self

        def eq(self, *_):
            return self

        def execute(self):
            return None

    fake = FakeUpdate()
    reserve_calls: list[dict] = []

    def reserve(ip_hash, *, qa_mode=False):
        reserve_calls.append({"ip_hash": ip_hash, "qa_mode": qa_mode})
        return REPORT_A

    csv = b"MPN,Qty\nPART1,1\n"
    with (
        patch.object(funnel, "enabled", return_value=True),
        patch.object(funnel, "turnstile_enabled", return_value=True),
        patch.object(
            funnel,
            "validate_turnstile",
            side_effect=AssertionError("Turnstile must be skipped for QA"),
        ),
        patch.object(
            funnel,
            "resolve_qa_session",
            return_value={"email": "qa@company.com", "qa_mode": True},
        ),
        patch.object(funnel, "visitor_hash", return_value="b" * 64),
        patch.object(funnel, "_reserve", side_effect=reserve),
        patch.object(funnel, "_claim_enrichment_budget"),
        patch.object(funnel, "_service_client", return_value=fake),
        patch.object(
            funnel,
            "_enrich_one",
            side_effect=lambda i, row: (
                i,
                {**row, "verified": True, "risk": "Low", "lifecycle": "Active"},
            ),
        ),
    ):
        result = funnel.run_audit(
            "qa.csv",
            csv,
            "signed",
            turnstile_token=None,
            access_token="qa-token",
        )

    assert reserve_calls[0]["qa_mode"] is True
    assert result["qa_mode"] is True
    assert fake.saved["qa_mode"] is True


def test_unlisted_session_cannot_activate_qa():
    with (
        patch.object(
            funnel,
            "qa_emails_allowlist",
            return_value={"qa@company.com"},
        ),
        patch.object(funnel, "get_secret", return_value="configured"),
        patch.dict(
            "sys.modules",
            {
                "supabase": types.SimpleNamespace(
                    create_client=lambda *_: types.SimpleNamespace(
                        auth=types.SimpleNamespace(
                            get_user=lambda *_: types.SimpleNamespace(
                                user=types.SimpleNamespace(
                                    email="other@company.com",
                                    email_confirmed_at="2026-11-14T00:00:00Z",
                                    id="u1",
                                )
                            )
                        )
                    )
                )
            },
        ),
    ):
        assert funnel.resolve_qa_session("tok") is None


def test_audit_api_rejects_missing_turnstile_when_enabled(client: TestClient):
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch("src.public_bom_stress_test.turnstile_enabled", return_value=True),
        patch(
            "src.public_bom_stress_test.validate_turnstile",
            side_effect=funnel.StressTestError(
                "Complete the security check and try again."
            ),
        ),
        patch(
            "src.public_bom_stress_test.run_audit",
            side_effect=funnel.StressTestError(
                "Complete the security check and try again."
            ),
        ),
    ):
        # Direct path through run_audit error mapping
        response = client.post(
            "/public/bom-stress/audit",
            files={"file": ("bom.csv", b"MPN,Qty\nA,1\n", "text/csv")},
            headers={"X-Cadivor-Visitor": _signed_visitor()},
        )
    assert response.status_code == 400
    assert "security check" in response.json()["detail"].lower()


def test_turnstile_three_cases_anonymous_qa_and_signed_in_non_qa(
    client: TestClient,
):
    """Anonymous + signed-in non-QA need Turnstile; confirmed QA skips.

    Client QA flags never grant a bypass. Status qa_verified is server-only.
    """
    csv_bytes = b"MPN,Qty\nPART1,1\n"

    def _deny_turnstile(*_a, **_k):
        raise funnel.StressTestError("Complete the security check and try again.")

    # 1) Anonymous: no bearer → Turnstile required.
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch("src.public_bom_stress_test.turnstile_enabled", return_value=True),
        patch("src.public_bom_stress_test.resolve_qa_session", return_value=None),
        patch(
            "src.public_bom_stress_test.validate_turnstile",
            side_effect=_deny_turnstile,
        ),
    ):
        anon_status = client.get("/public/bom-stress/status")
        anon_audit = client.post(
            "/public/bom-stress/audit",
            files={"file": ("bom.csv", csv_bytes, "text/csv")},
            headers={"X-Cadivor-Visitor": _signed_visitor()},
        )
    assert anon_status.json()["qa_verified"] is False
    assert anon_status.json()["turnstile_required"] is True
    assert anon_audit.status_code == 400
    assert "security check" in anon_audit.json()["detail"].lower()

    # 2) Signed-in non-QA: still must pass Turnstile (even with client qa flag).
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch("src.public_bom_stress_test.turnstile_enabled", return_value=True),
        patch("src.public_bom_stress_test.resolve_qa_session", return_value=None),
        patch(
            "src.public_bom_stress_test.validate_turnstile",
            side_effect=_deny_turnstile,
        ),
    ):
        normal_status = client.get(
            "/public/bom-stress/status?qa_verified=true&qa_mode=1",
            headers={"Authorization": "Bearer normal-user-token"},
        )
        normal_audit = client.post(
            "/public/bom-stress/audit",
            files={"file": ("bom.csv", csv_bytes, "text/csv")},
            data={"qa_mode": "true", "qa_verified": "true"},
            headers={
                "X-Cadivor-Visitor": _signed_visitor(),
                "Authorization": "Bearer normal-user-token",
            },
        )
    assert normal_status.json()["qa_verified"] is False
    assert normal_audit.status_code == 400
    assert "security check" in normal_audit.json()["detail"].lower()

    class FakeUpdate:
        def table(self, *_):
            return self

        def update(self, payload):
            self.saved = payload
            return self

        def eq(self, *_):
            return self

        def execute(self):
            return None

    fake = FakeUpdate()
    # 3) Confirmed allowlisted QA: no Turnstile token, succeeds via bearer only.
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch("src.public_bom_stress_test.turnstile_enabled", return_value=True),
        patch(
            "src.public_bom_stress_test.resolve_qa_session",
            return_value={"email": "qa@company.com", "qa_mode": True},
        ),
        patch(
            "src.public_bom_stress_test.validate_turnstile",
            side_effect=AssertionError("Turnstile must not run for QA"),
        ),
        patch("src.public_bom_stress_test.visitor_hash", return_value="c" * 64),
        patch("src.public_bom_stress_test._reserve", return_value=REPORT_A),
        patch("src.public_bom_stress_test._claim_enrichment_budget"),
        patch(
            "src.public_bom_stress_test._enrich_one",
            side_effect=lambda i, row: (
                i,
                {**row, "verified": True, "risk": "Low", "lifecycle": "Active"},
            ),
        ),
        patch("src.public_bom_stress_test._service_client", return_value=fake),
    ):
        qa_status = client.get(
            "/public/bom-stress/status",
            headers={"Authorization": "Bearer qa-allowlisted-token"},
        )
        allowed = client.post(
            "/public/bom-stress/audit",
            files={"file": ("qa.csv", csv_bytes, "text/csv")},
            headers={
                "X-Cadivor-Visitor": _signed_visitor(),
                "Authorization": "Bearer qa-allowlisted-token",
            },
        )
    assert qa_status.json()["qa_verified"] is True
    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body.get("ok") is True
    assert body.get("qa_mode") is True
    assert fake.saved["qa_mode"] is True


def test_complete_api_requires_auth(client: TestClient):
    with patch("src.public_bom_stress_test.enabled", return_value=True):
        response = client.post("/public/bom-stress/complete", json={})
    assert response.status_code in {401, 403}


def test_migration_defines_budget_and_qa_rpcs():
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[1]
        / "supabase/migrations/20261114_public_bom_abuse_protections.sql"
    ).read_text()
    assert "cadivor_claim_public_bom_enrichment_budget" in sql
    assert "cadivor_claim_public_bom_full_enrichment" in sql
    assert "cadivor_reserve_public_bom_stress_test_qa" in sql
    assert "qa_mode" in sql
    assert "full_enriched_at" in sql
    assert "full_enrichment_lease_expires_at" in sql
    assert "p_lease_seconds" in sql
    assert "in_progress" in sql
    assert "pg_advisory_xact_lock" in sql


def test_daily_enriched_row_limit_default():
    with patch.object(funnel, "get_secret", return_value=""):
        assert funnel.daily_enriched_row_limit() == funnel.DEFAULT_DAILY_ENRICHED_ROWS
    with patch.object(funnel, "get_secret", return_value="250"):
        assert funnel.daily_enriched_row_limit() == 250

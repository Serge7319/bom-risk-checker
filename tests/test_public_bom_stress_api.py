"""Unauthenticated FastAPI surface for the Next.js free BOM audit."""

from __future__ import annotations

import hashlib
import hmac
import time
import types
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from apps.api.main import app
from src import public_bom_stress_test as funnel
from src.public_bom_stress_test import (
    MAX_BYTES,
    PUBLIC_BOM_LIMIT_MESSAGE,
    StressTestError,
)


HMAC_SECRET = "a" * 48


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _signed_visitor(ip: str = "203.0.113.10", *, now: int | None = None) -> str:
    stamp = str(now if now is not None else int(time.time()))
    sig = hmac.new(
        HMAC_SECRET.encode(), f"v1|{stamp}|{ip}".encode(), hashlib.sha256
    ).hexdigest()
    return f"v1;{stamp};{ip};{sig}"


def test_public_bom_stress_status_requires_no_auth(client: TestClient):
    with patch("src.public_bom_stress_test.enabled", return_value=True):
        response = client.get("/public/bom-stress/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["enabled"] is True
    assert payload["preview_rows"] == 5
    assert payload["max_rows"] == 30
    assert payload["max_bytes"] == MAX_BYTES


def test_public_bom_stress_status_reports_disabled_flag(client: TestClient):
    with patch("src.public_bom_stress_test.enabled", return_value=False):
        response = client.get("/public/bom-stress/status")
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_public_bom_stress_audit_and_lead_fail_closed_when_disabled(client: TestClient):
    with patch("src.public_bom_stress_test.enabled", return_value=False):
        audit = client.post(
            "/public/bom-stress/audit",
            files={"file": ("sample.csv", b"MPN,Qty\nLM358N,1\n", "text/csv")},
        )
        lead = client.post(
            "/public/bom-stress/lead",
            json={
                "report_id": "report-1",
                "email": "a@b.com",
                "accepted_terms": True,
            },
            headers={"X-Cadivor-Visitor": _signed_visitor()},
        )
    assert audit.status_code == 503
    assert lead.status_code == 503
    assert "being prepared" in audit.json()["detail"]


def test_public_bom_stress_audit_rejects_missing_file(client: TestClient):
    with patch("src.public_bom_stress_test.enabled", return_value=True):
        response = client.post("/public/bom-stress/audit")
    assert response.status_code == 400
    assert "Missing file" in response.json()["detail"]


def test_public_bom_stress_audit_rejects_oversized_upload(client: TestClient):
    with patch("src.public_bom_stress_test.enabled", return_value=True):
        response = client.post(
            "/public/bom-stress/audit",
            files={
                "file": (
                    "huge.csv",
                    b"MPN,Qty\n" + b"PART,1\n" + (b"x" * (MAX_BYTES + 1)),
                    "text/csv",
                )
            },
        )
    assert response.status_code == 413
    assert "1 MB" in response.json()["detail"]


def test_public_bom_stress_audit_rejects_row_limit_via_funnel(client: TestClient):
    bom = b"MPN,Qty\n" + b"".join(f"PART{i},1\n".encode() for i in range(31))
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch(
            "src.public_bom_stress_test.get_secret",
            side_effect=lambda key, required=False: HMAC_SECRET
            if "HMAC" in str(key)
            else "",
        ),
    ):
        response = client.post(
            "/public/bom-stress/audit",
            files={"file": ("too-many.csv", bom, "text/csv")},
            headers={"X-Cadivor-Visitor": _signed_visitor()},
        )
    assert response.status_code == 400
    assert "1–30" in response.json()["detail"] or "30" in response.json()["detail"]


def test_forged_visitor_header_cannot_bypass_rate_correlation(client: TestClient):
    """X-Cadivor-Visitor is HMAC-checked correlation data, not client-trusted identity."""
    forged = f"v1;{int(time.time())};203.0.113.10;{'0' * 64}"
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch(
            "src.public_bom_stress_test.get_secret",
            side_effect=lambda key, required=False: HMAC_SECRET
            if "HMAC" in str(key)
            else "",
        ),
    ):
        response = client.post(
            "/public/bom-stress/audit",
            files={"file": ("sample.csv", b"MPN,Qty\nLM358N,1\n", "text/csv")},
            headers={"X-Cadivor-Visitor": forged},
        )
    assert response.status_code == 400
    assert "unavailable" in response.json()["detail"].lower()


def test_public_bom_stress_audit_returns_preview_only(client: TestClient):
    report = {
        "id": "report-1",
        "row_count": 6,
        "preview": [{"mpn": "LM358N", "risk": "Low"}],
        "remaining_count": 1,
        "remaining_high_risk": 0,
        "remaining_unverified": 0,
    }

    def fake_run(filename, payload, signed_header, **_kwargs):
        assert filename.endswith(".csv")
        assert payload.startswith(b"MPN")
        assert signed_header == "v1;signed"
        return report

    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch("src.public_bom_stress_test.run_audit", side_effect=fake_run),
    ):
        response = client.post(
            "/public/bom-stress/audit",
            files={"file": ("sample.csv", b"MPN,Qty\nLM358N,1\n", "text/csv")},
            headers={"X-Cadivor-Visitor": "v1;signed"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["id"] == "report-1"
    assert payload["preview"][0]["mpn"] == "LM358N"
    assert payload["remaining_count"] == 1
    assert "results" not in payload
    assert "remaining_preview" not in payload
    assert set(payload) <= {
        "ok",
        "id",
        "row_count",
        "preview",
        "remaining_count",
        "remaining_high_risk",
        "remaining_unverified",
        "remaining_pending",
        "preview_enriched_count",
        "qa_mode",
        "full_enriched",
    }


def test_public_routes_do_not_expose_workspace_reports(client: TestClient):
    denied = client.get("/reports")
    assert denied.status_code in {401, 403}
    public = client.get("/public/bom-stress/status")
    assert public.status_code == 200


def test_public_bom_stress_audit_maps_daily_limit(client: TestClient):
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch(
            "src.public_bom_stress_test.run_audit",
            side_effect=StressTestError(PUBLIC_BOM_LIMIT_MESSAGE),
        ),
    ):
        response = client.post(
            "/public/bom-stress/audit",
            files={"file": ("sample.csv", b"MPN,Qty\nLM358N,1\n", "text/csv")},
        )
    assert response.status_code == 429
    assert response.json()["detail"] == PUBLIC_BOM_LIMIT_MESSAGE


def test_public_bom_stress_lead_requires_terms(client: TestClient):
    with patch("src.public_bom_stress_test.enabled", return_value=True):
        response = client.post(
            "/public/bom-stress/lead",
            json={"report_id": "report-1", "email": "a@b.com", "accepted_terms": False},
        )
    assert response.status_code == 400
    assert "Terms" in response.json()["detail"]


def test_public_bom_stress_lead_rejects_invalid_visitor_header(client: TestClient):
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch(
            "src.public_bom_stress_test.get_secret",
            side_effect=lambda key, required=False: HMAC_SECRET
            if "HMAC" in str(key)
            else "",
        ),
        patch("src.public_bom_stress_test.send_report_verification") as send,
    ):
        response = client.post(
            "/public/bom-stress/lead",
            json={
                "report_id": "report-1",
                "email": "engineer@company.com",
                "accepted_terms": True,
            },
            headers={
                "X-Cadivor-Visitor": f"v1;{int(time.time())};203.0.113.10;{'0' * 64}"
            },
        )
    assert response.status_code == 400
    assert "unavailable" in response.json()["detail"].lower()
    send.assert_not_called()


def test_public_bom_stress_lead_sends_verification_once(client: TestClient):
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch(
            "src.public_bom_stress_test.request_full_report",
            return_value=("engineer@company.com", True),
        ) as request_full,
    ):
        response = client.post(
            "/public/bom-stress/lead?utm_source=guide",
            json={
                "report_id": "report-1",
                "email": "engineer@company.com",
                "accepted_terms": True,
            },
            headers={"X-Cadivor-Visitor": "v1;signed"},
        )
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "email": "engineer@company.com",
        "verification_sent": True,
    }
    request_full.assert_called_once()
    assert request_full.call_args.args[0] == "report-1"
    assert request_full.call_args.args[2] == "v1;signed"
    assert request_full.call_args.kwargs["source"] == "utm:guide"


class _AtomicClaimStore:
    """In-process stand-in for cadivor_claim_public_bom_verification."""

    def __init__(self):
        import threading

        self.lock = threading.Lock()
        self.report = {
            "id": "report-1",
            "row_count": 6,
            "status": "ready",
            "work_email": None,
            "results": [],
        }
        self.lead = {
            "report_id": "report-1",
            "work_email": "engineer@company.com",
            "verification_sent_at": None,
        }
        self.current = ""
        self._pending_update = None
        self._pending_upsert = None
        self._rpc_name = ""
        self._rpc_params = None
        self.cooldown_seconds = funnel.VERIFICATION_RESEND_COOLDOWN_SECONDS

    def table(self, name):
        self.current = name
        self._pending_update = None
        self._pending_upsert = None
        self._rpc_name = ""
        return self

    def rpc(self, name, params):
        self._rpc_name = name
        self._rpc_params = params
        return self

    def select(self, *_):
        return self

    def update(self, payload):
        self._pending_update = payload
        return self

    def upsert(self, payload, **_):
        self._pending_upsert = payload
        return self

    def eq(self, *_):
        return self

    def single(self):
        return self

    def _claim_rpc(self) -> bool:
        params = self._rpc_params or {}
        email = str(params.get("p_work_email") or "").strip().lower()
        cooldown = int(params.get("p_cooldown_seconds") or self.cooldown_seconds)
        with self.lock:
            prior = self.lead.get("verification_sent_at")
            if prior:
                prior_dt = datetime.fromisoformat(str(prior).replace("Z", "+00:00"))
                if prior_dt.tzinfo is None:
                    prior_dt = prior_dt.replace(tzinfo=timezone.utc)
                if prior_dt > datetime.now(timezone.utc) - timedelta(seconds=cooldown):
                    return False
            if self.lead.get("work_email") != email:
                return False
            self.lead["verification_sent_at"] = datetime.now(timezone.utc).isoformat()
            return True

    def execute(self):
        if self._rpc_name == "cadivor_claim_public_bom_verification":
            return types.SimpleNamespace(data=self._claim_rpc())
        if self.current == "cadivor_public_bom_stress_tests":
            if self._pending_update is not None:
                self.report = {**self.report, **self._pending_update}
                self._pending_update = None
                return types.SimpleNamespace(data=[{"id": "report-1"}])
            return types.SimpleNamespace(data=dict(self.report))
        if self._pending_upsert is not None:
            prior_sent = self.lead.get("verification_sent_at")
            self.lead = {**self.lead, **self._pending_upsert}
            if "verification_sent_at" not in self._pending_upsert:
                self.lead["verification_sent_at"] = prior_sent
            self._pending_upsert = None
            return types.SimpleNamespace(data=[{"report_id": "report-1"}])
        if self._pending_update is not None:
            self.lead = {**self.lead, **self._pending_update}
            self._pending_update = None
            return types.SimpleNamespace(data=[{"report_id": "report-1"}])
        return types.SimpleNamespace(data=dict(self.lead))


def test_request_full_report_repeat_does_not_resend_email():
    """Durable cooldown: second call for same lead skips the mailer (mocked)."""
    store = _AtomicClaimStore()
    sends: list[str] = []
    header = _signed_visitor()
    with (
        patch.object(funnel, "_service_client", return_value=store),
        patch.object(funnel, "get_secret", return_value=HMAC_SECRET),
        patch.object(
            funnel,
            "send_report_verification",
            side_effect=lambda address, report_id=None: sends.append(address),
        ),
    ):
        email, sent_first = funnel.request_full_report(
            "report-1",
            "engineer@company.com",
            header,
            source="homepage_stress_test",
        )
        assert email == "engineer@company.com"
        assert sent_first is True
        assert sends == ["engineer@company.com"]
        assert store.lead["verification_sent_at"]

        email2, sent_second = funnel.request_full_report(
            "report-1",
            "engineer@company.com",
            header,
            source="homepage_stress_test",
        )
        assert email2 == "engineer@company.com"
        assert sent_second is False
        assert sends == ["engineer@company.com"]


def test_claim_verification_send_uses_atomic_rpc():
    store = _AtomicClaimStore()
    store.lead["verification_sent_at"] = datetime.now(timezone.utc).isoformat()
    with patch.object(funnel, "_service_client", return_value=store):
        assert funnel.claim_verification_send("report-1", "engineer@company.com") is False
    migration = (
        Path(__file__).resolve().parents[1]
        / "supabase/migrations/20261114_public_bom_lead_verification_cooldown.sql"
    ).read_text()
    assert "cadivor_claim_public_bom_verification" in migration
    assert "pg_advisory_xact_lock" in migration


def test_concurrent_claims_send_exactly_one_verification_email():
    """Only one concurrent request may win the DB claim and call the mailer."""
    import threading

    store = _AtomicClaimStore()
    sends: list[str] = []
    send_lock = threading.Lock()
    header = _signed_visitor()

    def fake_send(address: str, *, report_id: str | None = None) -> None:
        with send_lock:
            sends.append(address)

    def worker(_idx: int):
        return funnel.request_full_report(
            "report-1",
            "engineer@company.com",
            header,
            source="homepage_stress_test",
        )

    with (
        patch.object(funnel, "_service_client", return_value=store),
        patch.object(funnel, "get_secret", return_value=HMAC_SECRET),
        patch.object(funnel, "send_report_verification", side_effect=fake_send),
    ):
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(worker, i) for i in range(20)]
            results = [future.result() for future in as_completed(futures)]

    sent_flags = [sent for _, sent in results]
    assert sum(1 for flag in sent_flags if flag) == 1
    assert sends == ["engineer@company.com"]



def test_public_audit_failure_logs_do_not_embed_bom_or_tokens(client: TestClient, caplog):
    with (
        patch("src.public_bom_stress_test.enabled", return_value=True),
        patch(
            "src.public_bom_stress_test.run_audit",
            side_effect=RuntimeError("boom"),
        ),
        caplog.at_level("ERROR"),
    ):
        response = client.post(
            "/public/bom-stress/audit",
            files={
                "file": (
                    "secret.csv",
                    b"MPN,Qty\nTOPSECRET-MPN,1\n",
                    "text/csv",
                )
            },
            headers={"Authorization": "Bearer super-secret-token"},
        )
    assert response.status_code == 503
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "public_bom_stress_audit_failed" in joined
    assert "TOPSECRET-MPN" not in joined
    assert "super-secret-token" not in joined

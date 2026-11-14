"""Authenticated verified-report delivery for the public BOM audit."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from apps.api.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_verified_report_requires_auth(client: TestClient):
    response = client.get("/public/bom-stress/verified-report")
    assert response.status_code in {401, 403}


def test_verified_report_returns_owner_audit(client: TestClient):
    report = {
        "id": "report-owner",
        "filename": "board.csv",
        "row_count": 2,
        "results": [{"mpn": "LM358DR", "risk": "Low"}],
        "created_at": "2026-11-14T00:00:00+00:00",
    }

    with (
        patch(
            "apps.api.main._auth_context",
            return_value=(
                {
                    "email": "owner@company.com",
                    "user_id": "user-1",
                    "workspace": "ws",
                    "workspace_id": "ws-1",
                    "plan": "trial",
                },
                None,
            ),
        ),
        patch("apps.api.main._bearer_token", return_value="owner-token"),
        patch(
            "src.public_bom_stress_test.verified_report",
            return_value=report,
        ) as verified,
    ):
        response = client.get(
            "/public/bom-stress/verified-report?email=attacker@evil.com",
            headers={"Authorization": "Bearer owner-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["report"]["id"] == "report-owner"
    assert payload["report"]["results"][0]["mpn"] == "LM358DR"
    # Ownership must use the bearer token, never the caller-supplied email.
    verified.assert_called_once()
    assert verified.call_args.args[0] == "owner-token"
    assert verified.call_args.kwargs.get("report_id") in (None, "")


def test_verified_report_denies_when_funnel_returns_none(client: TestClient):
    with (
        patch(
            "apps.api.main._auth_context",
            return_value=(
                {
                    "email": "other@company.com",
                    "user_id": "user-2",
                    "workspace": "ws",
                    "workspace_id": "ws-2",
                    "plan": "trial",
                },
                None,
            ),
        ),
        patch("apps.api.main._bearer_token", return_value="other-token"),
        patch("src.public_bom_stress_test.verified_report", return_value=None),
    ):
        response = client.get(
            "/public/bom-stress/verified-report",
            headers={"Authorization": "Bearer other-token"},
        )
    assert response.status_code == 404


def test_verified_report_helper_rejects_unconfirmed_and_cross_user():
    from src import public_bom_stress_test as funnel
    import types

    class FakeAuth:
        def __init__(self, user):
            self.user = user

        def get_user(self, token):
            assert token == "tok"
            return types.SimpleNamespace(user=self.user)

    class FakeQuery:
        def __init__(self):
            self.filters = []

        def table(self, *_):
            return self

        def select(self, *_):
            return self

        def eq(self, key, value):
            self.filters.append((key, value))
            return self

        def gte(self, *_):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def limit(self, *_):
            return self

        def execute(self):
            return types.SimpleNamespace(
                data=[
                    {
                        "id": "r1",
                        "filename": "a.csv",
                        "row_count": 1,
                        "results": [{"mpn": "X"}],
                        "created_at": "2026-11-14T00:00:00+00:00",
                    }
                ]
            )

    unconfirmed = types.SimpleNamespace(
        email="owner@company.com", email_confirmed_at=None
    )
    confirmed = types.SimpleNamespace(
        email="owner@company.com", email_confirmed_at="2026-11-14T00:00:00Z"
    )
    supabase = types.SimpleNamespace(
        create_client=lambda *_: types.SimpleNamespace(
            auth=FakeAuth(unconfirmed)
        )
    )
    with (
        patch.object(funnel, "enabled", return_value=True),
        patch.dict("sys.modules", {"supabase": supabase}),
        patch.object(funnel, "get_secret", return_value="configured"),
    ):
        assert funnel.verified_report("tok") is None

    query = FakeQuery()
    supabase_ok = types.SimpleNamespace(
        create_client=lambda *_: types.SimpleNamespace(auth=FakeAuth(confirmed))
    )
    with (
        patch.object(funnel, "enabled", return_value=True),
        patch.dict("sys.modules", {"supabase": supabase_ok}),
        patch.object(funnel, "get_secret", return_value="configured"),
        patch.object(funnel, "_service_client", return_value=query),
    ):
        report = funnel.verified_report("tok")
    assert report["id"] == "r1"
    assert ("work_email", "owner@company.com") in query.filters
    assert ("status", "lead_captured") in query.filters

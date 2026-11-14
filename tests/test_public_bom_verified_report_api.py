"""Authenticated verified-report delivery for the public BOM audit."""

from __future__ import annotations

import types
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from apps.api.main import app


REPORT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
REPORT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
FOREIGN = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_verified_report_requires_auth(client: TestClient):
    response = client.get("/public/bom-stress/verified-report")
    assert response.status_code in {401, 403}


def test_verified_report_returns_owner_audit(client: TestClient):
    report = {
        "id": REPORT_A,
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
            f"/public/bom-stress/verified-report?email=attacker@evil.com&report_id={REPORT_A}",
            headers={"Authorization": "Bearer owner-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["report"]["id"] == REPORT_A
    assert payload["report"]["results"][0]["mpn"] == "LM358DR"
    # Ownership must use the bearer token, never the caller-supplied email.
    verified.assert_called_once()
    assert verified.call_args.args[0] == "owner-token"
    assert verified.call_args.kwargs.get("report_id") == REPORT_A


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
            f"/public/bom-stress/verified-report?report_id={FOREIGN}",
            headers={"Authorization": "Bearer other-token"},
        )
    assert response.status_code == 404


def test_verified_report_helper_rejects_unconfirmed_and_cross_user():
    from src import public_bom_stress_test as funnel

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
                        "id": REPORT_A,
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
    assert report["id"] == REPORT_A
    assert ("work_email", "owner@company.com") in query.filters
    assert ("status", "lead_captured") in query.filters


def test_verified_report_selects_owned_report_by_id_and_denies_cross_user():
    """Two leads for the same email each open their own BOM; foreign email denied."""
    from src import public_bom_stress_test as funnel

    rows = [
        {
            "id": REPORT_A,
            "work_email": "owner@company.com",
            "status": "lead_captured",
            "filename": "board-a.csv",
            "row_count": 1,
            "results": [{"mpn": "LM358DR"}],
            "created_at": "2026-11-13T00:00:00+00:00",
        },
        {
            "id": REPORT_B,
            "work_email": "owner@company.com",
            "status": "lead_captured",
            "filename": "board-b.csv",
            "row_count": 1,
            "results": [{"mpn": "MCP2551-I/SN"}],
            "created_at": "2026-11-14T00:00:00+00:00",
        },
        {
            "id": FOREIGN,
            "work_email": "other@company.com",
            "status": "lead_captured",
            "filename": "foreign.csv",
            "row_count": 1,
            "results": [{"mpn": "SECRET"}],
            "created_at": "2026-11-14T01:00:00+00:00",
        },
    ]

    class FakeAuth:
        def __init__(self, user):
            self.user = user

        def get_user(self, token):
            return types.SimpleNamespace(user=self.user)

    class SelectingQuery:
        def __init__(self, catalog):
            self.catalog = catalog
            self.filters = {}

        def table(self, *_):
            return self

        def select(self, *_):
            return self

        def eq(self, key, value):
            self.filters[key] = value
            return self

        def gte(self, *_):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def limit(self, *_):
            return self

        def execute(self):
            matched = []
            for row in self.catalog:
                if row["work_email"] != self.filters.get("work_email"):
                    continue
                if row["status"] != self.filters.get("status"):
                    continue
                if "id" in self.filters and row["id"] != self.filters["id"]:
                    continue
                matched.append(
                    {
                        "id": row["id"],
                        "filename": row["filename"],
                        "row_count": row["row_count"],
                        "results": row["results"],
                        "created_at": row["created_at"],
                    }
                )
            return types.SimpleNamespace(data=matched[:1])

    owner = types.SimpleNamespace(
        email="owner@company.com", email_confirmed_at="2026-11-14T00:00:00Z"
    )
    other = types.SimpleNamespace(
        email="other@company.com", email_confirmed_at="2026-11-14T00:00:00Z"
    )
    supabase_owner = types.SimpleNamespace(
        create_client=lambda *_: types.SimpleNamespace(auth=FakeAuth(owner))
    )
    supabase_other = types.SimpleNamespace(
        create_client=lambda *_: types.SimpleNamespace(auth=FakeAuth(other))
    )

    with (
        patch.object(funnel, "enabled", return_value=True),
        patch.dict("sys.modules", {"supabase": supabase_owner}),
        patch.object(funnel, "get_secret", return_value="configured"),
        patch.object(
            funnel, "_service_client", return_value=SelectingQuery(rows)
        ),
    ):
        first = funnel.verified_report("owner-tok", report_id=REPORT_A)
        second = funnel.verified_report("owner-tok", report_id=REPORT_B)

    assert first is not None and first["id"] == REPORT_A
    assert first["results"][0]["mpn"] == "LM358DR"
    assert second is not None and second["id"] == REPORT_B
    assert second["results"][0]["mpn"] == "MCP2551-I/SN"

    # Same email cannot open another user's report id even when the id is known.
    with (
        patch.object(funnel, "enabled", return_value=True),
        patch.dict("sys.modules", {"supabase": supabase_owner}),
        patch.object(funnel, "get_secret", return_value="configured"),
        patch.object(
            funnel, "_service_client", return_value=SelectingQuery(rows)
        ),
    ):
        assert funnel.verified_report("owner-tok", report_id=FOREIGN) is None

    # Cross-user: other email requesting owner's report_id is denied.
    with (
        patch.object(funnel, "enabled", return_value=True),
        patch.dict("sys.modules", {"supabase": supabase_other}),
        patch.object(funnel, "get_secret", return_value="configured"),
        patch.object(
            funnel, "_service_client", return_value=SelectingQuery(rows)
        ),
    ):
        assert funnel.verified_report("other-tok", report_id=REPORT_A) is None

def test_verified_report_api_forwards_selector_and_denies_cross_user(
    client: TestClient,
):
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
        patch("apps.api.main._bearer_token", return_value="other-tok"),
        patch(
            "src.public_bom_stress_test.verified_report", return_value=None
        ) as verified,
    ):
        denied = client.get(
            f"/public/bom-stress/verified-report?report_id={REPORT_A}",
            headers={"Authorization": "Bearer other-tok"},
        )
    assert denied.status_code == 404
    assert verified.call_args.kwargs.get("report_id") == REPORT_A

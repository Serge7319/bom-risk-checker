"""Signup / invite registration require terms acceptance and persist versions."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from apps.api.invitation_email import MemoryEmailSink, set_email_sink
import apps.api.main as api_main
from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.team_store import reset_team_store_for_tests
from apps.api.workspace_store import reset_store_for_tests
from apps.api import legal_acceptance
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)

ROOT = Path(__file__).resolve().parents[1]
INVITEE = "invite-terms@cadivor.test"
INVITEE_PASSWORD = "InviteePassword!12"


@pytest.fixture
def sink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.setenv("CADIVOR_LEGAL_ACCEPTANCE_PATH", str(tmp_path / "legal.json"))
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    reset_team_store_for_tests(tmp_path / "team.json")
    legal_acceptance.reset_legal_acceptances_for_tests()
    api_main._THROTTLE.clear()
    messages = MemoryEmailSink()
    set_email_sink(messages)
    yield messages
    set_email_sink(None)


@pytest.fixture
def client(sink: MemoryEmailSink) -> TestClient:
    del sink
    return TestClient(app)


def test_auth_config_exposes_published_versions(client: TestClient):
    res = client.get("/auth/config")
    assert res.status_code == 200
    body = res.json()
    assert body["terms_version"] == legal_acceptance.TERMS_VERSION
    assert body["privacy_version"] == legal_acceptance.PRIVACY_VERSION
    assert body["terms_url"].endswith("/#/terms")
    assert body["privacy_url"].endswith("/#/privacy")


def test_signup_rejects_missing_and_false_acceptance(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    import apps.api.supabase_auth as supabase_auth

    monkeypatch.setattr(api_main, "_use_supabase_auth", lambda: True)
    monkeypatch.setattr(supabase_auth, "signup_enabled", lambda: True)
    monkeypatch.setattr(supabase_auth, "signup", lambda *a, **k: None)

    missing = client.post(
        "/auth/signup",
        json={
            "email": "terms-missing@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Terms Lab",
        },
    )
    assert missing.status_code == 400
    assert "terms" in missing.json()["detail"].lower()

    falsey = client.post(
        "/auth/signup",
        json={
            "email": "terms-false@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Terms Lab",
            "accepted_terms": False,
        },
    )
    assert falsey.status_code == 400

    ok = client.post(
        "/auth/signup",
        json={
            "email": "terms-ok@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Terms Lab",
            "accepted_terms": True,
            "terms_version": legal_acceptance.TERMS_VERSION,
            "privacy_version": legal_acceptance.PRIVACY_VERSION,
        },
    )
    assert ok.status_code == 202, ok.text
    rows = legal_acceptance.list_acceptances(email="terms-ok@cadivor.test")
    assert len(rows) == 1
    assert rows[0]["terms_version"] == legal_acceptance.TERMS_VERSION
    assert rows[0]["privacy_version"] == legal_acceptance.PRIVACY_VERSION
    assert rows[0]["source"] == "signup"
    assert rows[0]["accepted_at"]
    uuid.UUID(rows[0]["id"])


def test_forged_terms_version_rejected_before_signup(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    import apps.api.supabase_auth as supabase_auth

    called: list[str] = []
    monkeypatch.setattr(api_main, "_use_supabase_auth", lambda: True)
    monkeypatch.setattr(supabase_auth, "signup_enabled", lambda: True)
    monkeypatch.setattr(
        supabase_auth,
        "signup",
        lambda *a, **k: called.append("signup"),
    )
    res = client.post(
        "/auth/signup",
        json={
            "email": "forged@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Terms Lab",
            "accepted_terms": True,
            "terms_version": "forged-evil-v99",
            "privacy_version": legal_acceptance.PRIVACY_VERSION,
        },
    )
    assert res.status_code == 400
    body = res.json()
    assert body.get("code") == "terms_version_mismatch"
    assert called == []
    assert legal_acceptance.list_acceptances(email="forged@cadivor.test") == []


def test_consent_storage_failure_blocks_signup(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    import apps.api.supabase_auth as supabase_auth

    called: list[str] = []
    monkeypatch.setattr(api_main, "_use_supabase_auth", lambda: True)
    monkeypatch.setattr(supabase_auth, "signup_enabled", lambda: True)
    monkeypatch.setattr(
        supabase_auth,
        "signup",
        lambda *a, **k: called.append("signup"),
    )
    monkeypatch.setattr(
        legal_acceptance,
        "record_acceptance",
        lambda **kwargs: (_ for _ in ()).throw(
            legal_acceptance.LegalAcceptanceError(
                "Cadivor could not record Terms acceptance. Account creation was not started.",
                status_code=503,
                code="consent_storage_failed",
            )
        ),
    )
    res = client.post(
        "/auth/signup",
        json={
            "email": "storage-fail@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Terms Lab",
            "accepted_terms": True,
            "terms_version": legal_acceptance.TERMS_VERSION,
            "privacy_version": legal_acceptance.PRIVACY_VERSION,
        },
    )
    assert res.status_code == 503
    body = res.json()
    assert body.get("code") == "consent_storage_failed"
    assert "account creation was not started" in body["detail"].lower()
    assert called == []


def test_fail_closed_without_durable_consent_store(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    import apps.api.supabase_auth as supabase_auth

    called: list[str] = []
    monkeypatch.setattr(api_main, "_use_supabase_auth", lambda: True)
    monkeypatch.setattr(supabase_auth, "signup_enabled", lambda: True)
    monkeypatch.setattr(
        supabase_auth,
        "signup",
        lambda *a, **k: called.append("signup"),
    )
    monkeypatch.delenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", raising=False)
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("CADIVOR_LEGAL_ACCEPTANCE_PATH", raising=False)

    res = client.post(
        "/auth/signup",
        json={
            "email": "no-store@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Terms Lab",
            "accepted_terms": True,
        },
    )
    assert res.status_code == 503
    assert res.json().get("code") == "consent_storage_unavailable"
    assert called == []


def test_same_second_acceptances_both_persist_with_unique_ids(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    del client
    fixed = "2026-11-07T19:00:00+00:00"
    monkeypatch.setattr(legal_acceptance, "utc_now", lambda: fixed)
    first = legal_acceptance.record_acceptance(
        email="same-second@cadivor.test",
        source="signup",
    )
    second = legal_acceptance.record_acceptance(
        email="same-second@cadivor.test",
        source="signup",
    )
    assert first["id"] != second["id"]
    uuid.UUID(first["id"])
    uuid.UUID(second["id"])
    rows = legal_acceptance.list_acceptances(email="same-second@cadivor.test")
    ids = {row["id"] for row in rows}
    assert first["id"] in ids and second["id"] in ids


def test_invitation_register_requires_acceptance_and_persists(
    client: TestClient, sink: MemoryEmailSink
):
    owner = client.post(
        "/auth/login", json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD}
    )
    assert owner.status_code == 200, owner.text
    headers = {"Authorization": f"Bearer {owner.json()['access_token']}"}
    invite = client.post(
        "/workspace/invitations",
        headers=headers,
        json={"email": INVITEE, "role": "engineer"},
    )
    assert invite.status_code in (200, 201), invite.text
    invite_token = str(sink.messages[-1]["invite_url"]).split("invite=", 1)[1]

    rejected = client.post(
        "/invitations/register",
        json={
            "token": invite_token,
            "email": INVITEE,
            "password": INVITEE_PASSWORD,
        },
    )
    assert rejected.status_code == 400

    rejected_false = client.post(
        "/invitations/register",
        json={
            "token": invite_token,
            "email": INVITEE,
            "password": INVITEE_PASSWORD,
            "accepted_terms": False,
        },
    )
    assert rejected_false.status_code == 400

    accepted = client.post(
        "/invitations/register",
        json={
            "token": invite_token,
            "email": INVITEE,
            "password": INVITEE_PASSWORD,
            "accepted_terms": True,
            "terms_version": legal_acceptance.TERMS_VERSION,
            "privacy_version": legal_acceptance.PRIVACY_VERSION,
        },
    )
    assert accepted.status_code == 200, accepted.text
    rows = legal_acceptance.list_acceptances(email=INVITEE)
    assert len(rows) == 1
    assert rows[0]["source"] == "invitation"
    assert rows[0]["terms_version"] == legal_acceptance.TERMS_VERSION
    assert rows[0]["accepted_at"]
    uuid.UUID(rows[0]["id"])


def test_ui_login_cta_and_terms_checkbox_contract():
    login = (ROOT / "apps/web/src/app/login/page.tsx").read_text(encoding="utf-8")
    signup = (ROOT / "apps/web/src/app/signup/page.tsx").read_text(encoding="utf-8")
    terms = (ROOT / "apps/web/src/components/TermsAcceptance.tsx").read_text(
        encoding="utf-8"
    )
    legal = (ROOT / "apps/web/src/lib/legalTerms.ts").read_text(encoding="utf-8")
    marketing = (ROOT / "marketing-web/index.html").read_text(encoding="utf-8")

    assert "Create an account · Start a 14-day trial" in login
    assert "signupEnabled" in login
    assert "New teammates join through a workspace invitation link" in login
    assert "TermsAcceptance" in signup and "TermsAcceptance" in login
    assert "TERMS_URL" in terms and "PRIVACY_URL" in terms
    assert "https://www.cadivor.com/#/terms" in legal
    assert "https://www.cadivor.com/#/privacy" in legal
    assert "Pre-launch" not in legal
    assert "requires review by qualified counsel" not in legal
    assert "Use of the service" in legal
    assert "Information we collect" in legal
    assert "Users are responsible for authorized use of their accounts" in marketing
    assert "Users are responsible for authorized use of their accounts" in legal
    assert "Cadivor does not sell personal information" in marketing
    assert "Cadivor does not sell personal information" in legal
    assert "acceptedTerms" in signup
    assert re.search(r'type="checkbox"', terms)


def test_migration_file_exists():
    path = ROOT / "supabase/migrations/20261107_legal_acceptances.sql"
    assert path.is_file()
    sql = path.read_text(encoding="utf-8")
    assert "migration_legal_acceptances" in sql
    assert "terms_version" in sql
    assert "privacy_version" in sql
    assert "accepted_at" in sql


def _has_embedded_postgres() -> bool:
    import importlib.util

    return (
        importlib.util.find_spec("embedded_postgres") is not None
        and importlib.util.find_spec("psycopg") is not None
    )


@pytest.mark.skipif(not _has_embedded_postgres(), reason="embedded_postgres/psycopg required")
def test_postgres_same_second_acceptances_both_persist(tmp_path, monkeypatch):
    """UUID ids must both insert under Postgres (no silent ON CONFLICT discard)."""
    import embedded_postgres

    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    server = embedded_postgres.get_server(pgdata, cleanup_mode="delete")
    uri = server.get_uri(database="postgres")
    monkeypatch.setenv("CADIVOR_MIGRATION_DATABASE_URL", uri)
    monkeypatch.delenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", raising=False)
    monkeypatch.delenv("CADIVOR_LEGAL_ACCEPTANCE_PATH", raising=False)
    legal_acceptance.reset_legal_acceptances_for_tests()
    legal_acceptance.ensure_schema(uri)
    fixed = "2026-11-07T19:00:00+00:00"
    monkeypatch.setattr(legal_acceptance, "utc_now", lambda: fixed)
    first = legal_acceptance.record_acceptance(
        email="pg-same-second@cadivor.test", source="signup"
    )
    second = legal_acceptance.record_acceptance(
        email="pg-same-second@cadivor.test", source="signup"
    )
    assert first["id"] != second["id"]
    rows = legal_acceptance.list_acceptances(email="pg-same-second@cadivor.test")
    ids = {row["id"] for row in rows}
    assert first["id"] in ids and second["id"] in ids
    try:
        server.__exit__(None, None, None)
    except Exception:
        pass


def test_signup_rate_limited_before_consent_write(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    import apps.api.supabase_auth as supabase_auth

    calls: list[str] = []
    monkeypatch.setattr(api_main, "_use_supabase_auth", lambda: True)
    monkeypatch.setattr(supabase_auth, "signup_enabled", lambda: True)
    monkeypatch.setattr(
        supabase_auth,
        "signup",
        lambda *a, **k: calls.append("signup") or {"user_id": "u-rate", "email": a[0]},
    )
    api_main._THROTTLE.clear()
    payload = {
        "email": "rate-limit@cadivor.test",
        "password": "long-password-123",
        "workspace_name": "Rate Lab",
        "accepted_terms": True,
        "terms_version": legal_acceptance.TERMS_VERSION,
        "privacy_version": legal_acceptance.PRIVACY_VERSION,
    }
    # Exhaust the 5/10min bucket.
    for _ in range(5):
        res = client.post("/auth/signup", json={**payload, "email": f"rl{_}@cadivor.test"})
        assert res.status_code in {202, 429}, res.text
    blocked = client.post("/auth/signup", json={**payload, "email": "rl-final@cadivor.test"})
    assert blocked.status_code == 429
    assert blocked.json().get("code") == "signup_rate_limited"
    assert legal_acceptance.list_acceptances(email="rl-final@cadivor.test") == []


def test_captcha_required_validated_before_consent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    import apps.api.supabase_auth as supabase_auth

    monkeypatch.setattr(api_main, "_use_supabase_auth", lambda: True)
    monkeypatch.setattr(supabase_auth, "signup_enabled", lambda: True)
    monkeypatch.setenv("CADIVOR_SIGNUP_CAPTCHA_REQUIRED", "1")
    api_main._THROTTLE.clear()
    called: list[str] = []
    monkeypatch.setattr(
        supabase_auth,
        "signup",
        lambda *a, **k: called.append("signup"),
    )
    res = client.post(
        "/auth/signup",
        json={
            "email": "need-captcha@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Captcha Lab",
            "accepted_terms": True,
            "terms_version": legal_acceptance.TERMS_VERSION,
            "privacy_version": legal_acceptance.PRIVACY_VERSION,
        },
    )
    assert res.status_code == 400
    assert called == []
    assert legal_acceptance.list_acceptances(email="need-captcha@cadivor.test") == []


def test_repeated_valid_signup_reuses_acceptance_row(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    import apps.api.supabase_auth as supabase_auth

    monkeypatch.setattr(api_main, "_use_supabase_auth", lambda: True)
    monkeypatch.setattr(supabase_auth, "signup_enabled", lambda: True)
    monkeypatch.setattr(
        supabase_auth,
        "signup",
        lambda *a, **k: {"user_id": "user-reuse-1", "email": a[0]},
    )
    api_main._THROTTLE.clear()
    payload = {
        "email": "reuse@cadivor.test",
        "password": "long-password-123",
        "workspace_name": "Reuse Lab",
        "accepted_terms": True,
        "terms_version": legal_acceptance.TERMS_VERSION,
        "privacy_version": legal_acceptance.PRIVACY_VERSION,
    }
    first = client.post("/auth/signup", json=payload)
    second = client.post("/auth/signup", json=payload)
    assert first.status_code == 202
    assert second.status_code == 202
    rows = legal_acceptance.list_acceptances(email="reuse@cadivor.test")
    assert len(rows) == 1
    assert rows[0].get("user_id") == "user-reuse-1"
    assert second.json().get("acceptance_identity") == "user_id"


def test_email_only_acceptance_identity_when_no_user_returned(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    import apps.api.supabase_auth as supabase_auth

    monkeypatch.setattr(api_main, "_use_supabase_auth", lambda: True)
    monkeypatch.setattr(supabase_auth, "signup_enabled", lambda: True)
    monkeypatch.setattr(
        supabase_auth,
        "signup",
        lambda *a, **k: {"user_id": None, "email": a[0]},
    )
    api_main._THROTTLE.clear()
    res = client.post(
        "/auth/signup",
        json={
            "email": "email-only@cadivor.test",
            "password": "long-password-123",
            "workspace_name": "Email Lab",
            "accepted_terms": True,
            "terms_version": legal_acceptance.TERMS_VERSION,
            "privacy_version": legal_acceptance.PRIVACY_VERSION,
        },
    )
    assert res.status_code == 202
    body = res.json()
    assert body.get("acceptance_identity") == "email"
    assert body.get("acceptance_user_linked") is False
    rows = legal_acceptance.list_acceptances(email="email-only@cadivor.test")
    assert len(rows) == 1
    assert rows[0].get("user_id") in (None, "")


def test_public_roles_cannot_read_or_write_legal_acceptances(tmp_path, monkeypatch):
    """RLS + revoked grants: anon/authenticated/public cannot touch acceptance rows."""
    embedded = pytest.importorskip("embedded_postgres")
    root = tmp_path / "legal-pg"
    root.mkdir()
    server = embedded.get_server(root / "pgdata", cleanup_mode="delete")
    uri = server.get_uri(database="postgres")
    monkeypatch.setenv("CADIVOR_MIGRATION_DATABASE_URL", uri)
    monkeypatch.delenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", raising=False)
    legal_acceptance.reset_legal_acceptances_for_tests()
    legal_acceptance.ensure_schema(uri)

    import psycopg

    with psycopg.connect(uri) as conn:
        conn.execute("COMMIT")
        with conn.cursor() as cur:
            # Apply migration-equivalent security for roles that exist locally.
            for role in ("anon", "authenticated"):
                cur.execute(f"DO $$ BEGIN CREATE ROLE {role}; EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
            cur.execute("ALTER TABLE migration_legal_acceptances ENABLE ROW LEVEL SECURITY")
            try:
                cur.execute("ALTER TABLE migration_legal_acceptances FORCE ROW LEVEL SECURITY")
            except Exception:
                pass
            for role in ("anon", "authenticated", "PUBLIC"):
                cur.execute(f"REVOKE ALL ON TABLE migration_legal_acceptances FROM {role}")
            # Drop any permissive policies if present.
            cur.execute(
                """
                DO $$
                DECLARE r record;
                BEGIN
                  FOR r IN
                    SELECT policyname FROM pg_policies
                    WHERE tablename = 'migration_legal_acceptances'
                  LOOP
                    EXECUTE format('DROP POLICY IF EXISTS %I ON migration_legal_acceptances', r.policyname);
                  END LOOP;
                END $$;
                """
            )
        conn.commit()

    # Server-side insert still works (table owner / migration connection).
    row = legal_acceptance.record_acceptance(
        email="rls@cadivor.test",
        source="signup",
    )
    assert row["id"]

    with psycopg.connect(uri) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            for role in ("anon", "authenticated"):
                cur.execute(f"SET ROLE {role}")
                with pytest.raises(Exception):
                    cur.execute("SELECT count(*) FROM migration_legal_acceptances")
                with pytest.raises(Exception):
                    cur.execute(
                        """
                        INSERT INTO migration_legal_acceptances
                          (id, email, source, terms_version, privacy_version)
                        VALUES ('x', 'evil@cadivor.test', 'signup', 't', 'p')
                        """
                    )
                cur.execute("RESET ROLE")

    try:
        server.__exit__(None, None, None)  # type: ignore[attr-defined]
    except Exception:
        pass

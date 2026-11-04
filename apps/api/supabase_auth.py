"""Production Cadivor Supabase Auth for the Next.js migration API.

Verifies Supabase-issued access tokens server-side via Auth ``get_user`` using
the anon/publishable key (same pattern as Streamlit). Never requires or exposes
a service-role key. Workspace membership is stored only in the dedicated
``CADIVOR_MIGRATION_DATABASE_URL`` store — not in Streamlit production tables.

Sandbox HS256 auth remains in ``apps.api.sandbox_auth`` and stays fail-closed
when ``is_production_runtime()`` is true.
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from typing import Any

from apps.api.sandbox_auth import (
    AuthContext,
    AuthError,
    AuthNotConfiguredError,
    get_auth_store,
    is_production_runtime,
)
from apps.api.workspace_store import migration_database_url

_TEST_WORKSPACE_PREFIX = "ws-next-prod-test"


def supabase_url() -> str:
    return (os.environ.get("SUPABASE_URL") or "").strip()


def supabase_anon_key() -> str:
    """Anon/publishable key only — never service_role."""
    return (
        (os.environ.get("SUPABASE_KEY") or "").strip()
        or (os.environ.get("SUPABASE_ANON_KEY") or "").strip()
    )


def missing_config_vars() -> list[str]:
    """Return required env var *names* that are unset (never values)."""
    from apps.api.workspace_store import allow_ephemeral_file_store

    missing: list[str] = []
    if not supabase_url():
        missing.append("SUPABASE_URL")
    if not supabase_anon_key():
        missing.append("SUPABASE_KEY")
    # Dedicated migration Postgres is required on Railway; local/tests may use
    # the explicit ephemeral file store.
    if not migration_database_url() and not allow_ephemeral_file_store():
        missing.append("CADIVOR_MIGRATION_DATABASE_URL")
    return missing


def supabase_auth_configured() -> bool:
    return not missing_config_vars()


def describe_supabase_auth() -> dict[str, Any]:
    missing = missing_config_vars()
    ready = not missing
    return {
        "mode": "supabase-jwt-membership" if ready else "unconfigured",
        "production_auth": True,
        "sandbox_only": False,
        "production_runtime": is_production_runtime(),
        "token_verification": "server-side-supabase-get-user" if ready else None,
        "workspace_source": "migration_membership_table" if ready else None,
        "client_workspace_id_trusted": False,
        "service_role_used": False,
        "migration_database_separate_from_streamlit_store": True,
        "missing_config_vars": missing,
        "setup_required": (
            [f"Set {name} on the production Next API service only." for name in missing]
            + [
                "CADIVOR_MIGRATION_DATABASE_URL must be a dedicated production "
                "migration Postgres — not the Streamlit Supabase database URL "
                "and not the sandbox migration DB.",
                "Do not set SUPABASE_SERVICE_ROLE_KEY on the Next web service.",
                "Keep CADIVOR_SANDBOX_AUTH_SECRET unset/unused on production; "
                "sandbox HS256 remains fail-closed.",
            ]
            if missing
            else []
        ),
    }


def _require_configured() -> tuple[str, str]:
    missing = missing_config_vars()
    if missing:
        raise AuthNotConfiguredError(
            "Supabase Auth is not configured for the Next migration API. "
            f"Missing: {', '.join(missing)}"
        )
    return supabase_url(), supabase_anon_key()


def _client():
    from supabase import create_client

    url, key = _require_configured()
    return create_client(url, key)


def _token_fingerprint(access_token: str) -> str:
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()


def _workspace_ids_for_owner(user_id: str, email: str) -> tuple[str, str]:
    slug = re.sub(r"[^a-z0-9]+", "-", (email or "owner").lower()).strip("-")[:24] or "owner"
    short = re.sub(r"[^a-f0-9]", "", user_id.lower())[:12] or uuid.uuid4().hex[:12]
    workspace_id = f"{_TEST_WORKSPACE_PREFIX}-{short}"
    workspace_name = f"Next migration test · {slug}"
    return workspace_id, workspace_name


def ensure_owner_membership(*, user_id: str, email: str, plan: str = "Trial") -> dict[str, str]:
    """Create/reuse a dedicated test workspace for the signed-in Supabase owner."""
    if not user_id or not email:
        raise AuthError("Authenticated user missing id or email")
    if not migration_database_url():
        # Allow ephemeral file store only for unit tests / local preview.
        railway_env = (os.environ.get("RAILWAY_ENVIRONMENT") or "").strip()
        allow_file = (os.environ.get("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE") or "").strip() == "1"
        if railway_env or not allow_file:
            raise AuthNotConfiguredError(
                "CADIVOR_MIGRATION_DATABASE_URL is required for Supabase membership"
            )
    store = get_auth_store()
    existing = store.membership_for_user(user_id)
    if existing:
        return {
            "user_id": user_id,
            "email": email.strip().lower(),
            "workspace_id": str(existing["workspace_id"]),
            "workspace": str(existing.get("workspace_name") or existing["workspace_id"]),
            "plan": plan,
        }
    workspace_id, workspace_name = _workspace_ids_for_owner(user_id, email)
    return store.ensure_supabase_owner(
        user_id=user_id,
        email=email,
        workspace_id=workspace_id,
        workspace=workspace_name,
        plan=plan,
    )


def _user_payload(user: Any) -> tuple[str, str]:
    user_id = str(
        getattr(user, "id", None)
        or (user.get("id") if isinstance(user, dict) else "")
        or ""
    )
    email = str(
        getattr(user, "email", None)
        or (user.get("email") if isinstance(user, dict) else "")
        or ""
    ).strip().lower()
    if not user_id or not email:
        raise AuthError("Supabase user missing id or email")
    return user_id, email


def login(
    email: str, password: str, *, requested_workspace_id: str | None = None
) -> dict[str, Any]:
    """Sign in via Cadivor Supabase Auth; ignore client workspace_id."""
    _ = requested_workspace_id
    _require_configured()
    email_n = (email or "").strip().lower()
    if not email_n or not password:
        raise AuthError("Invalid credentials")
    client = _client()
    try:
        result = client.auth.sign_in_with_password(
            {"email": email_n, "password": password}
        )
    except Exception as exc:  # noqa: BLE001
        raise AuthError("Invalid credentials") from exc
    session = getattr(result, "session", None) or (
        result.get("session") if isinstance(result, dict) else None
    )
    user = getattr(result, "user", None) or (
        result.get("user") if isinstance(result, dict) else None
    )
    if session is None or user is None:
        raise AuthError("Invalid credentials")
    access_token = str(
        getattr(session, "access_token", None)
        or (session.get("access_token") if isinstance(session, dict) else "")
        or ""
    )
    if not access_token:
        raise AuthError("Invalid credentials")
    user_id, user_email = _user_payload(user)
    membership = ensure_owner_membership(user_id=user_id, email=user_email)
    expires_in = int(
        getattr(session, "expires_in", None)
        or (session.get("expires_in") if isinstance(session, dict) else 0)
        or 3600
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "email": membership["email"],
        "user_id": membership["user_id"],
        "workspace": membership["workspace"],
        "workspace_id": membership["workspace_id"],
        "plan": membership["plan"],
        "mode": "supabase-jwt",
        "sandbox_only": False,
        "production_auth": True,
    }


def logout(access_token: str) -> None:
    _require_configured()
    if not access_token:
        raise AuthError("Missing bearer token")
    get_auth_store().revoke(_token_fingerprint(access_token), exp=0)
    try:
        import urllib.request

        url, key = _require_configured()
        req = urllib.request.Request(
            f"{url.rstrip('/')}/auth/v1/logout",
            data=b"{}",
            method="POST",
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": key,
                "Content-Type": "application/json",
            },
        )
        urllib.request.urlopen(req, timeout=10).read()  # noqa: S310 — Auth host from env
    except Exception:  # noqa: BLE001
        pass


def resolve_bearer(access_token: str) -> AuthContext:
    _require_configured()
    if not access_token:
        raise AuthError("Missing bearer token")
    fingerprint = _token_fingerprint(access_token)
    store = get_auth_store()
    if store.is_revoked(fingerprint):
        raise AuthError("Token revoked")
    client = _client()
    try:
        response = client.auth.get_user(access_token)
    except Exception as exc:  # noqa: BLE001
        raise AuthError("Invalid token") from exc
    user = getattr(response, "user", None) or (
        response.get("user") if isinstance(response, dict) else None
    )
    if user is None:
        raise AuthError("Invalid token")
    user_id, email = _user_payload(user)
    membership = ensure_owner_membership(user_id=user_id, email=email)
    return AuthContext(
        user_id=membership["user_id"],
        email=membership["email"],
        workspace_id=membership["workspace_id"],
        workspace=membership["workspace"],
        plan=membership["plan"],
        access_token=access_token,
        jti=fingerprint,
        mode="supabase-jwt",
    )

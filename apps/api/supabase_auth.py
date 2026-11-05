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
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
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
TRIAL_DAYS = 14


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


def signup_enabled() -> bool:
    """Signup stays off until an operator enables verified-email onboarding."""
    return (
        is_production_runtime()
        and (os.environ.get("CADIVOR_SELF_SERVE_SIGNUP_ENABLED") or "").strip() == "1"
        and (os.environ.get("CADIVOR_SIGNUP_EMAIL_CONFIRMATION_CONFIRMED") or "").strip() == "1"
        and (os.environ.get("CADIVOR_SIGNUP_ABUSE_PROTECTION_CONFIRMED") or "").strip() == "1"
        and supabase_auth_configured()
        and bool(_signup_redirect_url())
        and (os.environ.get("CADIVOR_SIGNUP_CAPTCHA_REQUIRED") or "").strip() != "1"
    )


def _signup_redirect_url() -> str:
    """Return a same-origin HTTPS confirmation URL, or empty when not safe."""
    value = (os.environ.get("CADIVOR_SIGNUP_REDIRECT_URL") or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return ""
    origin = f"https://{parsed.netloc}".rstrip("/").lower()
    allowed = {
        item.strip().rstrip("/").lower()
        for item in (os.environ.get("CADIVOR_WEB_ORIGINS") or "").split(",")
        if item.strip()
    }
    return value if origin in allowed else ""


def _normalize_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _trial_fields(membership: dict[str, Any]) -> dict[str, Any]:
    started = _normalize_datetime(membership.get("trial_started_at"))
    ends = _normalize_datetime(membership.get("trial_ends_at"))
    if not started:
        started_dt = datetime.now(timezone.utc)
        started = started_dt.isoformat()
    else:
        started_dt = datetime.fromisoformat(started)
    if not ends:
        ends = (started_dt + timedelta(days=14)).isoformat()
    ends_dt = datetime.fromisoformat(ends)
    status = str(membership.get("subscription_status") or "trialing")
    remaining_seconds = (ends_dt - datetime.now(timezone.utc)).total_seconds()
    if status == "trialing" and remaining_seconds <= 0:
        status = "trial_expired"
    remaining_days = max(0, int((max(0.0, remaining_seconds) + 86399) // 86400))
    return {
        "trial_started_at": started,
        "trial_ends_at": ends,
        "trial_status": status,
        "trial_days_remaining": remaining_days,
    }


def trial_expired(context: dict[str, Any]) -> bool:
    """Expired trials may keep reading saved data but cannot run new analyses."""
    if str(context.get("trial_status") or "trialing") not in {"trialing", "trial_expired"}:
        return False
    if context.get("trial_status") == "trial_expired":
        return True
    end = _normalize_datetime(context.get("trial_ends_at"))
    return bool(end and datetime.now(timezone.utc) >= datetime.fromisoformat(end))


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


def ensure_owner_membership(
    *,
    user_id: str,
    email: str,
    plan: str = "Trial",
    workspace_name: str | None = None,
) -> dict[str, Any]:
    """Create/reuse a migration workspace and start its trial once."""
    if not user_id or not email:
        raise AuthError("Authenticated user missing id or email")
    if not migration_database_url():
        railway_env = (os.environ.get("RAILWAY_ENVIRONMENT") or "").strip()
        allow_file = (os.environ.get("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE") or "").strip() == "1"
        if railway_env or not allow_file:
            raise AuthNotConfiguredError(
                "CADIVOR_MIGRATION_DATABASE_URL is required for Supabase membership"
            )
    store = get_auth_store()
    existing = store.membership_for_user(user_id)
    if existing:
        workspace_id = str(existing["workspace_id"])
        existing_name = str(existing.get("workspace_name") or existing["workspace_id"])
        desired_name = existing_name
    else:
        workspace_id, existing_name = _workspace_ids_for_owner(user_id, email)
        desired_name = workspace_name or existing_name
    result = store.ensure_supabase_owner(
        user_id=user_id,
        email=email,
        workspace_id=workspace_id,
        workspace=desired_name,
        plan=plan,
    )
    return {
        "user_id": user_id,
        "email": email.strip().lower(),
        "workspace_id": str(result["workspace_id"]),
        "workspace": str(result.get("workspace") or desired_name),
        "plan": str(result.get("plan") or plan),
        **_trial_fields(result),
    }


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


def user_workspace_name(user: Any) -> str | None:
    metadata = getattr(user, "user_metadata", None) or (
        user.get("user_metadata") if isinstance(user, dict) else None
    )
    if not isinstance(metadata, dict):
        return None
    value = " ".join(str(metadata.get("workspace_name") or "").split())
    return value[:80] or None


def user_email_verified(user: Any) -> bool:
    for key in ("email_confirmed_at", "confirmed_at"):
        value = getattr(user, key, None) or (
            user.get(key) if isinstance(user, dict) else None
        )
        if value:
            return True
    return False


def signup(
    email: str,
    password: str,
    workspace_name: str,
    *,
    captcha_token: str | None = None,
) -> None:
    """Request Supabase's verified-email signup; provision after verified login."""
    if not signup_enabled():
        raise AuthNotConfiguredError("Self-serve signup is not enabled")
    email_n = (email or "").strip().lower()
    workspace_n = " ".join((workspace_name or "").split())
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email_n):
        raise AuthError("Enter a valid email address", 400)
    if len(password or "") < 12:
        raise AuthError("Use a password with at least 12 characters", 400)
    if not workspace_n or len(workspace_n) > 80:
        raise AuthError("Enter a workspace name of 1 to 80 characters", 400)
    captcha_required = (os.environ.get("CADIVOR_SIGNUP_CAPTCHA_REQUIRED") or "").strip() == "1"
    if captcha_required and not (captcha_token or "").strip():
        raise AuthError("Complete the security check and try again", 400)
    options: dict[str, Any] = {
        "email_redirect_to": _signup_redirect_url(),
        "data": {"workspace_name": workspace_n},
    }
    if captcha_token:
        options["captcha_token"] = captcha_token
    try:
        response = _client().auth.sign_up(
            {"email": email_n, "password": password, "options": options}
        )
    except Exception as exc:  # noqa: BLE001
        raise AuthError(
            "We could not send the verification email. Try again shortly or sign in if you already have an account.",
            503,
        ) from exc
    session = getattr(response, "session", None) or (
        response.get("session") if isinstance(response, dict) else None
    )
    if session is not None:
        raise AuthNotConfiguredError(
            "Email confirmation must be enabled in Supabase before signup can be enabled"
        )


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
    if signup_enabled() and not user_email_verified(user):
        raise AuthError("Verify your email address before signing in", 403)
    access_token = str(
        getattr(session, "access_token", None)
        or (session.get("access_token") if isinstance(session, dict) else "")
        or ""
    )
    if not access_token:
        raise AuthError("Invalid credentials")
    user_id, user_email = _user_payload(user)
    membership = ensure_owner_membership(
        user_id=user_id,
        email=user_email,
        workspace_name=user_workspace_name(user),
    )
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
        **_trial_fields(membership),
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
    membership = ensure_owner_membership(
        user_id=user_id,
        email=email,
        workspace_name=user_workspace_name(user),
    )
    return AuthContext(
        user_id=membership["user_id"],
        email=membership["email"],
        workspace_id=membership["workspace_id"],
        workspace=membership["workspace"],
        plan=membership["plan"],
        access_token=access_token,
        jti=fingerprint,
        mode="supabase-jwt",
        trial_started_at=membership.get("trial_started_at"),
        trial_ends_at=membership.get("trial_ends_at"),
        trial_status=membership.get("trial_status"),
        trial_days_remaining=membership.get("trial_days_remaining"),
    )

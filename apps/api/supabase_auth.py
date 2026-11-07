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
import threading
import time
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
_ENTITLEMENT_CACHE_TTL_SECONDS = 20
_ENTITLEMENT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_ENTITLEMENT_CACHE_LOCK = threading.RLock()


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


def account_entitlements(access_token: str) -> dict[str, Any]:
    """Read authoritative billing entitlements through the Supabase Edge Function.

    The Edge Function reads ``public.users`` with its service-role client after
    verifying this user's JWT. A profile row selected with the user's own JWT
    is not trusted for plan or role because ordinary profile-update policies
    must not become a billing authorization boundary.
    """
    from apps.api import subscription_billing_service

    cache_key = _token_fingerprint(access_token)
    now = time.monotonic()
    with _ENTITLEMENT_CACHE_LOCK:
        cached = _ENTITLEMENT_CACHE.get(cache_key)
        if cached and now - cached[0] < _ENTITLEMENT_CACHE_TTL_SECONDS:
            return dict(cached[1])

    try:
        result, status = subscription_billing_service.request_action(
            access_token=access_token,
            action="entitlements",
            timeout_seconds=5,
        )
    except subscription_billing_service.SubscriptionBillingError:
        snapshot = {"plan": "Subscription inactive"}
    else:
        if status != 200 or result.get("ok") is not True:
            snapshot = {"plan": "Subscription inactive"}
        else:
            allowed_plans = {
                "Student",
                "Trial",
                "Trial expired",
                "Grandfathered beta",
                "Subscription inactive",
                "Starter",
                "Professional",
                "Business",
                "Enterprise",
            }
            plan = str(result.get("plan") or "")
            if plan not in allowed_plans:
                plan = "Subscription inactive"
            snapshot = {"plan": plan}
            for field in (
                "trial_started_at",
                "trial_ends_at",
                "trial_status",
                "trial_days_remaining",
            ):
                if field in result:
                    snapshot[field] = result[field]

    with _ENTITLEMENT_CACHE_LOCK:
        _ENTITLEMENT_CACHE[cache_key] = (now, dict(snapshot))
        if len(_ENTITLEMENT_CACHE) > 512:
            expired = [
                key for key, (created, _) in _ENTITLEMENT_CACHE.items()
                if now - created >= _ENTITLEMENT_CACHE_TTL_SECONDS
            ]
            for key in expired:
                _ENTITLEMENT_CACHE.pop(key, None)
            while len(_ENTITLEMENT_CACHE) > 512:
                _ENTITLEMENT_CACHE.pop(next(iter(_ENTITLEMENT_CACHE)))
    return snapshot


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
            "Supabase Auth is not configured for this API. "
            f"Missing: {', '.join(missing)}"
        )
    return supabase_url(), supabase_anon_key()


def _client(*, flow_type: str | None = None):
    from supabase import create_client

    url, key = _require_configured()
    if flow_type:
        from supabase import ClientOptions

        return create_client(url, key, options=ClientOptions(flow_type=flow_type))
    return create_client(url, key)


def _token_fingerprint(access_token: str) -> str:
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()


def _workspace_ids_for_owner(user_id: str, email: str) -> tuple[str, str]:
    slug = re.sub(r"[^a-z0-9]+", "-", (email or "owner").lower()).strip("-")[:24] or "owner"
    short = re.sub(r"[^a-f0-9]", "", user_id.lower())[:12] or uuid.uuid4().hex[:12]
    workspace_id = f"{_TEST_WORKSPACE_PREFIX}-{short}"
    workspace_name = "Engineering workspace"
    return workspace_id, workspace_name


def _accept_invitations(
    user_id: str,
    email: str,
    *,
    strict: bool,
    prefer_invite_id: str | None = None,
) -> list[dict[str, Any]]:
    """Accept pending invitations for a verified, authenticated Supabase user.

    Callers have already established ``email_confirmed_at`` and the user id via
    Supabase ``get_user``; the invitation's workspace and role are resolved
    server-side. ``strict`` makes failures fatal - required before any
    personal-workspace provisioning so an unreadable invitation table can never
    be bypassed by silently creating an empty workspace.
    """
    from apps.api import team_service

    try:
        return team_service.accept_pending_invitations(
            user_id=user_id, email=email, prefer_invite_id=prefer_invite_id
        )
    except team_service.TeamError as exc:
        if strict:
            raise AuthError(exc.detail, exc.status_code) from exc
        return []
    except Exception as exc:  # noqa: BLE001
        if strict:
            raise AuthError(
                "We could not check your workspace invitations. Try again shortly.", 503
            ) from exc
        return []


def ensure_owner_membership(
    *,
    user_id: str,
    email: str,
    plan: str = "Trial",
    workspace_name: str | None = None,
    allow_create: bool = False,
    accept_invites: str = "if_missing",
    prefer_invite_id: str | None = None,
) -> dict[str, Any]:
    """Reuse a membership or provision an owner only when creation is explicitly allowed.

    Pending, unexpired invitations for the verified email are accepted *before*
    any personal workspace is created (``accept_invites`` is ``"if_missing"``,
    ``"always"``, or ``"never"``). Membership is authoritative in the migration
    database; see ``apps.api.team_service``.
    """
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
    if accept_invites == "always" or (accept_invites == "if_missing" and not existing):
        accepted = _accept_invitations(
            user_id,
            email,
            strict=not existing,
            prefer_invite_id=prefer_invite_id,
        )
        if accepted:
            existing = store.membership_for_user(user_id)
    if not existing and not allow_create:
        raise AuthError(
            "This account is not provisioned for Cadivor. Contact support for access.",
            403,
        )
    if existing:
        workspace_id = str(existing["workspace_id"])
        existing_name = str(existing.get("workspace_name") or existing["workspace_id"])
        account = store.find_user_by_email(email) or {}
        stored_plan = (
            str(account.get("plan") or plan)
            if str(account.get("id") or "") == user_id
            else plan
        )
        return {
            "user_id": user_id,
            "email": email.strip().lower(),
            "workspace_id": workspace_id,
            "workspace": existing_name,
            "plan": stored_plan,
            **_trial_fields(existing),
        }
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


def _invite_hint(invite_token: str | None) -> str | None:
    if not invite_token:
        return None
    try:
        from apps.api import team_service

        return team_service.invite_id_for_token(invite_token)
    except Exception:  # noqa: BLE001
        return None


def login(
    email: str,
    password: str,
    *,
    requested_workspace_id: str | None = None,
    invite_token: str | None = None,
) -> dict[str, Any]:
    """Sign in via Cadivor Supabase Auth; ignore client workspace_id.

    ``invite_token`` is only a hint for which accepted invitation should become
    the active workspace; acceptance itself is by verified email match.
    """
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
    if not user_email_verified(user):
        raise AuthError("Verify your email address before signing in", 403)
    access_token = str(
        getattr(session, "access_token", None)
        or (session.get("access_token") if isinstance(session, dict) else "")
        or ""
    )
    refresh_token = str(
        getattr(session, "refresh_token", None)
        or (session.get("refresh_token") if isinstance(session, dict) else "")
        or ""
    )
    if not access_token:
        raise AuthError("Invalid credentials")
    user_id, user_email = _user_payload(user)
    membership = ensure_owner_membership(
        user_id=user_id,
        email=user_email,
        workspace_name=user_workspace_name(user),
        allow_create=signup_enabled(),
        accept_invites="always",
        prefer_invite_id=_invite_hint(invite_token),
    )
    entitlements = account_entitlements(access_token)
    expires_in = int(
        getattr(session, "expires_in", None)
        or (session.get("expires_in") if isinstance(session, dict) else 0)
        or 3600
    )
    return {
        "access_token": access_token,
        **({"refresh_token": refresh_token} if refresh_token else {}),
        "token_type": "bearer",
        "expires_in": expires_in,
        "email": membership["email"],
        "user_id": membership["user_id"],
        "workspace": membership["workspace"],
        "workspace_id": membership["workspace_id"],
        "plan": entitlements["plan"],
        "mode": "supabase-jwt",
        "sandbox_only": False,
        "production_auth": True,
        **{
            key: entitlements[key]
            for key in (
                "trial_started_at",
                "trial_ends_at",
                "trial_status",
                "trial_days_remaining",
            )
            if key in entitlements
        },
    }


def logout(access_token: str) -> None:
    _require_configured()
    if not access_token:
        raise AuthError("Missing bearer token")
    get_auth_store().revoke(_token_fingerprint(access_token), exp=0)
    with _ENTITLEMENT_CACHE_LOCK:
        _ENTITLEMENT_CACHE.pop(_token_fingerprint(access_token), None)
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
    if not user_email_verified(user):
        raise AuthError("Verify your email address before using Cadivor", 403)
    membership = ensure_owner_membership(
        user_id=user_id,
        email=email,
        workspace_name=user_workspace_name(user),
        allow_create=signup_enabled(),
    )
    entitlements = account_entitlements(access_token)
    return AuthContext(
        user_id=membership["user_id"],
        email=membership["email"],
        workspace_id=membership["workspace_id"],
        workspace=membership["workspace"],
        plan=entitlements["plan"],
        access_token=access_token,
        jti=fingerprint,
        mode="supabase-jwt",
        trial_started_at=entitlements.get("trial_started_at"),
        trial_ends_at=entitlements.get("trial_ends_at"),
        trial_status=entitlements.get("trial_status"),
        trial_days_remaining=entitlements.get("trial_days_remaining"),
    )


# --------------------------------------------------------------------------
# Invitation account creation, password reset/change, session controls
# --------------------------------------------------------------------------

def _safe_redirect(candidate: str, allowed_origins: list[str]) -> str:
    """Return ``candidate`` only when it is an allowlisted, credential-free URL."""
    value = (candidate or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    if not parsed.hostname or parsed.username or parsed.password:
        return ""
    local = parsed.hostname in {"localhost", "127.0.0.1"}
    if parsed.scheme != "https" and not (local and not is_production_runtime()):
        return ""
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/").lower()
    allowed = {item.strip().rstrip("/").lower() for item in allowed_origins if item.strip()}
    return value if origin in allowed else ""


def web_redirect_url(web_origin: str, path: str, allowed_origins: list[str]) -> str:
    """Allowlisted same-origin URL on the Next web app, or empty when unsafe."""
    configured = (os.environ.get("CADIVOR_INVITE_REDIRECT_URL") or "").strip()
    if path == "/login" and configured:
        safe = _safe_redirect(configured, allowed_origins)
        if safe:
            return safe
    return _safe_redirect(f"{web_origin.rstrip('/')}{path}", allowed_origins)


def signup_for_invitation(
    *,
    token: str,
    password: str,
    redirect_to: str,
    full_name: str | None = None,
    captcha_token: str | None = None,
) -> None:
    """Create a Supabase account for the invited address (verification required).

    Not the public self-serve route: it only works with a valid, unexpired
    invitation token, the email address comes from the stored invitation
    (never the browser), and Supabase email confirmation is still mandatory -
    login and every API request reject unverified users. No workspace or
    membership is created here; acceptance happens after verified sign-in.
    """
    from apps.api import team_service

    _require_configured()
    invite = team_service.valid_invitation_for_token(token)
    if invite is None:
        raise AuthError("This invitation is not valid or has expired.", 404)
    if len(password or "") < 12:
        raise AuthError("Use a password with at least 12 characters", 400)
    captcha_required = (os.environ.get("CADIVOR_SIGNUP_CAPTCHA_REQUIRED") or "").strip() == "1"
    if captcha_required and not (captcha_token or "").strip():
        raise AuthError("Complete the security check and try again", 400)
    metadata: dict[str, Any] = {}
    name = " ".join(str(full_name or "").split())[:120]
    if name:
        metadata["full_name"] = name
    options: dict[str, Any] = {"data": metadata}
    if redirect_to:
        options["email_redirect_to"] = redirect_to
    if captcha_token:
        options["captcha_token"] = captcha_token
    try:
        response = _client().auth.sign_up(
            {"email": str(invite["email"]), "password": password, "options": options}
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
            "Email confirmation must be enabled in Supabase before invitation signup can be used"
        )


def request_password_reset(email: str, *, redirect_to: str) -> None:
    """Ask Supabase Auth to email a recovery link; never reveals account state."""
    _require_configured()
    email_n = (email or "").strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email_n):
        raise AuthError("Enter a valid email address", 400)
    options: dict[str, Any] = {}
    if redirect_to:
        options["redirect_to"] = redirect_to
    try:
        # Implicit flow: the recovery link must work without a code verifier
        # that only a browser session could hold.
        _client(flow_type="implicit").auth.reset_password_for_email(email_n, options)
    except Exception:  # noqa: BLE001
        # Same response for unknown addresses, throttling, or provider errors.
        return


def _auth_user_update(access_token: str, body: dict[str, Any]) -> None:
    """Update the token owner's Supabase Auth user via the Auth REST API."""
    import json as _json
    import urllib.error
    import urllib.request

    url, key = _require_configured()
    req = urllib.request.Request(
        f"{url.rstrip('/')}/auth/v1/user",
        data=_json.dumps(body).encode("utf-8"),
        method="PUT",
        headers={
            "Authorization": f"Bearer {access_token}",
            "apikey": key,
            "Content-Type": "application/json",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()  # noqa: S310 - Auth host from env
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = _json.loads(exc.read().decode("utf-8") or "{}")
            detail = str(
                payload.get("msg") or payload.get("message") or payload.get("error_description") or ""
            )
        except Exception:  # noqa: BLE001
            detail = ""
        status = 400 if exc.code in {400, 401, 403, 422} else 503
        raise AuthError(
            detail or "Supabase could not update the password. Try again.", status
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise AuthError("Supabase could not update the password. Try again.", 503) from exc


def _validate_new_password(password: str) -> None:
    if len(password or "") < 12:
        raise AuthError("Use a password with at least 12 characters", 400)
    if len(password) > 256:
        raise AuthError("Password is too long", 400)


def complete_password_reset(recovery_access_token: str, new_password: str) -> None:
    """Finish a recovery flow using the short-lived token from the reset email."""
    _require_configured()
    _validate_new_password(new_password)
    if not recovery_access_token:
        raise AuthError("This reset link is invalid or has expired.", 400)
    try:
        response = _client().auth.get_user(recovery_access_token)
    except Exception as exc:  # noqa: BLE001
        raise AuthError("This reset link is invalid or has expired.", 400) from exc
    user = getattr(response, "user", None) or (
        response.get("user") if isinstance(response, dict) else None
    )
    if user is None:
        raise AuthError("This reset link is invalid or has expired.", 400)
    _auth_user_update(recovery_access_token, {"password": new_password})


def change_password(
    access_token: str, email: str, current_password: str, new_password: str
) -> None:
    """Change the signed-in user's password after re-verifying the current one."""
    _require_configured()
    _validate_new_password(new_password)
    if not current_password:
        raise AuthError("Enter your current password", 400)
    if new_password == current_password:
        raise AuthError("Choose a password that is different from the current one", 400)
    try:
        verified = _client().auth.sign_in_with_password(
            {"email": (email or "").strip().lower(), "password": current_password}
        )
    except Exception as exc:  # noqa: BLE001
        raise AuthError("Your current password is incorrect", 400) from exc
    verified_user = getattr(verified, "user", None) or (
        verified.get("user") if isinstance(verified, dict) else None
    )
    if verified_user is None:
        raise AuthError("Your current password is incorrect", 400)
    _auth_user_update(access_token, {"password": new_password})


def revoke_other_sessions(access_token: str) -> None:
    """Sign the user out of every other device (keeps the current session)."""
    import urllib.request

    url, key = _require_configured()
    req = urllib.request.Request(
        f"{url.rstrip('/')}/auth/v1/logout?scope=others",
        data=b"{}",
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "apikey": key,
            "Content-Type": "application/json",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()  # noqa: S310 - Auth host from env
    except Exception as exc:  # noqa: BLE001
        raise AuthError("Other sessions could not be signed out. Try again.", 503) from exc

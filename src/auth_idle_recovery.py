"""Idle-session recovery for authenticated workspace profile initialization.

After inactivity the Streamlit session can retain a user object while the JWT
access token is expired. Profile SELECTs then return empty under RLS and the
legacy path mistook that for a missing profile, showing a generic workspace
error. This module refreshes once before treating profile load as failed.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Literal, Mapping

logger = logging.getLogger(__name__)

SESSION_EXPIRED_NOTICE_KEY = "cadivor_session_expired_notice"
SESSION_EXPIRED_NOTICE = (
    "Your Cadivor session expired after inactivity. Sign in again to continue."
)
# Refresh slightly before hard expiry so workspace reads do not race the clock.
ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 90

RefreshOutcome = Literal["fresh", "refreshed", "invalid", "unavailable"]


def access_token_is_fresh(
    access_token: str,
    *,
    now_ts: float | None = None,
    skew_seconds: int = ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
) -> bool:
    """Return True when the access JWT looks usable for the next workspace read."""
    from src.auth_cookies import _decode_jwt_claims

    claims = _decode_jwt_claims(str(access_token or ""))
    if not claims:
        return False
    try:
        exp = float(claims.get("exp"))
    except (TypeError, ValueError):
        return False
    now = time.time() if now_ts is None else float(now_ts)
    return exp > (now + max(int(skew_seconds), 0))


def is_auth_rejection_error(error: BaseException | str | None) -> bool:
    """True when an API/auth failure indicates expired or rejected credentials."""
    text = str(error or "").casefold()
    if not text:
        return False
    markers = (
        "jwt expired",
        "jwtinvalid",
        "invalid jwt",
        "invalid_token",
        "token is expired",
        "token has expired",
        "not authenticated",
        "authapierror",
        "401",
        "403",
        "unauthorized",
        "forbidden",
        "session_not_found",
        "refresh_token",
        "invalid refresh",
    )
    return any(marker in text for marker in markers)


def refresh_authenticated_session(
    supabase: Any,
    *,
    access_token: str,
    refresh_token: str,
    force: bool = False,
) -> tuple[RefreshOutcome, Any | None, str, str]:
    """Validate or refresh tokens without writing Streamlit state.

    Returns ``(outcome, user, access_token, refresh_token)``.
    """
    access = str(access_token or "").strip()
    refresh = str(refresh_token or "").strip()
    if not access or not refresh:
        return "invalid", None, "", ""

    from src.auth_state import _SUPABASE_AUTH_LOCK, _fetch_validated_auth

    if not force and access_token_is_fresh(access):
        try:
            validated = _fetch_validated_auth(supabase, access, refresh)
        except Exception as exc:
            if not is_auth_rejection_error(exc):
                logger.info(
                    "idle_session_validate_unavailable error=%s",
                    type(exc).__name__,
                )
                return "unavailable", None, access, refresh
            force = True
            validated = None
        if validated is not None:
            return (
                "fresh",
                validated.user,
                validated.access_token,
                validated.refresh_token,
            )
        force = True

    try:
        with _SUPABASE_AUTH_LOCK:
            # Prefer explicit refresh for idle recovery; set_session alone may not
            # rotate an already-expired access token on every gotrue version.
            try:
                response = supabase.auth.refresh_session(refresh)
            except TypeError:
                response = supabase.auth.refresh_session()
            session = getattr(response, "session", None)
            user = getattr(response, "user", None) or getattr(
                getattr(response, "session", None), "user", None
            )
            if session is None or not getattr(session, "access_token", None):
                # Fallback: re-bind and re-read user.
                validated = _fetch_validated_auth(supabase, access, refresh)
                if validated is None:
                    return "invalid", None, "", ""
                return (
                    "refreshed",
                    validated.user,
                    validated.access_token,
                    validated.refresh_token,
                )
            if user is None:
                user_response = supabase.auth.get_user()
                user = getattr(user_response, "user", None)
            if user is None:
                return "invalid", None, "", ""
            return (
                "refreshed",
                user,
                str(session.access_token),
                str(getattr(session, "refresh_token", None) or refresh),
            )
    except Exception as exc:
        if is_auth_rejection_error(exc):
            logger.info("idle_session_refresh_invalid error=%s", type(exc).__name__)
            return "invalid", None, "", ""
        logger.info("idle_session_refresh_unavailable error=%s", type(exc).__name__)
        return "unavailable", None, access, refresh


def commit_refreshed_workspace_session(
    session_state: Mapping[str, Any] | Any,
    *,
    user: Any,
    access_token: str,
    refresh_token: str,
    cookie_manager: Any = None,
    supabase: Any = None,
) -> None:
    """Persist refreshed credentials into Streamlit state and the Supabase client."""
    from src.auth_state import _SUPABASE_AUTH_LOCK, _commit_authenticated_session

    _commit_authenticated_session(user, access_token, refresh_token)
    if supabase is not None:
        try:
            with _SUPABASE_AUTH_LOCK:
                supabase.auth.set_session(access_token, refresh_token)
        except Exception:
            logger.info(
                "idle_session_set_session_failed error=%s",
                "set_session",
            )
    try:
        from src.auth_cookies import get_auth_cookie_manager, persist_session_auth_cookie

        persist_session_auth_cookie(cookie_manager or get_auth_cookie_manager(mount=True))
    except Exception:
        pass


def preserve_requested_page_for_reauth(session_state: Any) -> None:
    """Keep the current authenticated page so login can resume navigation."""
    page = ""
    try:
        page = str(session_state.get("app_mode") or session_state.get("cadivor_route") or "").strip()
    except Exception:
        page = ""
    if not page:
        try:
            import streamlit as st

            raw = st.query_params.get("page", "")
            if isinstance(raw, (list, tuple)):
                raw = raw[0] if raw else ""
            page = str(raw or "").strip()
        except Exception:
            page = ""
    if page and page not in {"login", "signup", "public"}:
        session_state["cadivor_requested_page"] = page


def enter_session_expired_recovery(
    *,
    reason: str,
    cookie_manager: Any = None,
) -> None:
    """Clear authenticated runtime and route to branded sign-in recovery."""
    import streamlit as st

    from src.auth_state import APP_LOGIN, mark_signed_out

    try:
        from src.auth_bootstrap import clear_login_handoff

        clear_login_handoff()
    except Exception:
        st.session_state.pop("cadivor_login_handoff_active", None)
        st.session_state.pop("cadivor_login_handoff_stage", None)
        st.session_state.pop("cadivor_login_handoff_started_at", None)

    preserve_requested_page_for_reauth(st.session_state)
    mark_signed_out(reason=f"idle_session:{reason}")
    st.session_state["cadivor_root_state"] = APP_LOGIN
    st.session_state[SESSION_EXPIRED_NOTICE_KEY] = SESSION_EXPIRED_NOTICE
    try:
        from src.auth_cookies import clear_auth_cookie, get_auth_cookie_manager

        clear_auth_cookie(cookie_manager or get_auth_cookie_manager(mount=False))
    except Exception:
        pass
    try:
        from src.auth_state import log_auth_diagnostic

        log_auth_diagnostic("idle_session_expired", reason=reason)
    except Exception:
        pass
    st.rerun()


def render_retryable_profile_error(*, message: str) -> None:
    """Show a transient workspace-profile error with an in-page retry action."""
    import streamlit as st

    from src.ui.core_premium_ui import stop_authenticated_page

    # Retire the Login handoff shell before painting retry UI so the opaque
    # "Signing you in…" overlay cannot mask the actionable error forever.
    try:
        from src.auth_bootstrap import clear_login_handoff

        clear_login_handoff()
    except Exception:
        st.session_state.pop("cadivor_login_handoff_active", None)
        st.session_state.pop("cadivor_login_handoff_stage", None)
        st.session_state.pop("cadivor_login_handoff_started_at", None)

    st.error(message)
    st.caption("Your signed-in session was kept. Retry when the connection is available.")
    if st.button("Retry workspace load", type="primary", key="cadivor_retry_workspace_profile"):
        st.rerun()
    stop_authenticated_page()


def load_workspace_profile(
    *,
    supabase: Any,
    session_state: Any,
    cookie_manager: Any = None,
    read_profile,
    ensure_profile,
    recent_profile,
    remember_profile,
    transport_error_type: type[BaseException],
) -> dict[str, Any]:
    """Load the users profile with one idle-session refresh attempt.

    Side-effect helpers (`enter_session_expired_recovery`, retry UI) stop the
    Streamlit script when recovery is required.
    """
    from src.services.user_provisioning import UserProvisioningError

    user = session_state.get("user")
    if user is None:
        enter_session_expired_recovery(reason="missing_user", cookie_manager=cookie_manager)
        raise RuntimeError("session_expired")

    user_id = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
    access_token = str(session_state.get("access_token") or "").strip()
    refresh_token = str(session_state.get("refresh_token") or "").strip()
    session_refreshed = False

    outcome, refreshed_user, new_access, new_refresh = refresh_authenticated_session(
        supabase,
        access_token=access_token,
        refresh_token=refresh_token,
        force=False,
    )
    if outcome == "invalid":
        enter_session_expired_recovery(reason="token_invalid", cookie_manager=cookie_manager)
        raise RuntimeError("session_expired")
    if outcome == "unavailable" and not access_token_is_fresh(
        str(session_state.get("access_token") or new_access or "")
    ):
        cached_profile = recent_profile(session_state, user_id)
        if cached_profile:
            return cached_profile
        render_retryable_profile_error(
            message=(
                "Cadivor could not refresh your session right now. "
                "Please wait a moment and retry."
            )
        )
        raise RuntimeError("retryable_profile_error")
    if outcome == "refreshed" and refreshed_user is not None:
        commit_refreshed_workspace_session(
            session_state,
            user=refreshed_user,
            access_token=new_access,
            refresh_token=new_refresh,
            cookie_manager=cookie_manager,
            supabase=supabase,
        )
        user = refreshed_user
        user_id = getattr(user, "id", None) or user_id
        session_refreshed = True

    response = None
    read_error: BaseException | None = None
    try:
        response = read_profile(user_id)
    except transport_error_type as exc:
        read_error = exc
    except Exception as exc:
        if is_auth_rejection_error(exc):
            outcome, refreshed_user, new_access, new_refresh = refresh_authenticated_session(
                supabase,
                access_token=str(session_state.get("access_token") or ""),
                refresh_token=str(session_state.get("refresh_token") or ""),
                force=True,
            )
            if outcome == "invalid":
                enter_session_expired_recovery(
                    reason="auth_rejected",
                    cookie_manager=cookie_manager,
                )
                raise RuntimeError("session_expired")
            if outcome in {"refreshed", "fresh"} and refreshed_user is not None:
                commit_refreshed_workspace_session(
                    session_state,
                    user=refreshed_user,
                    access_token=new_access,
                    refresh_token=new_refresh,
                    cookie_manager=cookie_manager,
                    supabase=supabase,
                )
                user = refreshed_user
                user_id = getattr(user, "id", None) or user_id
                session_refreshed = True
                try:
                    response = read_profile(user_id)
                    read_error = None
                except Exception as retry_exc:
                    read_error = retry_exc
            else:
                read_error = exc
        else:
            read_error = exc

    if read_error is not None and response is None:
        if isinstance(read_error, transport_error_type) or not is_auth_rejection_error(read_error):
            cached_profile = recent_profile(session_state, user_id)
            if cached_profile:
                return cached_profile
            render_retryable_profile_error(
                message=(
                    "Cadivor could not reach the database right now. "
                    "Please wait a moment and retry."
                )
            )
            raise RuntimeError("retryable_profile_error")
        enter_session_expired_recovery(reason="profile_auth_error", cookie_manager=cookie_manager)
        raise RuntimeError("session_expired")

    if response is not None and getattr(response, "data", None):
        row = response.data[0]
        return remember_profile(session_state, row) or row

    if response is not None and not getattr(response, "data", None) and not session_refreshed:
        outcome, refreshed_user, new_access, new_refresh = refresh_authenticated_session(
            supabase,
            access_token=str(session_state.get("access_token") or ""),
            refresh_token=str(session_state.get("refresh_token") or ""),
            force=True,
        )
        if outcome == "invalid":
            enter_session_expired_recovery(
                reason="empty_profile_invalid_session",
                cookie_manager=cookie_manager,
            )
            raise RuntimeError("session_expired")
        if outcome == "unavailable":
            cached_profile = recent_profile(session_state, user_id)
            if cached_profile:
                return cached_profile
            render_retryable_profile_error(
                message=(
                    "Cadivor could not verify your session right now. "
                    "Please wait a moment and retry."
                )
            )
            raise RuntimeError("retryable_profile_error")
        if outcome in {"refreshed", "fresh"} and refreshed_user is not None:
            commit_refreshed_workspace_session(
                session_state,
                user=refreshed_user,
                access_token=new_access,
                refresh_token=new_refresh,
                cookie_manager=cookie_manager,
                supabase=supabase,
            )
            user = refreshed_user
            user_id = getattr(user, "id", None) or user_id
            try:
                response = read_profile(user_id)
            except transport_error_type:
                cached_profile = recent_profile(session_state, user_id)
                if cached_profile:
                    return cached_profile
                render_retryable_profile_error(
                    message=(
                        "Cadivor could not reach the database right now. "
                        "Please wait a moment and retry."
                    )
                )
                raise RuntimeError("retryable_profile_error")
            except Exception as retry_exc:
                if is_auth_rejection_error(retry_exc):
                    enter_session_expired_recovery(
                        reason="empty_profile_retry_auth",
                        cookie_manager=cookie_manager,
                    )
                    raise RuntimeError("session_expired")
                cached_profile = recent_profile(session_state, user_id)
                if cached_profile:
                    return cached_profile
                render_retryable_profile_error(
                    message=(
                        "Cadivor could not load your workspace profile right now. "
                        "Please wait a moment and retry."
                    )
                )
                raise RuntimeError("retryable_profile_error")
            if response is not None and getattr(response, "data", None):
                row = response.data[0]
                return remember_profile(session_state, row) or row

    cached_profile = recent_profile(session_state, user_id)
    if cached_profile:
        return cached_profile

    try:
        profile, _created = ensure_profile(supabase, user)
        return remember_profile(session_state, profile) or profile
    except UserProvisioningError as exc:
        if is_auth_rejection_error(exc) or is_auth_rejection_error(getattr(exc, "__cause__", None)):
            enter_session_expired_recovery(
                reason="provisioning_auth_rejected",
                cookie_manager=cookie_manager,
            )
            raise RuntimeError("session_expired")
        render_retryable_profile_error(
            message=(
                "Cadivor could not load your workspace profile right now. "
                "Please wait a moment and retry."
            )
        )
        raise RuntimeError("retryable_profile_error")

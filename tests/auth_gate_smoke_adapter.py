"""Test-only auth-gate smoke adapter (never imported by production runtime).

Installs monkeypatches so the browser smoke harness can exercise
boot → login → authenticating → ready without Supabase or env-based mock switches.
"""
from __future__ import annotations

import types
import uuid
from typing import Any

SMOKE_EMAIL = "auth-smoke@cadivor.test"
SMOKE_PASSWORD = "cadivor-auth-smoke"
SMOKE_ACCESS_TOKEN = "smoke_access_token"
SMOKE_REFRESH_TOKEN = "smoke_refresh_token"
SMOKE_COOKIE = "cadivor_auth_gate_smoke=1"
SMOKE_SESSION_KEY = "cadivor_auth_gate_smoke_session"


def _smoke_cookie_present() -> bool:
    import streamlit as st

    if st.session_state.get(SMOKE_SESSION_KEY):
        return True
    try:
        headers = getattr(getattr(st, "context", None), "headers", None) or {}
        cookie_header = str(headers.get("Cookie") or headers.get("cookie") or "")
        return SMOKE_COOKIE.split("=", 1)[0] + "=1" in cookie_header
    except Exception:
        return False


def _persist_smoke_cookie() -> None:
    import streamlit as st
    import streamlit.components.v1 as components

    st.session_state[SMOKE_SESSION_KEY] = True
    try:
        components.html(
            f"""
            <script>
            document.cookie = "{SMOKE_COOKIE}; path=/; SameSite=Lax";
            </script>
            """,
            height=0,
            width=0,
        )
    except Exception:
        pass


def _activate_smoke_session(*, email: str = SMOKE_EMAIL) -> None:
    import streamlit as st
    from src.auth_bootstrap import clear_login_handoff
    from src.auth_gate import set_auth_gate_state
    from src.auth_state import APP_AUTHENTICATED, AUTH_AUTHENTICATED

    st.session_state["access_token"] = SMOKE_ACCESS_TOKEN
    st.session_state["refresh_token"] = SMOKE_REFRESH_TOKEN
    st.session_state["user"] = types.SimpleNamespace(id="auth-smoke-user", email=email)
    st.session_state["cadivor_auth_status"] = AUTH_AUTHENTICATED
    st.session_state["cadivor_root_state"] = APP_AUTHENTICATED
    st.session_state.pop("cadivor_force_signed_out", None)
    # Never arm login handoff after a valid session — that remounts the centered
    # authenticating card over the durable authenticated shell.
    clear_login_handoff()
    set_auth_gate_state("ready", reason="smoke_login_success")
    _persist_smoke_cookie()


def install_smoke_auth_patches() -> None:
    """Monkeypatch production auth entry points for the smoke Streamlit app only."""
    import streamlit as st

    import src.auth as auth_mod
    import src.auth_atomic_login as atomic_mod
    import src.auth_gate as gate_mod
    import src.auth_state as state_mod
    from src.auth_bootstrap import fail_login_handoff

    def smoke_execute_password_login(
        supabase: Any, cookie_manager: Any, email: str, password: str
    ) -> bool:
        del supabase, cookie_manager
        email_n = str(email or "").strip()
        if email_n.casefold() == SMOKE_EMAIL and str(password or "") == SMOKE_PASSWORD:
            _activate_smoke_session(email=email_n)
            return True
        fail_login_handoff(
            message="Email or password is incorrect. Please try again.",
            email=email_n,
        )
        return False

    def smoke_render_atomic_login(
        *,
        key: str = "cadivor_atomic_login",
        disabled: bool = False,
        submit_label: str = "Login",
        prefill_email: str = "",
        error_message: str = "",
        error_epoch: int = 0,
    ) -> dict[str, str] | None:
        del key, error_epoch
        if error_message:
            st.error(str(error_message))
        draft = str(prefill_email or "").strip()
        email_key = "cadivor_auth_gate_smoke_email"
        password_key = "cadivor_auth_gate_smoke_password"
        if draft and not st.session_state.get(email_key):
            st.session_state[email_key] = draft
        with st.form("cadivor_auth_gate_smoke_login", clear_on_submit=False, border=False):
            email = st.text_input(
                "Email",
                placeholder="you@company.com",
                key=email_key,
                autocomplete="email",
            )
            password = st.text_input(
                "Password",
                type="password",
                placeholder="Enter your password",
                key=password_key,
                autocomplete="current-password",
            )
            submitted = st.form_submit_button(
                submit_label or "Login",
                type="primary",
                use_container_width=True,
                disabled=bool(disabled),
            )
        if submitted and str(email or "").strip() and str(password or ""):
            return {
                "request_id": str(uuid.uuid4()),
                "email": str(email).strip(),
                "password": str(password),
            }
        return None

    _orig_resolve = state_mod.resolve_auth_state

    def smoke_resolve_auth_state(supabase: Any, cookie_manager: Any) -> str:
        access = str(st.session_state.get("access_token") or "")
        refresh = str(st.session_state.get("refresh_token") or "")
        if (
            (access == SMOKE_ACCESS_TOKEN and refresh == SMOKE_REFRESH_TOKEN)
            or _smoke_cookie_present()
        ):
            _activate_smoke_session(
                email=str(getattr(st.session_state.get("user"), "email", None) or SMOKE_EMAIL)
            )
            return state_mod.AUTH_AUTHENTICATED
        return _orig_resolve(supabase, cookie_manager)

    _orig_initial = gate_mod.resolve_initial_gate_state

    def smoke_resolve_initial_gate_state(
        *,
        force_signed_out: bool = False,
        handoff_active: bool = False,
        has_tokens: bool = False,
        pending_credentials: bool = False,
        already_authenticated: bool = False,
    ):
        if already_authenticated and not force_signed_out and not pending_credentials:
            return "ready"
        if _smoke_cookie_present() or (
            str(st.session_state.get("access_token") or "") == SMOKE_ACCESS_TOKEN
            and str(st.session_state.get("refresh_token") or "") == SMOKE_REFRESH_TOKEN
        ):
            if already_authenticated:
                return "ready"
            return "boot"
        if (
            not has_tokens
            and not pending_credentials
            and not handoff_active
            and not force_signed_out
        ):
            return "login"
        return _orig_initial(
            force_signed_out=force_signed_out,
            handoff_active=handoff_active,
            has_tokens=has_tokens,
            pending_credentials=pending_credentials,
            already_authenticated=already_authenticated,
        )

    auth_mod.execute_password_login = smoke_execute_password_login
    atomic_mod.render_atomic_login = smoke_render_atomic_login
    auth_mod.render_atomic_login = smoke_render_atomic_login
    state_mod.resolve_auth_state = smoke_resolve_auth_state
    gate_mod.resolve_initial_gate_state = smoke_resolve_initial_gate_state

    # Module-level imports in auth_bootstrap bind resolve_auth_state at import time.
    import src.auth_bootstrap as boot_mod

    boot_mod.resolve_auth_state = smoke_resolve_auth_state


def _smoke_user_row(*, email: str = SMOKE_EMAIL) -> dict[str, Any]:
    return {
        "id": "auth-smoke-user",
        "email": email,
        "full_name": "Auth Smoke",
        "company": "Cadivor Smoke",
        "company_name": "Cadivor Smoke",
        "role": "user",
        "role_title": "Engineer",
        "plan": "Starter",
        "monthly_upload_count": 0,
        "profile_completed": True,
        "workspace_completed": True,
        "first_bom_completed": True,
        "first_alternative_completed": True,
        "first_report_completed": True,
        "onboarding_completed": True,
    }


class _SmokeQuery:
    def __init__(self, data: list | None = None, count: int = 0) -> None:
        self._data = list(data or [])
        self._count = count

    def select(self, *args: Any, **kwargs: Any) -> "_SmokeQuery":
        del args, kwargs
        return self

    def eq(self, *args: Any, **kwargs: Any) -> "_SmokeQuery":
        del args, kwargs
        return self

    def neq(self, *args: Any, **kwargs: Any) -> "_SmokeQuery":
        del args, kwargs
        return self

    def in_(self, *args: Any, **kwargs: Any) -> "_SmokeQuery":
        del args, kwargs
        return self

    def order(self, *args: Any, **kwargs: Any) -> "_SmokeQuery":
        del args, kwargs
        return self

    def limit(self, *args: Any, **kwargs: Any) -> "_SmokeQuery":
        del args, kwargs
        return self

    def range(self, *args: Any, **kwargs: Any) -> "_SmokeQuery":
        del args, kwargs
        return self

    def update(self, *args: Any, **kwargs: Any) -> "_SmokeQuery":
        del args, kwargs
        return self

    def insert(self, *args: Any, **kwargs: Any) -> "_SmokeQuery":
        del args, kwargs
        return self

    def upsert(self, *args: Any, **kwargs: Any) -> "_SmokeQuery":
        del args, kwargs
        return self

    def delete(self, *args: Any, **kwargs: Any) -> "_SmokeQuery":
        del args, kwargs
        return self

    def execute(self) -> Any:
        return types.SimpleNamespace(data=list(self._data), count=self._count)


class _SmokeSupabase:
    def table(self, name: str) -> _SmokeQuery:
        if name == "users":
            return _SmokeQuery(data=[_smoke_user_row()])
        return _SmokeQuery()

    def rpc(self, *args: Any, **kwargs: Any) -> _SmokeQuery:
        del args, kwargs
        return _SmokeQuery(data=[{"account_status": "active", "maintenance_mode": False}])

    @property
    def auth(self) -> Any:
        user = types.SimpleNamespace(id="auth-smoke-user", email=SMOKE_EMAIL)

        class _Auth:
            def get_user(self, *args: Any, **kwargs: Any) -> Any:
                del args, kwargs
                return types.SimpleNamespace(user=user)

            def get_session(self, *args: Any, **kwargs: Any) -> Any:
                del args, kwargs
                return types.SimpleNamespace(
                    session=types.SimpleNamespace(
                        access_token=SMOKE_ACCESS_TOKEN,
                        refresh_token=SMOKE_REFRESH_TOKEN,
                        user=user,
                    )
                )

            def set_session(self, *args: Any, **kwargs: Any) -> Any:
                del args, kwargs
                return types.SimpleNamespace(session=None, user=user)

            def sign_out(self, *args: Any, **kwargs: Any) -> None:
                del args, kwargs

        return _Auth()


def install_production_path_smoke_patches() -> None:
    """Session-boundary + IO doubles for real streamlit_app / authenticated_runtime.

    Does not replace the ready surface, routing, unified_shell, or page modules.
    """
    install_smoke_auth_patches()

    import src.auth_bootstrap as boot_mod
    import src.authenticated_runtime as runtime_mod

    smoke_sb = _SmokeSupabase()

    def smoke_get_supabase_client(*args: Any, **kwargs: Any) -> _SmokeSupabase:
        del args, kwargs
        return smoke_sb

    def smoke_load_user_data() -> dict[str, Any]:
        import time

        import streamlit as st

        # Hold so browser smoke can capture the in-shell main placeholder after
        # foundation chrome mounts and before Dashboard content paints.
        time.sleep(1.25)
        email = str(
            getattr(st.session_state.get("user"), "email", None) or SMOKE_EMAIL
        ).strip()
        return _smoke_user_row(email=email)

    boot_mod.get_supabase_client = smoke_get_supabase_client
    runtime_mod.get_supabase_client = smoke_get_supabase_client
    runtime_mod.load_user_data = smoke_load_user_data
    runtime_mod.supabase = smoke_sb

    def smoke_ensure_personal_workspace(*args: Any, **kwargs: Any):
        del args, kwargs
        return (
            {
                "id": "smoke-workspace",
                "name": "Cadivor Smoke Workspace",
                "plan": "Starter",
            },
            None,
        )

    def smoke_list_user_workspaces(*args: Any, **kwargs: Any):
        del args, kwargs
        return (
            [
                {
                    "id": "smoke-workspace",
                    "name": "Cadivor Smoke Workspace",
                    "plan": "Starter",
                }
            ],
            None,
        )

    runtime_mod.ensure_personal_workspace = smoke_ensure_personal_workspace
    runtime_mod.list_user_workspaces = smoke_list_user_workspaces
    try:
        import src.workspace_service as workspace_mod

        workspace_mod.ensure_personal_workspace = smoke_ensure_personal_workspace
        workspace_mod.list_user_workspaces = smoke_list_user_workspaces
    except Exception:
        pass

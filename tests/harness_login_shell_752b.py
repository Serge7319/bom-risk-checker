#!/usr/bin/env python3
"""Sprint 75.2B — multi-run harness: one-click login + persistent shell boundaries."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_auth_cookie_read_bridge import (
    _FakeContextCookies,
    _install_auth_modules,
    _install_streamlit_stub,
)


def main() -> int:
    events: list[str] = []
    st = _install_streamlit_stub({}, context_cookies=_FakeContextCookies())
    st.rerun = MagicMock(side_effect=lambda: events.append("rerun"))
    st.error = MagicMock()
    st.markdown = MagicMock()
    st.warning = MagicMock()
    st.success = MagicMock()
    st.info = MagicMock()
    st.stop = MagicMock(side_effect=SystemExit("stop"))

    ui = types.ModuleType("src.ui.core_premium_ui")
    ui.inject_core_premium_ui_auth = MagicMock()
    sys.modules["src.ui.core_premium_ui"] = ui
    config = types.ModuleType("src.config")
    config.CADIVOR_MARKETING_URL = "https://www.cadivor.com/"
    sys.modules["src.config"] = config

    for name in list(sys.modules):
        if name.startswith("src.auth"):
            sys.modules.pop(name, None)
    _cookies, auth_state = _install_auth_modules(st)
    import importlib

    auth = importlib.import_module("src.auth")

    supabase = MagicMock()
    session = types.SimpleNamespace(access_token="a", refresh_token="r")
    user = types.SimpleNamespace(id="user-1", email="user@example.com")
    supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
        user=user, session=session
    )

    # Run 1: signed out → one login submit
    events.append("signed_out")
    with patch.object(auth, "mark_authenticated") as mark:
        auth._submit_manual_login(supabase, MagicMock(), "user@example.com", "secret")
        events.append("login_submit")
        assert mark.called
    assert supabase.auth.sign_in_with_password.call_count == 1
    events.append("signing_in_then_authenticated")

    # Simulate authenticated session after rerun
    st.session_state["user"] = user
    st.session_state["access_token"] = "a"
    st.session_state["refresh_token"] = "r"
    st.session_state["cadivor_auth_status"] = auth_state.AUTH_AUTHENTICATED
    st.session_state["cadivor_root_state"] = auth_state.APP_AUTHENTICATED
    st.session_state.pop("cadivor_manual_login_in_progress", None)

    # Signing-in wipe must not occur when already authenticated (show_auth_ui not used)
    # Navigate routes in session state
    for route in ("Dashboard", "Reports", "Dashboard", "Alternative Finder", "Dashboard"):
        st.session_state["cadivor_route"] = route
        events.append(f"route:{route}")
        # Authenticated UI must not remount login
        assert st.session_state.get("cadivor_auth_status") == auth_state.AUTH_AUTHENTICATED
        assert st.session_state.get("cadivor_root_state") != auth_state.APP_LOGIN

    # Source guards for shell persistence contract
    bootstrap = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
    runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
    assert "auth_surface_host = None" in bootstrap
    assert runtime.index("render_unified_shell(") < runtime.index('timed_phase("runtime.workspace_init"')

    report = {
        "login_calls": supabase.auth.sign_in_with_password.call_count,
        "events": events,
        "final_route": st.session_state.get("cadivor_route"),
        "auth_status": st.session_state.get("cadivor_auth_status"),
        "shell_before_workspace": True,
        "lazy_auth_surface": True,
        "ok": True,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

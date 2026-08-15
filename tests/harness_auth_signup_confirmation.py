#!/usr/bin/env python3
"""Sprint 74.2C — signup confirmation lifecycle harness."""
from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_auth_cookie_read_bridge import _install_streamlit_stub  # noqa: E402


def main() -> int:
    st = _install_streamlit_stub({})
    st.rerun = MagicMock()
    for name in list(sys.modules):
        if name.startswith("src.auth"):
            sys.modules.pop(name, None)

    confirm = importlib.import_module("src.auth_signup_confirmation")
    state = importlib.import_module("src.auth_state")
    report: dict = {}

    # Run 1: valid callback → session-ready success + cleaned query.
    st.query_params = {
        "cadivor_signup_confirm": "1",
        "token_hash": "signup-hash",
        "type": "email",
    }
    supabase = MagicMock()
    session = types.SimpleNamespace(
        access_token="access-token",
        refresh_token="refresh-token",
        user=types.SimpleNamespace(id="user-1", email="new@cadivor.com"),
    )
    supabase.auth.verify_otp.return_value = types.SimpleNamespace(
        session=session, user=session.user
    )
    confirm.apply_signup_confirmation_from_query(supabase)
    report["run1_verified_once"] = supabase.auth.verify_otp.call_count == 1
    report["run1_query_cleaned"] = "token_hash" not in st.query_params and (
        "cadivor_signup_confirm" not in st.query_params
    )
    report["run1_success_state"] = (
        st.session_state.get("cadivor_root_state") == state.APP_SIGNUP_CONFIRMATION_SUCCESS
    )
    report["run1_session_ready"] = confirm.signup_confirmation_session_ready()

    # Run 2: rerun with empty query does not reverify; surface survives.
    supabase.auth.verify_otp.reset_mock()
    st.query_params = {}
    confirm.apply_signup_confirmation_from_query(supabase)
    report["run2_no_reverify"] = supabase.auth.verify_otp.call_count == 0
    report["run2_surface_survives"] = (
        st.session_state.get("cadivor_root_state") == state.APP_SIGNUP_CONFIRMATION_SUCCESS
    )

    # Run 3: Continue to workspace marks authenticated.
    with patch.object(state, "mark_authenticated") as mark:
        # Re-bind mark_authenticated used inside continue helper.
        with patch("src.auth_state.mark_authenticated", mark):
            confirm.continue_signup_confirmation_to_workspace(None)
    report["run3_continue_workspace_called_mark"] = mark.called
    report["run3_rerun"] = st.rerun.called

    # Run 4: replayed email link (consumed) → invalid, no verify.
    st.session_state.clear()
    st.rerun.reset_mock()
    st.session_state[confirm._EXCHANGE_CONSUMED_KEY] = True
    st.query_params = {
        "cadivor_signup_confirm": "1",
        "token_hash": "signup-hash",
        "type": "email",
    }
    supabase2 = MagicMock()
    confirm.apply_signup_confirmation_from_query(supabase2)
    report["run4_replay_invalid"] = (
        st.session_state.get("cadivor_root_state") == state.APP_SIGNUP_CONFIRMATION_INVALID
    )
    report["run4_no_verify"] = supabase2.auth.verify_otp.call_count == 0
    report["run4_query_cleaned"] = "token_hash" not in st.query_params

    # Run 5: login-required success path.
    st.session_state.clear()
    st.query_params = {
        "cadivor_signup_confirm": "1",
        "token_hash": "signup-hash",
        "type": "email",
    }
    supabase3 = MagicMock()
    supabase3.auth.verify_otp.return_value = types.SimpleNamespace(
        session=None, user=types.SimpleNamespace(id="u2")
    )
    confirm.apply_signup_confirmation_from_query(supabase3)
    report["run5_login_required"] = (
        confirm.signup_confirmation_result_kind() == confirm.RESULT_LOGIN_REQUIRED
    )
    confirm.continue_signup_confirmation_to_login()
    report["run5_to_login"] = st.session_state.get("cadivor_root_state") == state.APP_LOGIN

    # Run 6: recovery collision stays out of signup confirmation when only recovery.
    st.session_state.clear()
    st.query_params = {
        "cadivor_recovery": "1",
        "token_hash": "recovery-hash",
        "type": "recovery",
    }
    supabase4 = MagicMock()
    confirm.apply_signup_confirmation_from_query(supabase4)
    report["run6_recovery_ignored_by_signup"] = (
        supabase4.auth.verify_otp.call_count == 0
        and not confirm.signup_confirmation_surface_active()
    )

    ok = all(bool(v) for v in report.values())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

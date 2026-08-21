#!/usr/bin/env python3
"""Sprint 74.1.1 — two-run password recovery Streamlit lifecycle harness."""
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

from tests.test_auth_cookie_read_bridge import _install_streamlit_stub


def run_harness() -> dict:
    report: dict = {}
    st = _install_streamlit_stub({})
    st.rerun = MagicMock()
    st.stop = MagicMock()
    st.cache_resource = lambda **kwargs: (lambda fn: fn)

    sys.modules.pop("src.auth_recovery", None)
    recovery = importlib.import_module("src.auth_recovery")
    supabase = MagicMock()

    # Run 1: first page load without server-readable recovery params stays signed out.
    recovery.apply_password_recovery_from_query(supabase)
    report["run1_recovery_active"] = recovery.password_recovery_active()
    report["run1_no_token_promotion"] = not hasattr(recovery, "recovery_hash_bridge_markup")

    # Run 2: PKCE token_hash callback arrives in query params and activates recovery.
    st.query_params = {
        "token_hash": "recovery-token-hash",
        "type": "recovery",
        "cadivor_recovery": "1",
    }
    session = types.SimpleNamespace(
        access_token="access-token",
        refresh_token="refresh-token",
        user=types.SimpleNamespace(id="user-1", email="user@example.com"),
    )
    supabase.auth.verify_otp.return_value = types.SimpleNamespace(
        session=session,
        user=session.user,
    )
    recovery.apply_password_recovery_from_query(supabase)
    report["run2_recovery_active"] = recovery.password_recovery_active()
    report["run2_root_state"] = st.session_state.get("cadivor_root_state")
    report["run2_query_cleaned"] = "token_hash" not in st.query_params

    # Run 3: auth shell renders recovery UI instead of login.
    sys.modules.pop("src.auth", None)
    auth = importlib.import_module("src.auth")
    with patch.object(auth, "_auth_css"), patch.object(auth, "inject_core_premium_ui_auth"), patch.object(
        auth, "_render_password_recovery_form"
    ) as recovery_form, patch.object(auth, "_render_auth_page") as login_form:
        auth.show_auth_ui(supabase, None)
        report["run3_recovery_form_rendered"] = recovery_form.called
        report["run3_login_form_rendered"] = login_form.called

    report["ok"] = all(
        [
            report["run1_no_token_promotion"],
            not report["run1_recovery_active"],
            report["run2_recovery_active"],
            report["run2_root_state"] == "password_recovery",
            report["run2_query_cleaned"],
            report["run3_recovery_form_rendered"],
            not report["run3_login_form_rendered"],
        ]
    )
    return report


def main() -> int:
    report = run_harness()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

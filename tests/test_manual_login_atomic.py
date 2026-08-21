"""Sprint 71.10 — single-run atomic manual login tests."""
from __future__ import annotations

import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.test_auth_cookie_read_bridge import (
    _FakeContextCookies,
    _install_auth_modules,
    _install_streamlit_stub,
)

ROOT = Path(__file__).resolve().parents[1]


class ManualLoginAtomicTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name.startswith("src.auth"):
                sys.modules.pop(name, None)

    def _load_auth(self, session_state=None):
        st = _install_streamlit_stub(session_state or {}, context_cookies=_FakeContextCookies())
        st.rerun = MagicMock()
        st.error = MagicMock()
        st.success = MagicMock()
        st.warning = MagicMock()
        st.markdown = MagicMock()

        ui = types.ModuleType("src.ui.core_premium_ui")
        ui.inject_core_premium_ui_auth = MagicMock()
        sys.modules["src.ui.core_premium_ui"] = ui

        config = types.ModuleType("src.config")
        config.CADIVOR_MARKETING_URL = "https://www.cadivor.com/"
        sys.modules["src.config"] = config

        _auth_cookies, auth_state = _install_auth_modules(st)

        sys.modules.pop("src.auth", None)
        import importlib

        auth = importlib.import_module("src.auth")
        return st, auth, auth_state

    def test_login_submit_calls_sign_in_in_same_script_run(self):
        _st, auth, auth_state = self._load_auth()
        supabase = MagicMock()
        session = types.SimpleNamespace(access_token="a", refresh_token="r")
        user = types.SimpleNamespace(id="user-1")
        supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
            user=user,
            session=session,
        )
        cookie_manager = MagicMock()

        with patch.object(auth, "mark_authenticated") as mark_mock:
            auth._submit_manual_login(
                supabase,
                cookie_manager,
                "user@example.com",
                "secret",
            )

        supabase.auth.sign_in_with_password.assert_called_once_with({
            "email": "user@example.com",
            "password": "secret",
        })
        mark_mock.assert_called_once_with(user, session, cookie_manager)

    def test_login_submit_does_not_rerun_before_supabase(self):
        st, auth, _auth_state = self._load_auth()
        supabase = MagicMock()
        calls: list[str] = []

        def sign_in(credentials):
            calls.append("sign_in")
            return types.SimpleNamespace(
                user=types.SimpleNamespace(id="u"),
                session=types.SimpleNamespace(access_token="a", refresh_token="r"),
            )

        supabase.auth.sign_in_with_password.side_effect = sign_in

        def rerun():
            calls.append("rerun")

        auth.st.rerun = rerun

        auth._submit_manual_login(supabase, MagicMock(), "user@example.com", "secret")

        self.assertEqual(calls, ["sign_in", "rerun"])

    def test_password_is_never_stored_in_session_state(self):
        st, auth, _auth_state = self._load_auth()
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
            user=types.SimpleNamespace(id="u"),
            session=types.SimpleNamespace(access_token="a", refresh_token="r"),
        )

        auth._submit_manual_login(supabase, MagicMock(), "user@example.com", "secret")

        self.assertNotIn("cadivor_auth_submission", st.session_state)
        self.assertFalse(
            any(
                "secret" in str(value)
                for value in st.session_state.values()
            )
        )

    def test_successful_login_calls_mark_authenticated_before_rerun(self):
        st, auth, _auth_state = self._load_auth()
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
            user=types.SimpleNamespace(id="u"),
            session=types.SimpleNamespace(access_token="a", refresh_token="r"),
        )
        order: list[str] = []

        def mark_authenticated(*args, **kwargs):
            order.append("mark_authenticated")

        with patch.object(auth, "mark_authenticated", side_effect=mark_authenticated):
            auth.st.rerun = lambda: order.append("rerun")
            auth._submit_manual_login(supabase, MagicMock(), "user@example.com", "secret")

        self.assertEqual(order, ["mark_authenticated", "rerun"])

    def test_invalid_login_rebuilds_enabled_login_once(self):
        st, auth, _auth_state = self._load_auth()
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
            user=types.SimpleNamespace(id="u"),
            session=None,
        )

        with patch.object(auth, "mark_authenticated") as mark_mock:
            auth._submit_manual_login(supabase, MagicMock(), "user@example.com", "bad")

        mark_mock.assert_not_called()
        st.rerun.assert_called_once_with()
        self.assertEqual(st.session_state["cadivor_root_state"], auth.APP_LOGIN)
        self.assertEqual(
            st.session_state["cadivor_auth_error"],
            auth.MANUAL_LOGIN_NO_SESSION_MESSAGE,
        )
        st.error.assert_not_called()

    def test_auth_source_has_no_pending_submission_storage(self):
        source = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
        self.assertNotIn('cadivor_auth_submission', source)

    def test_bootstrap_has_no_pending_password_dependency(self):
        bootstrap_source = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
        self.assertNotIn("cadivor_auth_submission", bootstrap_source)
        auth_state_source = (ROOT / "src" / "auth_state.py").read_text(encoding="utf-8")
        self.assertNotIn('["cadivor_auth_submission"]', auth_state_source)
        self.assertNotIn('get("cadivor_auth_submission"', auth_state_source)
        self.assertIn('pop("cadivor_auth_submission", None)', auth_state_source)

    def test_submit_handler_uses_atomic_helpers(self):
        source = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
        self.assertIn("_submit_manual_login(", source)
        self.assertIn("_submit_manual_signup(", source)
        self.assertNotIn("cadivor_auth_submission", source)


if __name__ == "__main__":
    unittest.main()

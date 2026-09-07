"""Manual login two-phase gate tests (stash → authenticating → provider)."""
from __future__ import annotations

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
        st, restore_streamlit = _install_streamlit_stub(
            session_state or {}, context_cookies=_FakeContextCookies()
        )
        self.addCleanup(restore_streamlit)
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

        _auth_cookies, auth_state, restore_secrets = _install_auth_modules(st)
        self.addCleanup(restore_secrets)

        sys.modules.pop("src.auth", None)
        import importlib

        auth = importlib.import_module("src.auth")
        return st, auth, auth_state

    def test_login_submit_stashes_and_reruns_without_provider(self):
        st, auth, _auth_state = self._load_auth()
        supabase = MagicMock()
        cookie_manager = MagicMock()

        with patch.object(auth, "mark_authenticated") as mark_mock:
            auth._submit_manual_login(
                supabase,
                cookie_manager,
                "user@example.com",
                "secret",
            )

        supabase.auth.sign_in_with_password.assert_not_called()
        mark_mock.assert_not_called()
        st.rerun.assert_called_once_with()
        self.assertEqual(st.session_state["cadivor_root_state"], auth.APP_SIGNING_IN)
        from src.auth_gate import AUTH_GATE_PENDING_EMAIL_KEY, has_pending_credentials

        self.assertTrue(has_pending_credentials())
        self.assertEqual(
            st.session_state.get(AUTH_GATE_PENDING_EMAIL_KEY),
            "user@example.com",
        )
        # Submit paints Signing you in… inside the auth card (not a second gate).
        markdown_calls = " ".join(str(c) for c in st.markdown.call_args_list)
        self.assertIn("Signing you in…", markdown_calls)
        self.assertNotIn('class="cv-auth-gate"', markdown_calls)

    def test_login_submit_reruns_before_provider_io(self):
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

        self.assertEqual(calls, ["rerun"])
        self.assertNotIn("sign_in", calls)

    def test_pending_password_is_popped_on_provider_login(self):
        st, auth, _auth_state = self._load_auth()
        from src.auth_gate import (
            has_pending_credentials,
            pop_pending_credentials,
            stash_pending_credentials,
        )

        stash_pending_credentials("user@example.com", "secret")
        self.assertTrue(has_pending_credentials())
        email, password = pop_pending_credentials()
        self.assertFalse(has_pending_credentials())

        supabase = MagicMock()
        supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
            user=types.SimpleNamespace(id="u"),
            session=types.SimpleNamespace(access_token="a", refresh_token="r"),
        )
        with patch.object(auth, "mark_authenticated"):
            auth.execute_password_login(supabase, MagicMock(), email, password)

        self.assertFalse(has_pending_credentials())
        self.assertNotIn("cadivor_auth_submission", st.session_state)

    def test_successful_provider_login_calls_mark_authenticated_without_rerun(self):
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
            ok = auth.execute_password_login(
                supabase, MagicMock(), "user@example.com", "secret"
            )

        self.assertTrue(ok)
        self.assertEqual(order, ["mark_authenticated"])
        st.rerun.assert_not_called()

    def test_invalid_provider_login_rebuilds_enabled_login_once(self):
        st, auth, _auth_state = self._load_auth()
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
            user=types.SimpleNamespace(id="u"),
            session=None,
        )

        with patch.object(auth, "mark_authenticated") as mark_mock:
            ok = auth.execute_password_login(
                supabase, MagicMock(), "user@example.com", "bad"
            )

        self.assertFalse(ok)
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
        self.assertNotIn("cadivor_auth_submission", source)

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
        self.assertIn("_render_auth_card_signing_in()", source)
        self.assertNotIn("cadivor_auth_submission", source)


if __name__ == "__main__":
    unittest.main()

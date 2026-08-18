"""Sprint 75.2B.4.2 — visible Login failure rerun lifecycle."""
from __future__ import annotations

import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from tests.test_auth_cookie_read_bridge import (
    _FakeContextCookies,
    _install_auth_modules,
    _install_streamlit_stub,
)

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "secret-passphrase-not-stored"
EMAIL = "user@example.com"


class _RerunSignal(Exception):
    """Stand-in for Streamlit RerunException raised by st.rerun()."""


class _Lifecycle:
    def __init__(self):
        self.events: list[str] = []
        self.rerun_count = 0
        self.submit = False
        self.email = EMAIL
        self.password = PASSWORD
        self.st = None
        self.auth = None
        self.auth_state = None

    def record(self, event: str) -> None:
        self.events.append(event)

    def load(self, session_state=None):
        st = _install_streamlit_stub(
            session_state or {},
            context_cookies=_FakeContextCookies(),
        )
        lifecycle = self

        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def _rerun():
            lifecycle.rerun_count += 1
            lifecycle.record("rerun")
            raise _RerunSignal("rerun")

        def _error(message, *args, **kwargs):
            lifecycle.record(f"error:{message}")

        def _markdown(text, *args, **kwargs):
            blob = str(text)
            if "cv-auth-transition" in blob or "Opening your engineering workspace" in blob:
                lifecycle.record("transition")
            else:
                lifecycle.record("markdown")

        def _radio(*args, **kwargs):
            lifecycle.record("radio")
            return "Login"

        def _text_input(label, *args, **kwargs):
            lifecycle.record(f"text_input:{label}")
            if str(label).lower().startswith("password"):
                return lifecycle.password
            return lifecycle.email

        def _form_submit_button(*args, **kwargs):
            lifecycle.record("form_submit_button")
            disabled = bool(kwargs.get("disabled"))
            if disabled:
                lifecycle.record("submit_disabled")
            return bool(lifecycle.submit) and not disabled

        st.form = lambda *args, **kwargs: _Ctx()
        st.expander = lambda *args, **kwargs: _Ctx()
        st.spinner = lambda *args, **kwargs: _Ctx()
        st.rerun = _rerun
        st.error = _error
        st.success = lambda *args, **kwargs: lifecycle.record("success")
        st.warning = lambda *args, **kwargs: lifecycle.record("warning")
        st.markdown = _markdown
        st.radio = _radio
        st.text_input = _text_input
        st.form_submit_button = _form_submit_button
        st.button = lambda *args, **kwargs: False
        st.checkbox = lambda *args, **kwargs: True
        st.info = lambda *args, **kwargs: lifecycle.record("info")
        st.query_params = {}

        ui = types.ModuleType("src.ui.core_premium_ui")
        ui.inject_core_premium_ui_auth = lambda: lifecycle.record("inject")
        sys.modules["src.ui.core_premium_ui"] = ui
        config = types.ModuleType("src.config")
        config.CADIVOR_MARKETING_URL = "https://www.cadivor.com/"
        sys.modules["src.config"] = config

        _auth_cookies, auth_state = _install_auth_modules(st)
        sys.modules.pop("src.auth", None)
        import importlib

        auth = importlib.import_module("src.auth")
        auth._auth_css = lambda: lifecycle.record("auth_css")
        orig_transition = auth.render_auth_transition

        def _transition(message="Preparing Cadivor"):
            lifecycle.record(f"transition:{message[:40]}")
            orig_transition(message)

        auth.render_auth_transition = _transition
        self.st = st
        self.auth = auth
        self.auth_state = auth_state
        return self

    @staticmethod
    def _bind_login_provider(auth, supabase):
        def _bounded(email, password):
            return supabase.auth.sign_in_with_password({
                "email": email,
                "password": password,
            })

        auth._sign_in_with_password_bounded = _bounded


class LoginFailureRerun752B42Tests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name.startswith("src.auth"):
                sys.modules.pop(name, None)

    def _provider(self, *, side_effect=None, session=True):
        supabase = MagicMock()
        if side_effect is not None:
            supabase.auth.sign_in_with_password.side_effect = side_effect
        elif session:
            supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
                user=types.SimpleNamespace(id="user-1"),
                session=types.SimpleNamespace(access_token="a", refresh_token="r"),
            )
        else:
            supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
                user=types.SimpleNamespace(id="user-1"),
                session=None,
            )
        return supabase

    def _timeout_request(self) -> httpx.Request:
        return httpx.Request("POST", "https://example.invalid/auth/v1/token")

    def _run_failure_lifecycle(self, supabase, expected_message: str):
        life = _Lifecycle().load({"cadivor_root_state": "login", "cadivor_auth_status": "signed_out"})
        _Lifecycle._bind_login_provider(life.auth, supabase)
        life.submit = True
        with self.assertRaises(_RerunSignal):
            life.auth.show_auth_ui(supabase, None)

        run1 = list(life.events)
        self.assertIn("radio", run1)
        self.assertTrue(any(item.startswith("text_input:") for item in run1))
        self.assertIn("form_submit_button", run1)
        self.assertFalse(any(item.startswith("transition:") for item in run1))
        self.assertEqual(life.rerun_count, 1)
        self.assertEqual(supabase.auth.sign_in_with_password.call_count, 1)
        self.assertEqual(life.st.session_state["cadivor_root_state"], life.auth_state.APP_LOGIN)
        self.assertIsNone(life.st.session_state.get("cadivor_manual_login_in_progress"))
        self.assertIsNone(life.st.session_state.get("cadivor_manual_login_started_at"))
        self.assertIsNone(life.st.session_state.get("cadivor_manual_login_attempt_id"))
        self.assertEqual(life.st.session_state.get("cadivor_auth_error"), expected_message)
        self.assertNotIn(PASSWORD, str(life.st.session_state.values()))
        self.assertFalse(any(item.startswith("error:") for item in run1))

        life.events.clear()
        life.submit = False
        life.rerun_count = 0
        life.auth.show_auth_ui(supabase, None)
        run2 = list(life.events)
        self.assertIn("radio", run2)
        self.assertIn("form_submit_button", run2)
        self.assertTrue(any(item.startswith("text_input:") for item in run2))
        self.assertFalse(any(item.startswith("transition:") for item in run2))
        self.assertIn(f"error:{expected_message}", run2)
        self.assertEqual(life.rerun_count, 0)
        self.assertEqual(supabase.auth.sign_in_with_password.call_count, 1)
        self.assertNotIn("submit_disabled", run2)
        self.assertNotIn(PASSWORD, str(life.st.session_state.values()))
        return life

    def test_invalid_credentials_rebuilds_login(self):
        class AuthApiError(Exception):
            pass

        supabase = self._provider(side_effect=AuthApiError("Invalid login credentials"))
        self._run_failure_lifecycle(
            supabase,
            "Cadivor could not sign you in. Check your credentials and try again.",
        )

    def test_connect_timeout_rebuilds_login(self):
        supabase = self._provider(
            side_effect=httpx.ConnectTimeout("connect", request=self._timeout_request())
        )
        self._run_failure_lifecycle(
            supabase,
            "Cadivor could not complete sign-in in time. Please try again.",
        )

    def test_read_timeout_rebuilds_login(self):
        supabase = self._provider(
            side_effect=httpx.ReadTimeout("read", request=self._timeout_request())
        )
        self._run_failure_lifecycle(
            supabase,
            "Cadivor could not complete sign-in in time. Please try again.",
        )

    def test_generic_provider_exception_rebuilds_login(self):
        supabase = self._provider(side_effect=RuntimeError("provider down"))
        life = self._run_failure_lifecycle(
            supabase,
            "Cadivor could not sign you in. Check your credentials and try again.",
        )
        self.assertNotIn("provider down", str(life.st.session_state.get("cadivor_auth_error", "")))

    def test_no_session_rebuilds_login(self):
        supabase = self._provider(session=False)
        self._run_failure_lifecycle(
            supabase,
            "Cadivor could not sign you in. Check your credentials and try again.",
        )

    def test_successful_login_one_provider_call_one_rerun(self):
        life = _Lifecycle().load({"cadivor_root_state": "login", "cadivor_auth_status": "signed_out"})
        supabase = self._provider()
        _Lifecycle._bind_login_provider(life.auth, supabase)
        life.submit = True
        with patch.object(life.auth, "mark_authenticated") as mark:
            with self.assertRaises(_RerunSignal):
                life.auth.show_auth_ui(supabase, None)
        mark.assert_called_once()
        self.assertEqual(supabase.auth.sign_in_with_password.call_count, 1)
        self.assertEqual(life.rerun_count, 1)
        self.assertIsNone(life.st.session_state.get("cadivor_auth_error"))
        self.assertFalse(any(item.startswith("error:") for item in life.events))
        self.assertFalse(any(item.startswith("transition:") for item in life.events))

    def test_recent_signing_in_keeps_login_form_disabled(self):
        life = _Lifecycle().load()
        now = time.time()
        life.st.session_state.update(
            {
                "cadivor_root_state": life.auth_state.APP_SIGNING_IN,
                "cadivor_auth_status": life.auth_state.AUTH_SIGNING_IN,
                "cadivor_manual_login_in_progress": True,
                "cadivor_manual_login_started_at": now - 1.0,
                "cadivor_manual_login_attempt_id": "recent",
            }
        )
        supabase = self._provider()
        _Lifecycle._bind_login_provider(life.auth, supabase)
        life.submit = True
        life.auth.show_auth_ui(supabase, None)
        self.assertFalse(any(item.startswith("transition:") for item in life.events))
        self.assertIn("form_submit_button", life.events)
        self.assertIn("submit_disabled", life.events)
        supabase.auth.sign_in_with_password.assert_not_called()
        self.assertEqual(life.rerun_count, 0)

    def test_stale_signing_in_restores_login(self):
        life = _Lifecycle().load()
        timeout = life.auth_state.MANUAL_LOGIN_STALE_TIMEOUT_SECONDS
        now = time.time()
        life.st.session_state.update(
            {
                "cadivor_root_state": life.auth_state.APP_SIGNING_IN,
                "cadivor_auth_status": life.auth_state.AUTH_SIGNING_IN,
                "cadivor_manual_login_in_progress": True,
                "cadivor_manual_login_started_at": now - timeout - 5,
                "cadivor_manual_login_attempt_id": "stale",
            }
        )
        supabase = self._provider()
        life.submit = False
        life.auth.show_auth_ui(supabase, None)
        self.assertEqual(life.st.session_state["cadivor_root_state"], life.auth_state.APP_LOGIN)
        self.assertIsNone(life.st.session_state.get("cadivor_manual_login_in_progress"))
        self.assertIn(f"error:{life.auth_state.STALE_MANUAL_LOGIN_MESSAGE}", life.events)
        self.assertIn("form_submit_button", life.events)
        self.assertFalse(any(item.startswith("transition:") for item in life.events))
        supabase.auth.sign_in_with_password.assert_not_called()

    def test_rerun_exception_propagates_without_failure_rerun(self):
        life = _Lifecycle().load({"cadivor_root_state": "login"})
        class RerunException(Exception):
            pass

        supabase = self._provider(side_effect=RerunException("streamlit-rerun"))
        _Lifecycle._bind_login_provider(life.auth, supabase)
        life.submit = True
        with self.assertRaises(RerunException):
            life.auth.show_auth_ui(supabase, None)
        self.assertEqual(life.rerun_count, 0)
        self.assertTrue(life.st.session_state.get("cadivor_manual_login_in_progress"))
        self.assertEqual(life.st.session_state.get("cadivor_root_state"), life.auth_state.APP_SIGNING_IN)
        self.assertIsNone(life.st.session_state.get("cadivor_auth_error"))

    def test_stop_exception_propagates_without_failure_rerun(self):
        life = _Lifecycle().load({"cadivor_root_state": "login"})
        class StopException(Exception):
            pass

        supabase = self._provider(side_effect=StopException("streamlit-stop"))
        _Lifecycle._bind_login_provider(life.auth, supabase)
        life.submit = True
        with self.assertRaises(StopException):
            life.auth.show_auth_ui(supabase, None)
        self.assertEqual(life.rerun_count, 0)
        self.assertTrue(life.st.session_state.get("cadivor_manual_login_in_progress"))
        self.assertEqual(life.st.session_state.get("cadivor_root_state"), life.auth_state.APP_SIGNING_IN)
        self.assertIsNone(life.st.session_state.get("cadivor_auth_error"))

    def test_password_recovery_beats_inflight_login(self):
        life = _Lifecycle().load()
        life.st.session_state.update(
            {
                "cadivor_root_state": life.auth_state.APP_PASSWORD_RECOVERY,
                "cadivor_manual_login_in_progress": True,
                "cadivor_manual_login_started_at": time.time(),
                "cadivor_manual_login_attempt_id": "cb",
                "cadivor_auth_status": life.auth_state.AUTH_SIGNING_IN,
            }
        )
        with patch.object(life.auth, "_render_password_recovery_form") as recovery, patch.object(
            life.auth, "_render_auth_page"
        ) as login_form:
            life.auth.show_auth_ui(MagicMock(), None)
        recovery.assert_called_once()
        login_form.assert_not_called()
        self.assertFalse(any(item.startswith("transition:") for item in life.events))
        self.assertIsNone(life.st.session_state.get("cadivor_manual_login_in_progress"))

    def test_signup_confirmation_beats_inflight_login(self):
        life = _Lifecycle().load()
        life.st.session_state.update(
            {
                "cadivor_root_state": life.auth_state.APP_SIGNUP_CONFIRMATION_PENDING,
                "cadivor_manual_login_in_progress": True,
                "cadivor_manual_login_started_at": time.time(),
                "cadivor_manual_login_attempt_id": "cb",
                life.auth_state.SIGNUP_PENDING_EMAIL_KEY: "new@cadivor.com",
            }
        )
        with patch.object(life.auth, "_render_signup_confirmation_pending") as pending, patch.object(
            life.auth, "_render_auth_page"
        ) as login_form:
            life.auth.show_auth_ui(MagicMock(), None)
        pending.assert_called_once()
        login_form.assert_not_called()
        self.assertFalse(any(item.startswith("transition:") for item in life.events))
        self.assertIsNone(life.st.session_state.get("cadivor_manual_login_in_progress"))

    def test_password_absent_after_failure_rerun(self):
        supabase = self._provider(side_effect=RuntimeError("nope"))
        life = self._run_failure_lifecycle(
            supabase,
            "Cadivor could not sign you in. Check your credentials and try again.",
        )
        for value in life.st.session_state.values():
            self.assertNotEqual(str(value), PASSWORD)

    def test_static_guard_login_only_bounded_transport(self):
        auth_src = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
        bootstrap_src = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
        bounded_start = auth_src.find("def _sign_in_with_password_bounded")
        bounded_end = auth_src.find("\ndef _submit_manual_login", bounded_start)
        self.assertTrue(bounded_start >= 0)
        bounded_block = auth_src[bounded_start:bounded_end]
        self.assertIn("httpx_client", bounded_block)
        self.assertIn("httpx.Timeout(5.0, read=10.0, write=10.0, pool=5.0)", bounded_block)
        self.assertNotIn("httpx_client", auth_src[:bounded_start])
        self.assertNotIn("httpx_client", auth_src[bounded_end:])
        self.assertNotIn("ThreadPoolExecutor", auth_src)
        self.assertNotIn("supabase._sync", auth_src)
        self.assertNotIn("supabase._sync", bootstrap_src)
        self.assertIn(
            'options=SyncClientOptions(flow_type="pkce", storage=SyncMemoryStorage())',
            bootstrap_src,
        )
        baseline = (
            '        return create_client(\n'
            '            url,\n'
            '            key,\n'
            '            options=SyncClientOptions(flow_type="pkce", storage=SyncMemoryStorage()),\n'
            '        )\n'
        )
        self.assertIn(baseline, bootstrap_src)
        self.assertNotIn("SUPABASE_HTTP_CONNECT_TIMEOUT", bootstrap_src)
        self.assertNotIn("build_supabase_httpx_client", bootstrap_src)


if __name__ == "__main__":
    unittest.main()

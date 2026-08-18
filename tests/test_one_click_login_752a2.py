"""Sprint 75.2A.2 — one-click Login focused contract and password-clearing matrix."""
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
SECRET = "s3cret-login-value"
EMAIL = "user@example.com"


class _RerunSignal(Exception):
    """Stand-in for Streamlit RerunException (tests may also use BaseException)."""


class _RerunBase(BaseException):
    """Mirrors Streamlit RerunException: BaseException, not Exception."""


class _StopBase(BaseException):
    """Mirrors Streamlit StopException: BaseException, not Exception."""


class OneClickLogin752A2Tests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name.startswith("src.auth"):
                sys.modules.pop(name, None)

    def _load(self, session_state=None):
        st = _install_streamlit_stub(
            session_state or {},
            context_cookies=_FakeContextCookies(),
        )
        st.rerun = MagicMock(side_effect=_RerunSignal("rerun"))
        st.error = MagicMock()
        st.success = MagicMock()
        st.warning = MagicMock()
        st.markdown = MagicMock()
        st.info = MagicMock()
        st.radio = MagicMock(return_value="Login")
        st.button = MagicMock(return_value=False)
        st.checkbox = MagicMock(return_value=True)
        st.text_input = MagicMock(return_value="")
        st.form_submit_button = MagicMock(return_value=False)

        class _CM:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        st.form = lambda *a, **k: _CM()
        st.expander = lambda *a, **k: _CM()
        st.query_params = {}

        ui = types.ModuleType("src.ui.core_premium_ui")
        ui.inject_core_premium_ui_auth = MagicMock()
        sys.modules["src.ui.core_premium_ui"] = ui
        config = types.ModuleType("src.config")
        config.CADIVOR_MARKETING_URL = "https://www.cadivor.com/"
        sys.modules["src.config"] = config

        _install_auth_modules(st)
        sys.modules.pop("src.auth", None)
        import importlib

        auth = importlib.import_module("src.auth")
        auth_state = importlib.import_module("src.auth_state")
        return st, auth, auth_state

    def _login_state(self, auth, auth_state, **extra):
        state = {
            "cadivor_root_state": auth_state.APP_LOGIN,
            "cadivor_auth_status": auth_state.AUTH_SIGNED_OUT,
            "cadivor_auth_intent_applied": True,
            auth.AUTH_MODE_WIDGET_KEY: auth.AUTH_MODE_LOGIN,
            auth.AUTH_EMAIL_WIDGET_KEY: EMAIL,
            auth.AUTH_PASSWORD_WIDGET_KEY: SECRET,
        }
        state.update(extra)
        return state

    def _provider(self, *, session=True, error=None):
        supabase = MagicMock()
        user = types.SimpleNamespace(id="user-1")
        sess = types.SimpleNamespace(access_token="a", refresh_token="r") if session else None
        if error is not None:
            supabase.auth.sign_in_with_password.side_effect = error
        else:
            supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
                user=user,
                session=sess,
            )
        return supabase, user, sess

    def _assert_secret_absent(self, st, auth, extra_blobs=()):
        self.assertNotIn(auth.AUTH_PASSWORD_WIDGET_KEY, st.session_state)
        blobs = [str(v) for v in st.session_state.values()]
        blobs.extend(str(item) for item in extra_blobs)
        blobs.append(str(st.query_params))
        blobs.extend(str(item) for item in (st.session_state.get("cadivor_auth_debug_log") or []))
        self.assertFalse(any(SECRET in blob for blob in blobs))

    def _submit_login(self, st, auth, supabase):
        st.form_submit_button = MagicMock(return_value=True)
        st.text_input = MagicMock(return_value="")
        with patch.object(auth, "inject_core_premium_ui_auth"):
            auth.show_auth_ui(supabase, None)

    # --- 1. One valid submit ---
    def test_01_one_valid_submit(self):
        st, auth, auth_state = self._load()
        st.session_state.update(self._login_state(auth, auth_state))
        supabase, user, session = self._provider()
        with self.assertRaises(_RerunSignal):
            self._submit_login(st, auth, supabase)
        supabase.auth.sign_in_with_password.assert_called_once()
        self.assertEqual(st.session_state["cadivor_root_state"], auth_state.APP_AUTHENTICATED)
        self.assertIs(st.session_state.get("user"), user)
        self.assertEqual(st.session_state.get("access_token"), session.access_token)

    # --- 2. No second submit ---
    def test_02_no_second_submit_or_provider_call(self):
        st, auth, auth_state = self._load()
        st.session_state.update(self._login_state(auth, auth_state))
        supabase, _user, _session = self._provider()
        with self.assertRaises(_RerunSignal):
            self._submit_login(st, auth, supabase)
        status = auth_state.resolve_auth_state(supabase, None)
        self.assertEqual(status, auth_state.AUTH_AUTHENTICATED)
        supabase.auth.sign_in_with_password.assert_called_once()
        st.form_submit_button = MagicMock(return_value=False)
        with patch.object(auth, "inject_core_premium_ui_auth"):
            # Authenticated session must not call the provider again.
            pass
        self.assertEqual(supabase.auth.sign_in_with_password.call_count, 1)

    # --- 3. Tokens persisted before rerun ---
    def test_03_tokens_persisted_before_rerun(self):
        st, auth, auth_state = self._load()
        st.session_state.update(self._login_state(auth, auth_state))
        supabase, _user, session = self._provider()
        events: list[str] = []

        def mark(user_arg, session_arg, cookie_manager=None):
            events.append("mark_authenticated")
            auth_state.mark_authenticated(user_arg, session_arg, cookie_manager)
            self.assertTrue(bool(st.session_state.get("access_token")))
            self.assertTrue(bool(st.session_state.get("refresh_token")))
            self.assertNotIn(auth.AUTH_PASSWORD_WIDGET_KEY, st.session_state)

        def rerun():
            events.append("rerun")
            self.assertTrue(bool(st.session_state.get("access_token")))
            self.assertTrue(bool(st.session_state.get("refresh_token")))
            raise _RerunSignal("rerun")

        st.form_submit_button = MagicMock(return_value=True)
        st.rerun = rerun
        with patch.object(auth, "mark_authenticated", side_effect=mark):
            with patch.object(auth, "inject_core_premium_ui_auth"):
                with self.assertRaises(_RerunSignal):
                    auth.show_auth_ui(supabase, None)
        self.assertEqual(events, ["mark_authenticated", "rerun"])

    # --- 4. Invalid credentials ---
    def test_04_invalid_credentials(self):
        st, auth, auth_state = self._load()
        st.session_state.update(self._login_state(auth, auth_state))
        supabase, _user, _session = self._provider(
            error=Exception("Invalid login credentials")
        )
        with self.assertRaises(_RerunSignal):
            self._submit_login(st, auth, supabase)
        supabase.auth.sign_in_with_password.assert_called_once()
        self.assertIsNone(st.session_state.get("user"))
        self.assertEqual(st.session_state["cadivor_root_state"], auth_state.APP_LOGIN)
        self.assertEqual(st.session_state["cadivor_auth_status"], auth_state.AUTH_SIGNED_OUT)
        self._assert_secret_absent(st, auth, (st.session_state.get("cadivor_auth_error"),))

    # --- 5. Provider failure ---
    def test_05_provider_failure(self):
        st, auth, auth_state = self._load()
        st.session_state.update(self._login_state(auth, auth_state))
        supabase, _user, _session = self._provider(
            error=RuntimeError("upstream 503")
        )
        with self.assertRaises(_RerunSignal):
            self._submit_login(st, auth, supabase)
        self.assertIsNone(st.session_state.get("access_token"))
        self.assertEqual(st.session_state["cadivor_root_state"], auth_state.APP_LOGIN)
        self._assert_secret_absent(st, auth, (st.session_state.get("cadivor_auth_error"),))

    # --- 6. No-session response ---
    def test_06_no_session_response(self):
        st, auth, auth_state = self._load()
        st.session_state.update(self._login_state(auth, auth_state))
        supabase, _user, _session = self._provider(session=False)
        with self.assertRaises(_RerunSignal):
            self._submit_login(st, auth, supabase)
        self.assertIsNone(st.session_state.get("user"))
        self.assertIn("no session", str(st.session_state.get("cadivor_auth_error") or "").lower())
        self._assert_secret_absent(st, auth, (st.session_state.get("cadivor_auth_error"),))

    # --- 7. Safe error copy ---
    def test_07_safe_error_copy(self):
        st, auth, auth_state = self._load()
        st.session_state.update(self._login_state(auth, auth_state))
        leaked = Exception(f"AuthApiError {SECRET} stack")
        supabase, _user, _session = self._provider(error=leaked)
        with self.assertRaises(_RerunSignal):
            self._submit_login(st, auth, supabase)
        message = str(st.session_state.get("cadivor_auth_error") or "")
        self.assertEqual(message, auth._LOGIN_PROVIDER_ERROR)
        self.assertNotIn(SECRET, message)
        self.assertNotIn("AuthApiError", message)
        self.assertNotIn("stack", message)
        self.assertNotIn("traceback", message.lower())
        for call in st.error.call_args_list:
            self.assertNotIn(SECRET, str(call))

    # --- 8. No rerun loop ---
    def test_08_no_rerun_loop(self):
        st, auth, auth_state = self._load()
        st.session_state.update(self._login_state(auth, auth_state))
        supabase, _user, _session = self._provider()
        reruns = {"n": 0}

        def rerun():
            reruns["n"] += 1
            raise _RerunSignal("rerun")

        st.rerun = rerun
        with self.assertRaises(_RerunSignal):
            self._submit_login(st, auth, supabase)
        self.assertEqual(reruns["n"], 1)
        supabase.auth.sign_in_with_password.assert_called_once()

    # --- 9. RerunException ---
    def test_09_rerun_exception_propagates(self):
        st, auth, _auth_state = self._load()
        supabase, _user, _session = self._provider()
        st.rerun = MagicMock(side_effect=_RerunBase("streamlit-rerun"))
        with self.assertRaises(_RerunBase):
            auth._submit_manual_login(supabase, MagicMock(), EMAIL, SECRET)

    # --- 10. StopException ---
    def test_10_stop_exception_propagates(self):
        st, auth, _auth_state = self._load()
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.side_effect = _StopBase("streamlit-stop")
        with self.assertRaises(_StopBase):
            auth._submit_manual_login(supabase, MagicMock(), EMAIL, SECRET)
        self.assertIsNone(st.session_state.get("user"))

    # --- 11. Recovery precedence ---
    def test_11_recovery_precedence(self):
        st, auth, auth_state = self._load()
        st.session_state.update(
            self._login_state(
                auth,
                auth_state,
                cadivor_root_state=auth_state.APP_PASSWORD_RECOVERY,
                cadivor_password_recovery_active=True,
                cadivor_manual_login_in_progress=True,
            )
        )
        supabase, _user, _session = self._provider()
        st.form_submit_button = MagicMock(return_value=True)
        with patch.object(auth, "inject_core_premium_ui_auth"):
            with patch.object(auth, "_render_password_recovery_form") as recovery_form:
                with patch.object(auth, "_render_auth_page") as login_page:
                    auth.show_auth_ui(supabase, None)
        recovery_form.assert_called_once()
        login_page.assert_not_called()
        supabase.auth.sign_in_with_password.assert_not_called()
        self._assert_secret_absent(st, auth)

    # --- 12. Signup-confirmation precedence ---
    def test_12_signup_confirmation_precedence(self):
        st, auth, auth_state = self._load()
        st.session_state.update(
            self._login_state(
                auth,
                auth_state,
                cadivor_root_state=auth_state.APP_SIGNUP_CONFIRMATION_PENDING,
                cadivor_manual_login_in_progress=True,
                cadivor_signup_pending_email=EMAIL,
            )
        )
        supabase, _user, _session = self._provider()
        st.form_submit_button = MagicMock(return_value=True)
        with patch.object(auth, "inject_core_premium_ui_auth"):
            with patch.object(auth, "_render_signup_confirmation_pending") as pending:
                with patch.object(auth, "_render_auth_page") as login_page:
                    auth.show_auth_ui(supabase, None)
        pending.assert_called_once()
        login_page.assert_not_called()
        supabase.auth.sign_in_with_password.assert_not_called()
        self._assert_secret_absent(st, auth)

    # --- 13. Bootstrap/client unchanged ---
    def test_13_bootstrap_and_client_unchanged(self):
        bootstrap = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
        auth_source = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
        self.assertNotIn("cadivor_auth_password", bootstrap)
        self.assertNotIn("httpx", auth_source)
        self.assertNotIn("ThreadPoolExecutor", auth_source)
        self.assertNotIn("sign_in_with_password", bootstrap)

    # --- 14. No rejected 75.2B patterns ---
    def test_14_no_rejected_752b_patterns(self):
        source = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
        submit_block = source[
            source.find("def _submit_manual_login") : source.find("def _signup_response_get")
        ]
        compact = "".join(source.split())
        self.assertNotIn("render_auth_transition(", submit_block)
        self.assertNotIn("ThreadPoolExecutor", source)
        self.assertNotIn("httpx", source)
        self.assertNotIn("45", submit_block)
        self.assertNotIn("window.location", source)
        self.assertNotIn("document.click", source)
        self.assertNotIn("DeltaGenerator", source)
        self.assertNotIn("stVerticalBlock]{gap:0", compact)
        self.assertNotIn("gap:0!important", compact)

        tree = ast.parse(source)
        submit = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "_submit_manual_login":
                submit = node
                break
        self.assertIsNotNone(submit)
        calls = [
            n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            for n in ast.walk(submit)
            if isinstance(n, ast.Call)
        ]
        self.assertNotIn("render_auth_transition", calls)

    def test_signing_in_recovery_does_not_reseed_radio_or_drop_submit(self):
        st, auth, auth_state = self._load()
        st.session_state.update(
            self._login_state(
                auth,
                auth_state,
                cadivor_root_state=auth_state.APP_SIGNING_IN,
                cadivor_auth_status=auth_state.AUTH_SIGNING_IN,
                cadivor_manual_login_in_progress=True,
            )
        )
        st.form_submit_button = MagicMock(return_value=True)
        st.text_input = MagicMock(return_value="")
        supabase, _user, _session = self._provider()
        mode_before = st.session_state[auth.AUTH_MODE_WIDGET_KEY]
        with patch.object(auth, "inject_core_premium_ui_auth"):
            with self.assertRaises(_RerunSignal):
                auth.show_auth_ui(supabase, None)
        self.assertEqual(st.session_state[auth.AUTH_MODE_WIDGET_KEY], mode_before)
        supabase.auth.sign_in_with_password.assert_called_once()
        self.assertEqual(st.session_state["cadivor_root_state"], auth_state.APP_AUTHENTICATED)

    def test_signing_in_without_submit_does_not_call_provider(self):
        st, auth, auth_state = self._load()
        st.session_state.update(
            self._login_state(
                auth,
                auth_state,
                cadivor_root_state=auth_state.APP_SIGNING_IN,
                cadivor_manual_login_in_progress=True,
            )
        )
        st.form_submit_button = MagicMock(return_value=False)
        supabase, _user, _session = self._provider()
        with patch.object(auth, "inject_core_premium_ui_auth"):
            with self.assertRaises(_RerunSignal):
                auth.show_auth_ui(supabase, None)
        supabase.auth.sign_in_with_password.assert_not_called()
        self.assertFalse(st.session_state.get("cadivor_manual_login_in_progress"))
        self._assert_secret_absent(st, auth)

    def test_login_submit_does_not_render_transition_card(self):
        _st, auth, _auth_state = self._load()
        supabase, _user, _session = self._provider()
        with patch.object(auth, "render_auth_transition") as transition:
            with self.assertRaises(_RerunSignal):
                auth._submit_manual_login(supabase, MagicMock(), EMAIL, SECRET)
        transition.assert_not_called()
        supabase.auth.sign_in_with_password.assert_called_once()

    def test_source_has_stable_credential_keys(self):
        source = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
        self.assertIn('AUTH_EMAIL_WIDGET_KEY = "cadivor_auth_email"', source)
        self.assertIn('AUTH_PASSWORD_WIDGET_KEY = "cadivor_auth_password"', source)
        self.assertIn("key=AUTH_EMAIL_WIDGET_KEY", source)
        self.assertIn("key=AUTH_PASSWORD_WIDGET_KEY", source)
        submit_block = source[
            source.find("def _submit_manual_login") : source.find("def _signup_response_get")
        ]
        self.assertNotIn("render_auth_transition(", submit_block)

    def test_signing_in_does_not_disable_login(self):
        st, auth, auth_state = self._load()
        st.session_state.update(
            self._login_state(
                auth,
                auth_state,
                cadivor_root_state=auth_state.APP_SIGNING_IN,
                cadivor_manual_login_in_progress=True,
            )
        )
        st.form_submit_button = MagicMock(return_value=False)
        supabase, _user, _session = self._provider()
        with patch.object(auth, "inject_core_premium_ui_auth"):
            with patch.object(auth, "_render_auth_page", wraps=auth._render_auth_page) as page:
                with self.assertRaises(_RerunSignal):
                    auth.show_auth_ui(supabase, None)
        page.assert_called_once()
        self.assertEqual(st.session_state["cadivor_root_state"], auth_state.APP_LOGIN)

    # --- Password-clearing matrix ---
    def test_password_cleared_on_successful_login_before_rerun(self):
        st, auth, auth_state = self._load()
        st.session_state.update(self._login_state(auth, auth_state))
        supabase, _user, _session = self._provider()
        seen_before_rerun = {"password_present": True}

        def rerun():
            seen_before_rerun["password_present"] = auth.AUTH_PASSWORD_WIDGET_KEY in st.session_state
            raise _RerunSignal("rerun")

        st.rerun = rerun
        with self.assertRaises(_RerunSignal):
            self._submit_login(st, auth, supabase)
        self.assertFalse(seen_before_rerun["password_present"])
        self._assert_secret_absent(st, auth)

    def test_password_cleared_on_invalid_and_provider_and_no_session(self):
        cases = [
            {"error": Exception("Invalid login credentials")},
            {"error": RuntimeError("boom")},
            {"session": False},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                self.setUp()
                st, auth, auth_state = self._load()
                st.session_state.update(self._login_state(auth, auth_state))
                supabase, _user, _session = self._provider(**kwargs)
                with self.assertRaises(_RerunSignal):
                    self._submit_login(st, auth, supabase)
                self._assert_secret_absent(st, auth)

    def test_password_cleared_on_logout(self):
        st, auth, auth_state = self._load()
        st.session_state[auth.AUTH_PASSWORD_WIDGET_KEY] = SECRET
        auth_state._clear_user_session_for_logout()
        self._assert_secret_absent(st, auth)

    def test_password_cleared_on_clear_auth_session(self):
        st, auth, auth_state = self._load()
        st.session_state[auth.AUTH_PASSWORD_WIDGET_KEY] = SECRET
        auth_state.clear_auth_session()
        self._assert_secret_absent(st, auth)

    def test_password_cleared_on_password_recovery_entry(self):
        st, auth, auth_state = self._load()
        st.session_state.update(
            self._login_state(
                auth,
                auth_state,
                cadivor_root_state=auth_state.APP_PASSWORD_RESET,
            )
        )
        supabase, _user, _session = self._provider()
        with patch.object(auth, "inject_core_premium_ui_auth"):
            with patch.object(auth, "_render_password_reset_request"):
                auth.show_auth_ui(supabase, None)
        self._assert_secret_absent(st, auth)

    def test_password_cleared_on_recovery_form_entry(self):
        st, auth, auth_state = self._load()
        st.session_state.update(
            self._login_state(
                auth,
                auth_state,
                cadivor_root_state=auth_state.APP_PASSWORD_RECOVERY,
                cadivor_password_recovery_active=True,
            )
        )
        supabase, _user, _session = self._provider()
        with patch.object(auth, "inject_core_premium_ui_auth"):
            with patch.object(auth, "_render_password_recovery_form"):
                auth.show_auth_ui(supabase, None)
        self._assert_secret_absent(st, auth)

    def test_password_cleared_on_signup_confirmation_entry(self):
        st, auth, auth_state = self._load()
        st.session_state.update(
            self._login_state(
                auth,
                auth_state,
                cadivor_root_state=auth_state.APP_SIGNUP_CONFIRMATION_PENDING,
            )
        )
        supabase, _user, _session = self._provider()
        with patch.object(auth, "inject_core_premium_ui_auth"):
            with patch.object(auth, "_render_signup_confirmation_pending"):
                auth.show_auth_ui(supabase, None)
        self._assert_secret_absent(st, auth)

    def test_password_cleared_on_login_to_create_account(self):
        st, auth, auth_state = self._load()
        st.session_state.update(
            self._login_state(
                auth,
                auth_state,
                cadivor_last_auth_mode=auth.AUTH_MODE_LOGIN,
            )
        )
        st.radio = MagicMock(return_value=auth.AUTH_MODE_SIGNUP)
        st.form_submit_button = MagicMock(return_value=False)
        supabase, _user, _session = self._provider()
        with patch.object(auth, "inject_core_premium_ui_auth"):
            auth.show_auth_ui(supabase, None)
        self._assert_secret_absent(st, auth)

    def test_password_cleared_on_stale_signing_in_recovery(self):
        st, auth, auth_state = self._load()
        st.session_state.update(
            self._login_state(
                auth,
                auth_state,
                cadivor_root_state=auth_state.APP_SIGNING_IN,
                cadivor_manual_login_in_progress=True,
            )
        )
        st.form_submit_button = MagicMock(return_value=False)
        supabase, _user, _session = self._provider()
        with patch.object(auth, "inject_core_premium_ui_auth"):
            with self.assertRaises(_RerunSignal):
                auth.show_auth_ui(supabase, None)
        self._assert_secret_absent(st, auth)

    def test_password_not_written_to_query_or_debug_log(self):
        st, auth, auth_state = self._load()
        st.session_state.update(self._login_state(auth, auth_state))
        supabase, _user, _session = self._provider()
        with self.assertRaises(_RerunSignal):
            self._submit_login(st, auth, supabase)
        self.assertNotIn("password", {str(k).lower() for k in st.query_params})
        self._assert_secret_absent(st, auth)
        auth_state._log("probe", password=SECRET, cadivor_auth_password=SECRET)
        log = st.session_state.get("cadivor_auth_debug_log") or []
        self.assertFalse(any(SECRET in str(item) for item in log))


if __name__ == "__main__":
    unittest.main()

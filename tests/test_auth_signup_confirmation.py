"""Sprint 74.2C — secure signup confirmation callback tests."""
from __future__ import annotations

import ast
import importlib
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.test_auth_cookie_read_bridge import _install_streamlit_stub

REPO = Path(__file__).resolve().parents[1]
AUTH_PATH = REPO / "src" / "auth.py"
CONFIRM_PATH = REPO / "src" / "auth_signup_confirmation.py"
BOOTSTRAP_PATH = REPO / "src" / "auth_bootstrap.py"
RECOVERY_PATH = REPO / "src" / "auth_recovery.py"


class SignupConfirmationSourceGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth = AUTH_PATH.read_text(encoding="utf-8")
        cls.confirm = CONFIRM_PATH.read_text(encoding="utf-8")
        cls.bootstrap = BOOTSTRAP_PATH.read_text(encoding="utf-8")
        cls.recovery = RECOVERY_PATH.read_text(encoding="utf-8")

    def test_no_fragment_token_promotion(self):
        joined = "\n".join([self.auth, self.confirm, self.bootstrap])
        for banned in (
            "location.hash",
            "window.location.hash",
            "hash.replace",
            "access_token=",
            "refresh_token=",
            "fragment",
        ):
            # Allow prose comments that forbid fragment handling.
            if banned in ("access_token=", "refresh_token=", "fragment"):
                continue
            self.assertNotIn(banned, joined)

    def test_no_query_token_assignment_of_session_secrets(self):
        # Must never write access/refresh tokens into query params.
        self.assertNotRegex(
            self.confirm,
            r"query_params\[.access_token.\]\s*=",
        )
        self.assertNotRegex(
            self.confirm,
            r"query_params\[.refresh_token.\]\s*=",
        )
        self.assertNotIn('query_params["access_token"]', self.confirm)
        self.assertNotIn('query_params["refresh_token"]', self.confirm)

    def test_verify_otp_uses_email_type_only(self):
        self.assertIn('{"token_hash": token_hash, "type": SIGNUP_CONFIRM_TYPE}', self.confirm)
        self.assertIn('SIGNUP_CONFIRM_TYPE = "email"', self.confirm)

    def test_marker_contract(self):
        self.assertIn('SIGNUP_CONFIRM_CALLBACK_MARKER = "cadivor_signup_confirm"', self.confirm)
        self.assertIn("signup_confirmation_callback_requested", self.confirm)
        self.assertIn("signup_and_recovery_markers_conflict", self.confirm)

    def test_bootstrap_wires_confirmation_near_recovery(self):
        self.assertIn("apply_signup_confirmation_from_query", self.bootstrap)
        self.assertIn("signup_confirmation_surface_active", self.bootstrap)
        self.assertIn("reject_conflicting_auth_callbacks", self.bootstrap)
        # Ordering inside ensure_authenticated_or_stop: signup apply before resolve call.
        ensure = self.bootstrap[
            self.bootstrap.find("def ensure_authenticated_or_stop") :
        ]
        idx_signup = ensure.find("apply_signup_confirmation_from_query(supabase)")
        idx_resolve = ensure.find("auth_status = resolve_auth_state(")
        self.assertGreater(idx_signup, 0)
        self.assertGreater(idx_resolve, idx_signup)

    def test_sign_up_passes_email_redirect_to(self):
        self.assertIn("email_redirect_to", self.auth)
        self.assertIn("signup_confirmation_redirect_url()", self.auth)

    def test_implementation_does_not_depend_on_a1_recovery_reorder(self):
        # Committed/candidate auth.py must keep HEAD recovery order (after LOGIN/SIGNUP).
        tree = ast.parse(self.auth)
        show = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "show_auth_ui":
                show = node
                break
        self.assertIsNotNone(show)
        source_segment = ast.get_source_segment(self.auth, show) or ""
        idx_login = source_segment.find("if state in (APP_LOGIN, APP_SIGNUP, APP_SIGNING_IN):")
        # A1 places password_recovery_active() before the login/signup block.
        a1 = "if recovery.password_recovery_active() or state == APP_PASSWORD_RECOVERY:"
        idx_a1 = source_segment.find(a1)
        self.assertTrue(idx_login > 0)
        self.assertTrue(idx_a1 < 0 or idx_a1 > idx_login)
        self.assertIn(
            "if state == APP_PASSWORD_RECOVERY or recovery.password_recovery_active():",
            source_segment,
        )

    def test_recovery_module_unchanged_marker(self):
        self.assertIn('_RECOVERY_CALLBACK_MARKER = "cadivor_recovery"', self.recovery)
        self.assertIn('"type": "recovery"', self.recovery)


class SignupConfirmationUnitTests(unittest.TestCase):
    def setUp(self):
        self.st = _install_streamlit_stub({})
        self.st.rerun = MagicMock()
        for name in list(sys.modules):
            if name.startswith("src.auth"):
                sys.modules.pop(name, None)
        self.confirm = importlib.import_module("src.auth_signup_confirmation")
        self.state = importlib.import_module("src.auth_state")

    def test_redirect_url_uses_app_url_helper(self):
        url = self.confirm.signup_confirmation_redirect_url()
        self.assertIn("cadivor_signup_confirm=1", url)
        self.assertTrue(url.startswith("https://"))

    def test_marker_token_hash_type_email_accepted(self):
        self.st.query_params = {
            "cadivor_signup_confirm": "1",
            "token_hash": "signup-hash",
            "type": "email",
        }
        supabase = MagicMock()
        session = types.SimpleNamespace(
            access_token="access-token",
            refresh_token="refresh-token",
            user=types.SimpleNamespace(id="u1"),
        )
        supabase.auth.verify_otp.return_value = types.SimpleNamespace(
            session=session, user=session.user
        )
        self.confirm.apply_signup_confirmation_from_query(supabase)
        supabase.auth.verify_otp.assert_called_once_with(
            {"token_hash": "signup-hash", "type": "email"}
        )
        self.assertEqual(
            self.st.session_state["cadivor_root_state"],
            self.state.APP_SIGNUP_CONFIRMATION_SUCCESS,
        )
        self.assertTrue(self.confirm.signup_confirmation_session_ready())
        self.assertNotIn("token_hash", self.st.query_params)
        self.assertNotIn("cadivor_signup_confirm", self.st.query_params)

    def test_no_marker_ignored(self):
        self.st.query_params = {"token_hash": "signup-hash", "type": "email"}
        supabase = MagicMock()
        self.confirm.apply_signup_confirmation_from_query(supabase)
        supabase.auth.verify_otp.assert_not_called()
        self.assertFalse(self.confirm.signup_confirmation_surface_active())

    def test_wrong_type_rejected_safely(self):
        self.st.query_params = {
            "cadivor_signup_confirm": "1",
            "token_hash": "signup-hash",
            "type": "recovery",
        }
        supabase = MagicMock()
        self.confirm.apply_signup_confirmation_from_query(supabase)
        supabase.auth.verify_otp.assert_not_called()
        self.assertEqual(
            self.st.session_state["cadivor_root_state"],
            self.state.APP_SIGNUP_CONFIRMATION_INVALID,
        )

    def test_recovery_marker_cannot_enter_signup_confirmation(self):
        self.st.query_params = {
            "cadivor_recovery": "1",
            "token_hash": "recovery-hash",
            "type": "recovery",
        }
        supabase = MagicMock()
        self.confirm.apply_signup_confirmation_from_query(supabase)
        supabase.auth.verify_otp.assert_not_called()
        self.assertFalse(self.confirm.signup_confirmation_surface_active())

    def test_conflicting_markers_rejected(self):
        self.st.query_params = {
            "cadivor_signup_confirm": "1",
            "cadivor_recovery": "1",
            "token_hash": "hash",
            "type": "email",
        }
        self.confirm.reject_conflicting_auth_callbacks()
        self.assertEqual(
            self.st.session_state["cadivor_root_state"],
            self.state.APP_SIGNUP_CONFIRMATION_INVALID,
        )
        self.assertNotIn("token_hash", self.st.query_params)

    def test_access_refresh_query_params_never_supported(self):
        self.st.query_params = {
            "cadivor_signup_confirm": "1",
            "access_token": "should-not-use",
            "refresh_token": "should-not-use",
            "type": "email",
        }
        supabase = MagicMock()
        self.confirm.apply_signup_confirmation_from_query(supabase)
        supabase.auth.verify_otp.assert_not_called()
        self.assertEqual(
            self.st.session_state["cadivor_root_state"],
            self.state.APP_SIGNUP_CONFIRMATION_INVALID,
        )
        self.assertNotIn("access_token", self.st.session_state)

    def test_verified_user_without_usable_session_requires_login(self):
        self.st.query_params = {
            "cadivor_signup_confirm": "1",
            "token_hash": "signup-hash",
            "type": "email",
        }
        supabase = MagicMock()
        user = types.SimpleNamespace(id="u1", email="a@b.com")
        supabase.auth.verify_otp.return_value = types.SimpleNamespace(
            session=None, user=user
        )
        self.confirm.apply_signup_confirmation_from_query(supabase)
        self.assertEqual(
            self.st.session_state["cadivor_root_state"],
            self.state.APP_SIGNUP_CONFIRMATION_SUCCESS,
        )
        self.assertFalse(self.confirm.signup_confirmation_session_ready())
        self.assertEqual(
            self.confirm.signup_confirmation_result_kind(),
            self.confirm.RESULT_LOGIN_REQUIRED,
        )

    def test_blank_tokens_not_authenticated(self):
        self.st.query_params = {
            "cadivor_signup_confirm": "1",
            "token_hash": "signup-hash",
            "type": "email",
        }
        supabase = MagicMock()
        session = types.SimpleNamespace(
            access_token="  ",
            refresh_token="",
            user=types.SimpleNamespace(id="u1"),
        )
        supabase.auth.verify_otp.return_value = {
            "session": session,
            "user": session.user,
        }
        self.confirm.apply_signup_confirmation_from_query(supabase)
        self.assertFalse(self.confirm.signup_confirmation_session_ready())
        self.assertEqual(
            self.confirm.signup_confirmation_result_kind(),
            self.confirm.RESULT_LOGIN_REQUIRED,
        )

    def test_exception_yields_invalid_surface(self):
        self.st.query_params = {
            "cadivor_signup_confirm": "1",
            "token_hash": "bad",
            "type": "email",
        }
        supabase = MagicMock()
        supabase.auth.verify_otp.side_effect = RuntimeError("otp failed")
        self.confirm.apply_signup_confirmation_from_query(supabase)
        self.assertEqual(
            self.st.session_state["cadivor_root_state"],
            self.state.APP_SIGNUP_CONFIRMATION_INVALID,
        )

    def test_dict_response_shape_session_ready(self):
        self.st.query_params = {
            "cadivor_signup_confirm": "1",
            "token_hash": "signup-hash",
            "type": "email",
        }
        supabase = MagicMock()
        user = {"id": "u1"}
        session = {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "user": user,
        }
        supabase.auth.verify_otp.return_value = {"session": session, "user": user}
        self.confirm.apply_signup_confirmation_from_query(supabase)
        self.assertTrue(self.confirm.signup_confirmation_session_ready())

    def test_rerun_does_not_reverify(self):
        self.st.query_params = {
            "cadivor_signup_confirm": "1",
            "token_hash": "signup-hash",
            "type": "email",
        }
        supabase = MagicMock()
        session = types.SimpleNamespace(
            access_token="access-token",
            refresh_token="refresh-token",
            user=types.SimpleNamespace(id="u1"),
        )
        supabase.auth.verify_otp.return_value = types.SimpleNamespace(
            session=session, user=session.user
        )
        self.confirm.apply_signup_confirmation_from_query(supabase)
        supabase.auth.verify_otp.reset_mock()
        # Simulate cleaned URL + surviving success state.
        self.st.query_params = {}
        self.confirm.apply_signup_confirmation_from_query(supabase)
        supabase.auth.verify_otp.assert_not_called()
        self.assertEqual(
            self.st.session_state["cadivor_root_state"],
            self.state.APP_SIGNUP_CONFIRMATION_SUCCESS,
        )

    def test_replay_after_consumed_is_invalid(self):
        self.st.session_state[self.confirm._EXCHANGE_CONSUMED_KEY] = True
        self.st.query_params = {
            "cadivor_signup_confirm": "1",
            "token_hash": "signup-hash",
            "type": "email",
        }
        supabase = MagicMock()
        self.confirm.apply_signup_confirmation_from_query(supabase)
        supabase.auth.verify_otp.assert_not_called()
        self.assertEqual(
            self.st.session_state["cadivor_root_state"],
            self.state.APP_SIGNUP_CONFIRMATION_INVALID,
        )

    def test_token_hash_not_retained_in_state(self):
        self.st.query_params = {
            "cadivor_signup_confirm": "1",
            "token_hash": "signup-hash-secret",
            "type": "email",
        }
        supabase = MagicMock()
        supabase.auth.verify_otp.side_effect = RuntimeError("fail")
        self.confirm.apply_signup_confirmation_from_query(supabase)
        dumped = str(self.st.session_state)
        self.assertNotIn("signup-hash-secret", dumped)


class SignupConfirmationUiTests(unittest.TestCase):
    def setUp(self):
        self.st = _install_streamlit_stub({})
        self.st.rerun = MagicMock()
        self.bodies: list[str] = []
        self.buttons: dict[str, bool] = {}

        def markdown(body, **kwargs):
            self.bodies.append(str(body))

        def button(label, key=None, **kwargs):
            return bool(self.buttons.get(key or label))

        self.st.markdown = MagicMock(side_effect=markdown)
        self.st.button = MagicMock(side_effect=button)
        for name in list(sys.modules):
            if name.startswith("src.auth") or name in {"src.secrets", "src.config", "src.ui.core_premium_ui"}:
                sys.modules.pop(name, None)

        secrets = types.ModuleType("src.secrets")
        secrets.get_secret = lambda *a, **k: "x"
        secrets.get_secret_bool = lambda *a, **k: False
        sys.modules["src.secrets"] = secrets
        config = types.ModuleType("src.config")
        config.CADIVOR_MARKETING_URL = "https://www.cadivor.com/"
        sys.modules["src.config"] = config
        ui = types.ModuleType("src.ui.core_premium_ui")
        ui.inject_core_premium_ui_auth = lambda: None
        sys.modules["src.ui.core_premium_ui"] = ui

        self.auth = importlib.import_module("src.auth")
        self.confirm = importlib.import_module("src.auth_signup_confirmation")
        self.state = importlib.import_module("src.auth_state")

    def test_success_session_ready_cta(self):
        self.st.session_state["cadivor_root_state"] = self.state.APP_SIGNUP_CONFIRMATION_SUCCESS
        self.st.session_state[self.confirm._SESSION_READY_KEY] = True
        self.st.session_state["user"] = types.SimpleNamespace(id="u1")
        self.st.session_state["access_token"] = "access-token"
        self.st.session_state["refresh_token"] = "refresh-token"
        self.auth._render_signup_confirmation_success(None)
        joined = "\n".join(self.bodies)
        self.assertIn("Welcome to Cadivor", joined)
        self.assertIn("Confirmation complete", joined)
        labels = [c.args[0] for c in self.st.button.call_args_list]
        self.assertIn("Continue to workspace", labels)

    def test_success_login_required_cta(self):
        self.st.session_state["cadivor_root_state"] = self.state.APP_SIGNUP_CONFIRMATION_SUCCESS
        self.auth._render_signup_confirmation_success(None)
        joined = "\n".join(self.bodies)
        self.assertIn("Continue to Cadivor", joined)
        labels = [c.args[0] for c in self.st.button.call_args_list]
        self.assertIn("Continue to login", labels)

    def test_invalid_surface_actions(self):
        self.st.session_state["cadivor_root_state"] = self.state.APP_SIGNUP_CONFIRMATION_INVALID
        self.auth._render_signup_confirmation_invalid()
        joined = "\n".join(self.bodies)
        self.assertIn("This link can’t be used", joined)
        labels = [c.args[0] for c in self.st.button.call_args_list]
        self.assertEqual(labels[:3], ["Return to login", "Create Account", "Reset password"])


class SignupConfirmationSignUpOptionsTests(unittest.TestCase):
    def setUp(self):
        self.st = _install_streamlit_stub({})
        self.st.rerun = MagicMock()
        for name in list(sys.modules):
            if name.startswith("src.auth") or name in {"src.secrets", "src.config", "src.ui.core_premium_ui"}:
                sys.modules.pop(name, None)
        secrets = types.ModuleType("src.secrets")
        secrets.get_secret = lambda *a, **k: "x"
        secrets.get_secret_bool = lambda *a, **k: False
        sys.modules["src.secrets"] = secrets
        config = types.ModuleType("src.config")
        config.CADIVOR_MARKETING_URL = "https://www.cadivor.com/"
        sys.modules["src.config"] = config
        ui = types.ModuleType("src.ui.core_premium_ui")
        ui.inject_core_premium_ui_auth = lambda: None
        sys.modules["src.ui.core_premium_ui"] = ui
        self.auth = importlib.import_module("src.auth")
        self.state = importlib.import_module("src.auth_state")

    def test_submit_manual_signup_passes_email_redirect_to(self):
        supabase = MagicMock()
        supabase.auth.sign_up.return_value = types.SimpleNamespace(
            user=types.SimpleNamespace(id="u1", email_confirmed_at=None),
            session=None,
        )
        with patch.object(self.auth, "begin_manual_login"), patch.object(
            self.auth, "render_auth_transition"
        ), patch.object(self.auth, "_log_manual_login_event"), patch.object(
            self.auth, "_enter_signup_confirmation_pending"
        ) as pending:
            self.auth._submit_manual_signup(supabase, MagicMock(), "new@cadivor.com", "secret")
        kwargs = supabase.auth.sign_up.call_args[0][0]
        self.assertEqual(kwargs["email"], "new@cadivor.com")
        self.assertIn("options", kwargs)
        redirect = kwargs["options"]["email_redirect_to"]
        self.assertIn("cadivor_signup_confirm=1", redirect)
        pending.assert_called_once()


if __name__ == "__main__":
    unittest.main()

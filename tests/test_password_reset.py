"""Sprint 74.1.1 — password recovery PKCE token-safety tests."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.test_auth_cookie_read_bridge import _install_streamlit_stub


class PasswordResetTests(unittest.TestCase):
    def setUp(self):
        self.st = _install_streamlit_stub({})
        self.st.rerun = MagicMock()
        self.st.error = MagicMock()
        self.st.success = MagicMock()

    def _load_auth_recovery(self):
        sys.modules.pop("src.auth_recovery", None)
        return importlib.import_module("src.auth_recovery")

    def test_request_password_reset_returns_generic_message(self):
        recovery = self._load_auth_recovery()
        supabase = MagicMock()
        message = recovery.request_password_reset_email(supabase, "user@example.com")
        self.assertIn("If an account exists", message)
        supabase.auth.reset_password_for_email.assert_called_once()
        redirect_to = supabase.auth.reset_password_for_email.call_args[0][1]["redirect_to"]
        self.assertIn("cadivor_recovery=1", redirect_to)

    def test_request_password_reset_does_not_reveal_missing_email(self):
        recovery = self._load_auth_recovery()
        supabase = MagicMock()
        message = recovery.request_password_reset_email(supabase, "")
        self.assertIn("Enter the email address", message)
        supabase.auth.reset_password_for_email.assert_not_called()

    def test_password_mismatch_is_rejected(self):
        recovery = self._load_auth_recovery()
        self.st.session_state["cadivor_password_recovery_active"] = True
        supabase = MagicMock()
        success, message = recovery.complete_password_recovery(
            supabase,
            "password123",
            "different123",
        )
        self.assertFalse(success)
        self.assertIn("do not match", message.lower())
        supabase.auth.update_user.assert_not_called()

    def test_successful_password_update_clears_recovery_state(self):
        recovery = self._load_auth_recovery()
        self.st.session_state["cadivor_password_recovery_active"] = True
        self.st.session_state["user"] = types.SimpleNamespace(id="user-1")
        self.st.session_state["access_token"] = "access"
        self.st.session_state["refresh_token"] = "refresh"
        supabase = MagicMock()
        success, message = recovery.complete_password_recovery(
            supabase,
            "newpassword123",
            "newpassword123",
        )
        self.assertTrue(success)
        self.assertIn("updated", message.lower())
        self.assertNotIn("cadivor_password_recovery_active", self.st.session_state)
        self.assertNotIn("access_token", self.st.session_state)
        supabase.auth.update_user.assert_called_once_with({"password": "newpassword123"})

    def test_invalid_recovery_session_is_rejected(self):
        recovery = self._load_auth_recovery()
        supabase = MagicMock()
        success, message = recovery.complete_password_recovery(
            supabase,
            "newpassword123",
            "newpassword123",
        )
        self.assertFalse(success)
        self.assertIn("not active", message.lower())

    def test_pkce_token_hash_is_verified_when_marker_present(self):
        recovery = self._load_auth_recovery()
        self.st.query_params = {
            "token_hash": "recovery-token-hash",
            "type": "recovery",
            "cadivor_recovery": "1",
        }
        supabase = MagicMock()
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
        supabase.auth.verify_otp.assert_called_once_with(
            {"token_hash": "recovery-token-hash", "type": "recovery"}
        )
        self.assertTrue(recovery.password_recovery_active())
        self.assertNotIn("token_hash", self.st.query_params)
        self.assertNotIn("cadivor_recovery", self.st.query_params)

    def test_token_hash_without_recovery_marker_is_ignored(self):
        recovery = self._load_auth_recovery()
        self.st.query_params = {
            "token_hash": "signup-token-hash",
            "type": "recovery",
        }
        supabase = MagicMock()
        recovery.apply_password_recovery_from_query(supabase)
        supabase.auth.verify_otp.assert_not_called()
        self.assertFalse(recovery.password_recovery_active())

    def test_recovery_state_survives_streamlit_rerun(self):
        recovery = self._load_auth_recovery()
        self.st.session_state["cadivor_password_recovery_active"] = True
        self.st.session_state["cadivor_root_state"] = "password_recovery"
        self.st.session_state["access_token"] = "access-token"
        self.st.session_state["refresh_token"] = "refresh-token"
        self.st.session_state["user"] = types.SimpleNamespace(id="user-1")

        recovery.apply_password_recovery_from_query(MagicMock())

        self.assertTrue(recovery.password_recovery_active())
        self.assertEqual(self.st.session_state["cadivor_root_state"], "password_recovery")

    def test_pkce_recovery_code_is_exchanged_when_marker_present(self):
        recovery = self._load_auth_recovery()
        self.st.query_params = {
            "code": "auth-code-123",
            "cadivor_recovery": "1",
        }
        supabase = MagicMock()
        session = types.SimpleNamespace(
            access_token="access-token",
            refresh_token="refresh-token",
            user=types.SimpleNamespace(id="user-1", email="user@example.com"),
        )
        supabase.auth.exchange_code_for_session.return_value = types.SimpleNamespace(
            session=session,
            user=session.user,
        )
        recovery.apply_password_recovery_from_query(supabase)
        supabase.auth.exchange_code_for_session.assert_called_once_with(
            {"auth_code": "auth-code-123"}
        )
        self.assertTrue(recovery.password_recovery_active())
        self.assertNotIn("code", self.st.query_params)

    def test_pkce_code_without_recovery_marker_is_ignored(self):
        recovery = self._load_auth_recovery()
        self.st.query_params = {"code": "signup-code-123"}
        supabase = MagicMock()
        recovery.apply_password_recovery_from_query(supabase)
        supabase.auth.exchange_code_for_session.assert_not_called()
        self.assertFalse(recovery.password_recovery_active())

    def test_invalid_recovery_token_hash_sets_safe_error(self):
        recovery = self._load_auth_recovery()
        self.st.query_params = {
            "token_hash": "bad",
            "type": "recovery",
            "cadivor_recovery": "1",
        }
        supabase = MagicMock()
        supabase.auth.verify_otp.side_effect = RuntimeError("invalid")
        recovery.apply_password_recovery_from_query(supabase)
        self.assertFalse(recovery.password_recovery_active())
        self.assertIn(
            "invalid or has expired",
            self.st.session_state[recovery._RECOVERY_ERROR_KEY].lower(),
        )

    def test_recovery_exchange_is_single_use(self):
        recovery = self._load_auth_recovery()
        self.st.query_params = {
            "token_hash": "recovery-token-hash",
            "type": "recovery",
            "cadivor_recovery": "1",
        }
        supabase = MagicMock()
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
        self.assertTrue(recovery.password_recovery_active())
        supabase.auth.verify_otp.reset_mock()

        # Replay after the exchange was consumed but before recovery UI completes
        # should not re-call verify_otp while recovery remains active.
        self.st.query_params = {
            "token_hash": "recovery-token-hash",
            "type": "recovery",
            "cadivor_recovery": "1",
        }
        recovery.apply_password_recovery_from_query(supabase)
        supabase.auth.verify_otp.assert_not_called()
        self.assertTrue(recovery.password_recovery_active())

        # Replay after recovery state was cleared should fail safely.
        self.st.session_state.pop("cadivor_password_recovery_active", None)
        self.st.query_params = {
            "token_hash": "recovery-token-hash",
            "type": "recovery",
            "cadivor_recovery": "1",
        }
        recovery.apply_password_recovery_from_query(supabase)
        supabase.auth.verify_otp.assert_not_called()
        self.assertIn(
            "already been used",
            self.st.session_state[recovery._RECOVERY_ERROR_KEY].lower(),
        )

    def test_recovery_query_cleanup_after_successful_exchange(self):
        recovery = self._load_auth_recovery()
        self.st.query_params = {
            "token_hash": "recovery-token-hash",
            "type": "recovery",
            "cadivor_recovery": "1",
        }
        supabase = MagicMock()
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
        self.assertNotIn("token_hash", self.st.query_params)
        self.assertNotIn("type", self.st.query_params)
        self.assertNotIn("cadivor_recovery", self.st.query_params)

    def test_implicit_access_token_query_params_are_not_supported(self):
        recovery = self._load_auth_recovery()
        self.st.query_params = {
            "type": "recovery",
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "cadivor_recovery": "1",
        }
        supabase = MagicMock()
        recovery.apply_password_recovery_from_query(supabase)
        supabase.auth.set_session.assert_not_called()
        self.assertFalse(recovery.password_recovery_active())

    def test_diagnostics_do_not_log_secrets(self):
        recovery = self._load_auth_recovery()
        logs = list(self.st.session_state.get("cadivor_auth_debug_log") or [])
        recovery.request_password_reset_email(MagicMock(), "user@example.com")
        recovery.complete_password_recovery(MagicMock(), "secret123", "secret123")
        joined = str(self.st.session_state.get("cadivor_auth_debug_log", logs))
        self.assertNotIn("secret123", joined)
        self.assertNotIn("access-token", joined)


class PasswordRecoveryBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.st = _install_streamlit_stub({})
        self.st.cache_resource = lambda **kwargs: (lambda fn: fn)
        self.st.stop = MagicMock(side_effect=SystemExit)

    def test_bootstrap_renders_recovery_ui_instead_of_login(self):
        sys.modules.pop("src.auth_bootstrap", None)
        sys.modules.pop("src.auth_recovery", None)
        bootstrap = importlib.import_module("src.auth_bootstrap")

        self.st.session_state["cadivor_password_recovery_active"] = True
        self.st.session_state["cadivor_root_state"] = "password_recovery"

        with patch.object(bootstrap, "show_auth_ui") as show_auth_ui, patch.object(
            bootstrap, "get_supabase_client", return_value=MagicMock()
        ), patch.object(bootstrap, "apply_auth_intent_from_query"), patch.object(
            bootstrap, "log_startup_phase"
        ), patch.object(
            bootstrap, "log_auth_restore"
        ), patch(
            "src.auth_diagnostics.log_auth_correlation"
        ), patch(
            "src.auth_diagnostics.log_auth_bounce"
        ):
            with self.assertRaises(SystemExit):
                bootstrap.ensure_authenticated_or_stop()

        show_auth_ui.assert_called_once()

    def test_supabase_client_uses_pkce_flow(self):
        sys.modules.pop("src.auth_bootstrap", None)
        bootstrap = importlib.import_module("src.auth_bootstrap")
        source = Path(bootstrap.__file__).read_text(encoding="utf-8")
        self.assertIn("SyncClientOptions", source)
        self.assertIn('flow_type="pkce"', source)
        with patch.object(bootstrap, "get_secret", side_effect=lambda key, **kwargs: {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "public-anon-key",
        }[key]), patch("supabase.lib.client_options.SyncClientOptions") as options_cls, patch(
            "supabase_auth.SyncMemoryStorage"
        ), patch.object(bootstrap, "create_client") as create_client:
            options_cls.return_value = types.SimpleNamespace(flow_type="pkce")
            bootstrap.get_supabase_client()
        create_client.assert_called_once()
        self.assertEqual(create_client.call_args.kwargs["options"].flow_type, "pkce")


class PasswordRecoverySurfaceTests(unittest.TestCase):
    AUTH_PATH = Path(__file__).resolve().parents[1] / "src" / "auth.py"

    def setUp(self):
        self.st = _install_streamlit_stub({})
        sys.modules.pop("src.auth", None)
        sys.modules.pop("src.auth_recovery", None)
        self.auth_source = self.AUTH_PATH.read_text(encoding="utf-8")

    def test_recovery_surfaces_use_auth_card_brand_shell(self):
        self.assertIn("_render_auth_card_brand", self.auth_source)
        self.assertIn('eyebrow="Secure account recovery"', self.auth_source)
        self.assertIn("auth-card-header", self.auth_source)
        self.assertIn("auth-card-logo", self.auth_source)

    def test_set_new_password_surface_copy_and_controls(self):
        self.assertIn("Choose a new password", self.auth_source)
        self.assertIn(
            "Your recovery link is active. Choose a secure new password to restore access to your Cadivor workspace.",
            self.auth_source,
        )
        self.assertIn('st.text_input("New password", type="password"', self.auth_source)
        self.assertIn('st.text_input("Confirm password", type="password"', self.auth_source)
        self.assertIn('st.form_submit_button("Update password"', self.auth_source)
        self.assertIn("auth-trust-note", self.auth_source)

    def test_reset_password_request_surface_copy(self):
        self.assertIn("Reset your password", self.auth_source)
        self.assertIn('st.form_submit_button("Send recovery email"', self.auth_source)
        self.assertIn('type="secondary"', self.auth_source)

    def test_recovery_active_renders_set_password_not_login(self):
        sys.modules.pop("src.auth", None)
        auth = importlib.import_module("src.auth")

        self.st.session_state["cadivor_password_recovery_active"] = True
        self.st.session_state["cadivor_root_state"] = "password_recovery"

        with patch.object(auth, "_auth_css"), patch.object(auth, "inject_core_premium_ui_auth"), patch.object(
            auth, "_render_password_recovery_form"
        ) as recovery_form, patch.object(auth, "_render_auth_page") as login_form:
            auth.show_auth_ui(MagicMock(), None)

        recovery_form.assert_called_once()
        login_form.assert_not_called()

    def test_normal_login_does_not_render_recovery_controls(self):
        sys.modules.pop("src.auth", None)
        auth = importlib.import_module("src.auth")
        self.st.session_state["cadivor_root_state"] = "login"
        self.st.session_state.pop("cadivor_password_recovery_active", None)

        with patch.object(auth, "_auth_css"), patch.object(auth, "inject_core_premium_ui_auth"), patch.object(
            auth, "_render_password_recovery_form"
        ) as recovery_form, patch.object(auth, "_render_auth_page") as login_form, patch.object(
            auth, "_auth_recovery"
        ) as auth_recovery_factory:
            auth_recovery_factory.return_value.password_recovery_active.return_value = False
            auth.show_auth_ui(MagicMock(), None)

        login_form.assert_called_once()
        recovery_form.assert_not_called()


class LoginBrandRenderTests(unittest.TestCase):
    def _assert_brand_markup_safe_for_html_render(self, body: str) -> None:
        lines = body.splitlines()
        non_empty = [line for line in lines if line.strip()]
        self.assertTrue(non_empty, "brand markup must not be empty")
        self.assertEqual(
            len(non_empty[0]) - len(non_empty[0].lstrip(" ")),
            0,
            "brand markup must not begin with markdown code-block indentation",
        )
        for line in lines:
            if line.strip():
                continue
            self.assertEqual(
                line,
                "",
                "brand markup must not contain whitespace-only indented lines",
            )
        self.assertRegex(body, r'^<div class="auth-card-header">', body[:80])
        self.assertIn('<a href="', body)
        self.assertEqual(body.count("<div"), body.count("</div>"))
        self.assertEqual(body.count("<a"), body.count("</a>"))

    def setUp(self):
        self.st = _install_streamlit_stub({})
        self.st.markdown = MagicMock()
        sys.modules.pop("src.auth", None)

    def test_deployed_login_brand_regression_pattern_is_rejected(self):
        deployed = f"""
        <div class="auth-card-header">
            
            <a href="https://www.cadivor.com/" target="_self" class="auth-card-brand-link">
                <div class="auth-card-logo">C</div>
            </a>
        </div>
        """
        with self.assertRaises(AssertionError):
            self._assert_brand_markup_safe_for_html_render(deployed)

    def test_login_brand_renders_html_not_literal_markup(self):
        auth = importlib.import_module("src.auth")
        auth._render_auth_card_brand(
            context_sub="Engineering intelligence for modern electronics teams.",
        )

        self.st.markdown.assert_called_once()
        body = self.st.markdown.call_args.args[0]
        kwargs = self.st.markdown.call_args.kwargs
        self.assertTrue(kwargs.get("unsafe_allow_html"))
        self._assert_brand_markup_safe_for_html_render(body)
        self.assertIn("auth-card-brand-link", body)
        self.assertIn("Engineering intelligence for modern electronics teams.", body)
        self.assertNotIn("\n            <a href", body)

    def test_recovery_brand_renders_with_eyebrow_and_html_flags(self):
        auth = importlib.import_module("src.auth")
        auth._render_auth_card_brand(
            eyebrow="Secure account recovery",
            context_sub="Choose a secure new password to restore access to your Cadivor workspace.",
        )

        self.st.markdown.assert_called_once()
        body = self.st.markdown.call_args.args[0]
        kwargs = self.st.markdown.call_args.kwargs
        self.assertTrue(kwargs.get("unsafe_allow_html"))
        self._assert_brand_markup_safe_for_html_render(body)
        self.assertIn("auth-recovery-eyebrow", body)
        self.assertIn("Secure account recovery", body)

    def test_render_auth_page_calls_login_brand_helper(self):
        auth = importlib.import_module("src.auth")
        self.st.form = MagicMock()
        self.st.form.return_value.__enter__ = MagicMock(return_value=None)
        self.st.form.return_value.__exit__ = MagicMock(return_value=False)
        self.st.radio = MagicMock(return_value="Login")
        self.st.text_input = MagicMock(return_value="")
        self.st.form_submit_button = MagicMock(return_value=False)
        self.st.button = MagicMock(return_value=False)
        with patch.object(auth, "_render_auth_card_brand") as brand, patch.object(
            auth, "_render_back_to_marketing_link"
        ):
            auth._render_auth_page(MagicMock(), MagicMock(), "Login")

        brand.assert_called_once_with(
            context_sub="Engineering intelligence for modern electronics teams.",
        )


class RecoveryBrandCenteringTests(unittest.TestCase):
    AUTH_PATH = Path(__file__).resolve().parents[1] / "src" / "auth.py"

    def setUp(self):
        self.st = _install_streamlit_stub({})
        self.st.markdown = MagicMock()
        sys.modules.pop("src.auth", None)
        self.auth_source = self.AUTH_PATH.read_text(encoding="utf-8")

    def _render_brand(self, *, eyebrow: str = "", context_sub: str = "Context copy."):
        auth = importlib.import_module("src.auth")
        auth._render_auth_card_brand(eyebrow=eyebrow, context_sub=context_sub)
        return self.st.markdown.call_args.args[0]

    def test_auth_card_header_uses_independent_centering_layout(self):
        self.assertIn(".auth-card-header{display:flex;flex-direction:column;align-items:center;", self.auth_source)
        self.assertIn(".auth-card-brand-link{display:block;", self.auth_source)

    def test_login_brand_is_block_wrapped_without_eyebrow(self):
        body = self._render_brand(
            context_sub="Engineering intelligence for modern electronics teams.",
        )
        self.assertRegex(
            body,
            r'<div class="auth-card-header">\s*<a href="[^"]+" target="_self" class="auth-card-brand-link">',
        )
        self.assertNotIn("auth-recovery-eyebrow", body)
        self.assertRegex(body, r'</a>\s*<div class="auth-card-sub">')

    def test_recovery_eyebrow_is_separate_row_after_brand_link(self):
        body = self._render_brand(
            eyebrow="Secure account recovery",
            context_sub="Choose a secure new password to restore access to your Cadivor workspace.",
        )
        self.assertRegex(
            body,
            r'</a>\s*<div class="auth-recovery-eyebrow">Secure account recovery</div>\s*<div class="auth-card-sub">',
        )
        self.assertNotRegex(
            body,
            r'<div class="auth-recovery-eyebrow">[^<]+</div><a href=',
        )
        self.assertNotRegex(
            body,
            r'auth-recovery-eyebrow">[^<]+</div><a href=',
        )

    def test_recovery_context_subtitle_is_separate_centered_element(self):
        body = self._render_brand(
            eyebrow="Secure account recovery",
            context_sub="We'll send recovery instructions to the email associated with your workspace.",
        )
        self.assertIn(
            '<div class="auth-card-sub">We\'ll send recovery instructions to the email associated with your workspace.</div>',
            body,
        )
        self.assertRegex(body, r'<div class="auth-recovery-eyebrow">[^<]+</div>\s*<div class="auth-card-sub">')


if __name__ == "__main__":
    unittest.main()

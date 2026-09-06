"""Login handoff UX regressions: bounded stages, no indefinite SIGNING_IN."""
from __future__ import annotations

import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.test_manual_login_atomic import ManualLoginAtomicTests


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src" / "components" / "atomic_login" / "index.html").read_text(
    encoding="utf-8"
)
AUTH = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
IDLE = (ROOT / "src" / "auth_idle_recovery.py").read_text(encoding="utf-8")


class LoginHandoffUxTests(unittest.TestCase):
    def setUp(self):
        self.helper = ManualLoginAtomicTests(
            methodName="test_login_submit_calls_sign_in_in_same_script_run"
        )
        self.helper.setUp()

    def tearDown(self):
        self.helper.doCleanups()

    def _load_auth(self, session_state=None):
        return self.helper._load_auth(session_state)

    def test_one_click_submit_consumes_request_id_once(self):
        self.assertIn("request_id != consumed_id", AUTH)
        self.assertIn('AUTH_ATOMIC_LOGIN_CONSUMED_KEY] = request_id', AUTH)
        self.assertIn("submitted = true", HTML)
        self.assertIn("if (submitted || button.disabled) return", HTML)

    def test_enter_submit_uses_native_form_submit(self):
        self.assertIn('<form id="login"', HTML)
        self.assertIn('form.addEventListener("submit"', HTML)
        self.assertIn('type="submit"', HTML)
        self.assertIn("event.preventDefault()", HTML)

    def test_in_flight_duplicate_suppression_disables_controls(self):
        self.assertIn("button.disabled = Boolean(isBusy) || submitted", HTML)
        self.assertIn("email.disabled = Boolean(isBusy)", HTML)
        self.assertIn("password.disabled = Boolean(isBusy)", HTML)
        self.assertIn("disabled=login_in_flight", AUTH)
        self.assertIn("login_in_flight = manual_login_in_flight()", AUTH)

    def test_successful_one_click_leaves_signing_in_and_starts_initializing(self):
        st, auth, _auth_state = self._load_auth()
        shells = []

        with patch(
            "src.auth_bootstrap.render_startup_loading_shell",
            side_effect=lambda message="": shells.append(str(message)),
        ):
            auth._submit_manual_login(
                MagicMock(
                    auth=MagicMock(
                        sign_in_with_password=MagicMock(
                            return_value=types.SimpleNamespace(
                                user=types.SimpleNamespace(id="u1"),
                                session=types.SimpleNamespace(
                                    access_token="access",
                                    refresh_token="refresh",
                                ),
                            )
                        )
                    )
                ),
                MagicMock(),
                "user@example.com",
                "password-value",
            )

        self.assertTrue(any("Signing you in" in m for m in shells))
        self.assertEqual(st.session_state["cadivor_root_state"], auth.APP_AUTHENTICATED)
        self.assertNotEqual(st.session_state["cadivor_root_state"], auth.APP_SIGNING_IN)
        self.assertTrue(st.session_state.get("cadivor_login_handoff_active"))
        self.assertEqual(
            st.session_state.get("cadivor_login_handoff_stage"),
            "initializing",
        )
        # Same-run continue: success must not st.rerun() into a blank gap.
        st.rerun.assert_not_called()

    def test_signing_in_cannot_remain_without_in_flight_work(self):
        """Stale APP_SIGNING_IN must restore Login — never park forever."""
        self.assertIn("if state == APP_SIGNING_IN:", AUTH)
        block = AUTH[
            AUTH.index("if state == APP_SIGNING_IN:") : AUTH.index(
                "if state in (APP_LOGIN, APP_SIGNUP):"
            )
        ]
        self.assertIn("manual_login_in_flight()", block)
        self.assertIn("fail_login_handoff", block)
        self.assertIn("LOGIN_HANDOFF_TIMEOUT", BOOTSTRAP)
        # Logout may empty; authenticated path must mount progress instead.
        self.assertIn("mount_auth_progress_surface(auth_surface_host)", BOOTSTRAP)
        auth_path = BOOTSTRAP[
            BOOTSTRAP.find("if auth_status != AUTH_AUTHENTICATED:") : BOOTSTRAP.find(
                'log_startup_phase("auth_boundary_passed")'
            )
        ]
        self.assertNotIn("auth_surface_host.empty()", auth_path)

    def test_handoff_shell_is_stage_and_time_bounded(self):
        self.assertIn("LOGIN_HANDOFF_STAGE_AUTHENTICATING", BOOTSTRAP)
        self.assertIn("LOGIN_HANDOFF_STAGE_INITIALIZING", BOOTSTRAP)
        self.assertIn("LOGIN_HANDOFF_TIMEOUT_SECONDS", BOOTSTRAP)
        self.assertIn("login_handoff_timed_out()", BOOTSTRAP)
        self.assertIn("fail_login_handoff(", BOOTSTRAP)
        self.assertIn("clear_login_handoff()", RUNTIME)
        self.assertIn("clear_login_handoff()", IDLE)

    def test_failed_login_returns_form_with_error_and_email(self):
        st, auth, _auth_state = self._load_auth()
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.side_effect = RuntimeError("denied")

        auth._submit_manual_login(
            supabase, MagicMock(), "keepme@example.com", "password-value"
        )

        self.assertEqual(st.session_state["cadivor_root_state"], auth.APP_LOGIN)
        self.assertEqual(
            st.session_state["cadivor_auth_error"],
            auth.MANUAL_LOGIN_FAILURE_MESSAGE,
        )
        self.assertEqual(
            st.session_state[auth.ATOMIC_LOGIN_ERROR_KEY],
            "Email or password is incorrect. Please try again.",
        )
        self.assertGreaterEqual(
            int(st.session_state.get(auth.ATOMIC_LOGIN_ERROR_EPOCH_KEY) or 0),
            1,
        )
        self.assertEqual(
            st.session_state["cadivor_login_email_draft"],
            "keepme@example.com",
        )
        self.assertFalse(st.session_state.get("cadivor_login_handoff_active", False))
        self.assertFalse(st.session_state.get("cadivor_manual_login_in_progress", False))
        self.assertIn("prefill_email=draft_email", AUTH)
        self.assertIn("error_message=", AUTH)
        self.assertIn("error_epoch=", AUTH)
        self.assertIn("args.prefill_email", HTML)
        self.assertIn("args.error_message", HTML)
        self.assertIn("applyServerError", HTML)
        self.assertIn('password.value = ""', HTML)
        self.assertIn("password.focus()", HTML)
        # Error must be owned by the atomic Login surface, not only st.error.
        self.assertIn("ATOMIC_LOGIN_ERROR_KEY", AUTH)
        self.assertNotIn("st.error(error)", AUTH[AUTH.index("if state in (APP_LOGIN, APP_SIGNUP):"):AUTH.index("if state == APP_PASSWORD_RESET:")])

    def test_invalid_password_error_reaches_atomic_login_args(self):
        """User-visible invalid-password copy must be passed into the iframe."""
        st, auth, _auth_state = self._load_auth()
        captured = {}

        def fake_render_atomic_login(**kwargs):
            captured.update(kwargs)
            return None

        st.radio = MagicMock(return_value=auth.AUTH_MODE_LOGIN)
        st.button = MagicMock(return_value=False)
        st.markdown = MagicMock()
        st.session_state[auth.ATOMIC_LOGIN_ERROR_KEY] = auth.MANUAL_LOGIN_FAILURE_MESSAGE
        st.session_state[auth.ATOMIC_LOGIN_ERROR_EPOCH_KEY] = 3
        st.session_state["cadivor_login_email_draft"] = "keepme@example.com"
        st.session_state["cadivor_root_state"] = auth.APP_LOGIN

        with patch.object(auth, "render_atomic_login", side_effect=fake_render_atomic_login):
            auth._render_auth_page(
                MagicMock(),
                MagicMock(),
                auth.AUTH_MODE_LOGIN,
                auth_error=auth.MANUAL_LOGIN_FAILURE_MESSAGE,
            )

        self.assertEqual(
            captured.get("error_message"),
            "Email or password is incorrect. Please try again.",
        )
        self.assertEqual(captured.get("prefill_email"), "keepme@example.com")
        self.assertEqual(captured.get("error_epoch"), 3)
        self.assertFalse(captured.get("disabled"))
        self.assertEqual(captured.get("submit_label"), "Login")

    def test_success_plus_profile_init_clears_signing_in_and_handoff(self):
        """Credentials + profile success must not leave APP_SIGNING_IN forever."""
        from tests.test_authenticated_startup_shell import (
            _install_bootstrap_deps,
            _install_streamlit_stub,
        )

        st = _install_streamlit_stub(
            {
                "cadivor_login_handoff_active": True,
                "cadivor_login_handoff_stage": "initializing",
                "cadivor_login_handoff_started_at": 1000.0,
                "cadivor_root_state": "authenticated",
                "cadivor_auth_status": "authenticated",
            }
        )
        bootstrap, restore_secrets = _install_bootstrap_deps(st)
        self.addCleanup(restore_secrets)

        with patch("time.monotonic", return_value=1001.0):
            self.assertTrue(bootstrap.should_render_authenticated_startup_shell())
            bootstrap.clear_login_handoff()
            self.assertFalse(bootstrap.should_render_authenticated_startup_shell())
        self.assertNotIn("cadivor_login_handoff_active", st.session_state)
        self.assertNotEqual(st.session_state.get("cadivor_root_state"), "signing_in")

    def test_handoff_timeout_during_authenticating_restores_login(self):
        from tests.test_authenticated_startup_shell import (
            _install_bootstrap_deps,
            _install_streamlit_stub,
        )

        st = _install_streamlit_stub(
            {
                "cadivor_login_handoff_active": True,
                "cadivor_login_handoff_stage": "authenticating",
                "cadivor_login_handoff_started_at": 1000.0,
                "cadivor_login_email_draft": "keepme@example.com",
                "cadivor_root_state": "signing_in",
                "cadivor_manual_login_in_progress": True,
            }
        )
        bootstrap, restore_secrets = _install_bootstrap_deps(st)
        self.addCleanup(restore_secrets)

        with patch("time.monotonic", return_value=1000.0 + bootstrap.LOGIN_HANDOFF_TIMEOUT_SECONDS + 1.0):
            self.assertTrue(bootstrap.login_handoff_timed_out())
            bootstrap.fail_login_handoff(
                message=bootstrap.LOGIN_HANDOFF_TIMEOUT_MESSAGE,
                email="keepme@example.com",
            )

        self.assertEqual(st.session_state["cadivor_root_state"], "login")
        self.assertEqual(
            st.session_state["cadivor_auth_error"],
            bootstrap.LOGIN_HANDOFF_TIMEOUT_MESSAGE,
        )
        self.assertEqual(
            st.session_state["cadivor_login_email_draft"],
            "keepme@example.com",
        )
        self.assertFalse(st.session_state.get("cadivor_login_handoff_active", False))
        self.assertFalse(st.session_state.get("cadivor_manual_login_in_progress", False))

    def test_transient_profile_failure_clears_handoff_before_retry_ui(self):
        self.assertIn("clear_login_handoff()", IDLE)
        # clear must precede st.error in retryable profile path
        retry_fn = IDLE[
            IDLE.index("def render_retryable_profile_error") : IDLE.index(
                "def load_workspace_profile"
            )
        ]
        self.assertLess(
            retry_fn.index("clear_login_handoff()"),
            retry_fn.index("st.error(message)"),
        )


if __name__ == "__main__":
    unittest.main()

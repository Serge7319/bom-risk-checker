"""Auth handoff continuity: one progress surface, never blank between login and workspace."""
from __future__ import annotations

import re
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.test_authenticated_startup_shell import (
    _install_bootstrap_deps,
    _install_streamlit_stub,
)
from tests.test_manual_login_atomic import ManualLoginAtomicTests

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
AUTH = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
STREAMLIT_APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
IDLE = (ROOT / "src" / "auth_idle_recovery.py").read_text(encoding="utf-8")
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")


class AuthHandoffContinuitySourceContracts(unittest.TestCase):
    """Prove no path clears the auth host before the next surface is mounted."""

    def test_authenticated_fallthrough_never_empties_host(self):
        auth_path = BOOTSTRAP[
            BOOTSTRAP.find("if auth_status != AUTH_AUTHENTICATED:") : BOOTSTRAP.find(
                'log_startup_phase("auth_boundary_passed")'
            )
        ]
        self.assertIn("mount_auth_progress_surface(auth_surface_host)", auth_path)
        self.assertNotIn("auth_surface_host.empty()", auth_path)
        self.assertIn("continue_authenticated", auth_path)

    def test_progress_mount_is_authoritative_owner(self):
        self.assertIn("def mount_auth_progress_surface(", BOOTSTRAP)
        self.assertIn("AUTH_PROGRESS_MOUNTED_KEY", BOOTSTRAP)
        self.assertIn("auth_progress_surface_mounted()", STREAMLIT_APP)
        # Entrypoint must not paint a second shell when host already mounted.
        self.assertIn(
            "should_render_authenticated_startup_shell() and not auth_progress_surface_mounted()",
            STREAMLIT_APP,
        )

    def test_success_login_does_not_rerun(self):
        submit = AUTH[
            AUTH.find("def _submit_manual_login") : AUTH.find(
                "def _signup_response_get"
            )
        ]
        self.assertIn("Do not st.rerun() on success", submit)
        # Failure helpers may mention rerun; success tail must not call it.
        success_tail = submit[submit.find("manual_login_session_committed") :]
        self.assertNotRegex(success_tail, r"(?m)^\s*st\.rerun\(\)")
        self.assertIn("render_startup_loading_shell(login_handoff_message())", submit)

    def test_handoff_active_skips_hydration_rerun_loops(self):
        self.assertIn(
            "if not manual_login_in_flight() and not login_handoff_active():",
            BOOTSTRAP,
        )
        self.assertIn("and not login_handoff_active()", BOOTSTRAP)

    def test_begin_login_handoff_is_idempotent(self):
        block = BOOTSTRAP[
            BOOTSTRAP.find("def begin_login_handoff") : BOOTSTRAP.find(
                "def advance_login_handoff"
            )
        ]
        self.assertIn("if login_handoff_active():", block)
        self.assertIn("One handoff only", block)

    def test_expired_session_recovery_never_blanks_via_empty_host(self):
        self.assertIn("enter_session_expired_recovery", IDLE)
        self.assertIn("SESSION_EXPIRED_NOTICE", IDLE)
        self.assertIn("clear_login_handoff()", IDLE)
        # Recovery reruns into Login form — not an empty auth host clear.
        self.assertNotIn("auth_surface_host.empty()", IDLE)

    def test_workspace_ready_clears_single_handoff(self):
        self.assertIn("clear_login_handoff()", RUNTIME)


class AuthHandoffContinuitySequenceTests(unittest.TestCase):
    def setUp(self):
        self.helper = ManualLoginAtomicTests(
            methodName="test_login_submit_calls_sign_in_in_same_script_run"
        )
        self.helper.setUp()

    def tearDown(self):
        self.helper.doCleanups()

    def _load_auth(self):
        return self.helper._load_auth()

    def test_1_unauthenticated_renders_login_form_path(self):
        self.assertIn("show_auth_ui(supabase, cookie_manager)", BOOTSTRAP)
        self.assertIn("render_atomic_login(", AUTH)
        st, auth, _ = self._load_auth()
        st.button = MagicMock(return_value=False)
        st.session_state["cadivor_root_state"] = auth.APP_LOGIN
        st.radio = MagicMock(return_value=auth.AUTH_MODE_LOGIN)
        with patch.object(auth, "render_atomic_login", return_value=None) as atomic:
            auth._render_auth_page(MagicMock(), MagicMock(), auth.AUTH_MODE_LOGIN)
        atomic.assert_called_once()
        self.assertEqual(atomic.call_args.kwargs.get("submit_label"), "Login")

    def test_2_valid_submit_one_progress_surface_no_blank_empty(self):
        st, auth, _ = self._load_auth()
        shells: list[str] = []
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
        self.assertEqual(len(shells), 1)
        self.assertIn("Signing you in", shells[0])
        st.rerun.assert_not_called()
        self.assertTrue(st.session_state.get("cadivor_login_handoff_active"))

    def test_3_same_run_continue_mounts_progress_then_workspace_ready(self):
        st = _install_streamlit_stub(
            {
                "cadivor_auth_status": "authenticated",
                "cadivor_login_handoff_active": True,
                "cadivor_login_handoff_stage": "initializing",
                "cadivor_login_handoff_started_at": 1000.0,
                "access_token": "a",
                "refresh_token": "r",
                "user": object(),
            }
        )
        bootstrap, restore = _install_bootstrap_deps(st)
        self.addCleanup(restore)

        mounts: list[str] = []
        host = MagicMock()
        container = MagicMock()
        host.container.return_value.__enter__ = MagicMock(return_value=container)
        host.container.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(
                bootstrap,
                "render_startup_loading_shell",
                side_effect=lambda message="": mounts.append(str(message)),
            ),
            patch("time.monotonic", return_value=1001.0),
        ):
            bootstrap.mount_auth_progress_surface(host)
            self.assertTrue(bootstrap.auth_progress_surface_mounted())
            self.assertFalse(bootstrap.should_render_authenticated_startup_shell())
            bootstrap.clear_login_handoff()

        self.assertEqual(len(mounts), 1)
        self.assertFalse(st.session_state.get("cadivor_login_handoff_active", False))
        host.empty.assert_not_called()

    def test_4_only_one_bootstrap_handoff_while_active(self):
        st = _install_streamlit_stub({})
        bootstrap, restore = _install_bootstrap_deps(st)
        self.addCleanup(restore)

        with patch("time.monotonic", side_effect=[1000.0, 1005.0, 1010.0]):
            bootstrap.begin_login_handoff(bootstrap.LOGIN_HANDOFF_STAGE_AUTHENTICATING)
            started = st.session_state[bootstrap.LOGIN_HANDOFF_STARTED_AT_KEY]
            bootstrap.begin_login_handoff(bootstrap.LOGIN_HANDOFF_STAGE_INITIALIZING)
            bootstrap.begin_login_handoff(bootstrap.LOGIN_HANDOFF_STAGE_INITIALIZING)

        self.assertEqual(
            st.session_state[bootstrap.LOGIN_HANDOFF_STARTED_AT_KEY], started
        )
        self.assertEqual(
            st.session_state[bootstrap.LOGIN_HANDOFF_STAGE_KEY],
            bootstrap.LOGIN_HANDOFF_STAGE_INITIALIZING,
        )

    def test_5_invalid_password_restores_form_with_error(self):
        st, auth, _ = self._load_auth()
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.side_effect = RuntimeError("denied")

        auth._submit_manual_login(
            supabase, MagicMock(), "keepme@example.com", "bad-password"
        )

        self.assertEqual(st.session_state["cadivor_root_state"], auth.APP_LOGIN)
        self.assertEqual(
            st.session_state[auth.ATOMIC_LOGIN_ERROR_KEY],
            "Email or password is incorrect. Please try again.",
        )
        self.assertEqual(
            st.session_state["cadivor_login_email_draft"],
            "keepme@example.com",
        )
        self.assertFalse(st.session_state.get("cadivor_login_handoff_active", False))
        st.rerun.assert_called_once_with()

    def test_6_expired_session_recovery_is_sign_in_again_not_blank(self):
        self.assertIn("Sign in again", AUTH)
        self.assertIn("session expired after inactivity", AUTH.lower())
        self.assertIn("SESSION_EXPIRED_NOTICE", IDLE)
        # Recovery clears handoff then reruns to Login — never host.empty().
        recovery = IDLE[
            IDLE.find("def enter_session_expired_recovery") : IDLE.find(
                "def render_retryable_profile_error"
            )
        ]
        self.assertIn("clear_login_handoff()", recovery)
        self.assertIn("st.rerun()", recovery)
        self.assertNotIn(".empty()", recovery)

    def test_early_progress_mount_before_resolve_when_tokens_present(self):
        self.assertIn("_should_keep_auth_progress_mounted()", BOOTSTRAP)
        self.assertIn("mount_auth_progress_surface(auth_surface_host)", BOOTSTRAP)
        # Host creation then immediate mount precedes resolve_auth_state.
        host_idx = BOOTSTRAP.find("auth_surface_host = st.empty()")
        mount_early = BOOTSTRAP.find(
            "if _should_keep_auth_progress_mounted():", host_idx
        )
        resolve_idx = BOOTSTRAP.find('log_startup_phase("resolve_auth_state")', host_idx)
        self.assertGreater(mount_early, host_idx)
        self.assertGreater(resolve_idx, mount_early)


class AuthHandoffNoBlankRegexContracts(unittest.TestCase):
    def test_no_empty_on_authenticated_boundary_path(self):
        """Authenticated fall-through mounts progress; never host.empty()."""
        start = BOOTSTRAP.find("# Same-run Login success:")
        end = BOOTSTRAP.find('log_startup_phase("auth_boundary_passed")', start)
        window = BOOTSTRAP[start:end]
        self.assertNotIn("auth_surface_host.empty()", window)
        self.assertIn("mount_auth_progress_surface(auth_surface_host)", window)

    def test_logout_may_empty_but_is_isolated(self):
        logout_idx = BOOTSTRAP.find('log_startup_phase("logout_redirect")')
        self.assertGreater(logout_idx, 0)
        window = BOOTSTRAP[logout_idx : logout_idx + 200]
        self.assertIn("auth_surface_host.empty()", window)


if __name__ == "__main__":
    unittest.main()

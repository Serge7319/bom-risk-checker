"""Sprint 75.2B / 75.2B.1 — login atomicity, recovery, shell data safety, loaders."""
from __future__ import annotations

import ast
import sys
import time
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


class LoginAtomicity752BTests(unittest.TestCase):
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
        st.info = MagicMock()

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

    def _seed_recent_attempt(self, st, auth_state, *, age_s: float = 1.0):
        now = time.time()
        st.session_state.update(
            {
                "cadivor_root_state": auth_state.APP_SIGNING_IN,
                "cadivor_manual_login_in_progress": True,
                "cadivor_auth_status": auth_state.AUTH_SIGNING_IN,
                "cadivor_manual_login_started_at": now - age_s,
                "cadivor_manual_login_attempt_id": "attempt-test-nonce",
            }
        )
        return now

    def test_signing_in_shows_transition_without_wiping_inflight(self):
        st, auth, auth_state = self._load_auth()
        self._seed_recent_attempt(st, auth_state)
        with patch.object(auth, "_auth_css"), patch.object(
            auth, "inject_core_premium_ui_auth"
        ), patch.object(auth, "render_auth_transition") as transition, patch.object(
            auth, "_render_auth_page"
        ) as login_form:
            auth.show_auth_ui(MagicMock(), None)
        transition.assert_called_once()
        login_form.assert_not_called()
        self.assertTrue(st.session_state.get("cadivor_manual_login_in_progress"))
        self.assertEqual(st.session_state["cadivor_root_state"], auth_state.APP_SIGNING_IN)

    def test_one_submit_calls_supabase_once(self):
        _st, auth, _auth_state = self._load_auth()
        supabase = MagicMock()
        session = types.SimpleNamespace(access_token="a", refresh_token="r")
        user = types.SimpleNamespace(id="user-1")
        supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
            user=user, session=session
        )
        with patch.object(auth, "mark_authenticated"):
            auth._submit_manual_login(supabase, MagicMock(), "user@example.com", "secret")
        supabase.auth.sign_in_with_password.assert_called_once()

    def test_submit_sets_signing_in_before_network(self):
        st, auth, auth_state = self._load_auth()
        order = []

        def begin(cookie_manager=None):
            order.append("begin")
            st.session_state["cadivor_manual_login_in_progress"] = True
            st.session_state["cadivor_manual_login_started_at"] = time.time()
            st.session_state["cadivor_manual_login_attempt_id"] = "x"
            st.session_state["cadivor_root_state"] = auth_state.APP_SIGNING_IN

        def sign_in(_creds):
            order.append("network")
            self.assertEqual(st.session_state.get("cadivor_auth_status"), auth_state.AUTH_SIGNING_IN)
            raise RuntimeError("boom")

        supabase = MagicMock()
        supabase.auth.sign_in_with_password.side_effect = sign_in
        with patch.object(auth, "begin_manual_login", side_effect=begin), patch.object(
            auth, "finish_manual_login_failed"
        ):
            auth._submit_manual_login(supabase, MagicMock(), "user@example.com", "secret")
        self.assertEqual(order, ["begin", "network"])

    def test_failed_login_returns_to_login_with_error(self):
        st, auth, auth_state = self._load_auth()
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.side_effect = RuntimeError("bad creds")
        with patch.object(auth, "finish_manual_login_failed") as finish:
            auth._submit_manual_login(supabase, MagicMock(), "user@example.com", "secret")
        finish.assert_called_once()
        self.assertEqual(st.session_state["cadivor_root_state"], auth_state.APP_LOGIN)
        self.assertIn("Authentication failed", st.session_state.get("cadivor_auth_error", ""))
        st.rerun.assert_not_called()

    def test_supabase_exception_clears_attempt_metadata(self):
        st, auth, auth_state = self._load_auth()
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.side_effect = RuntimeError("provider down")
        auth._submit_manual_login(supabase, MagicMock(), "user@example.com", "secret")
        self.assertIsNone(st.session_state.get("cadivor_manual_login_in_progress"))
        self.assertIsNone(st.session_state.get("cadivor_manual_login_started_at"))
        self.assertIsNone(st.session_state.get("cadivor_manual_login_attempt_id"))
        self.assertEqual(st.session_state["cadivor_root_state"], auth_state.APP_LOGIN)

    def test_rpc_timeout_exception_clears_attempt_metadata(self):
        st, auth, auth_state = self._load_auth()
        supabase = MagicMock()
        supabase.auth.sign_in_with_password.side_effect = TimeoutError("timed out")
        auth._submit_manual_login(supabase, MagicMock(), "user@example.com", "secret")
        self.assertIsNone(st.session_state.get("cadivor_manual_login_in_progress"))
        self.assertIsNone(st.session_state.get("cadivor_manual_login_started_at"))
        self.assertIsNone(st.session_state.get("cadivor_manual_login_attempt_id"))
        self.assertEqual(st.session_state["cadivor_root_state"], auth_state.APP_LOGIN)

    def test_successful_login_reruns_without_second_click(self):
        st, auth, _auth_state = self._load_auth()
        supabase = MagicMock()
        session = types.SimpleNamespace(access_token="a", refresh_token="r")
        user = types.SimpleNamespace(id="user-1")
        supabase.auth.sign_in_with_password.return_value = types.SimpleNamespace(
            user=user, session=session
        )
        with patch.object(auth, "mark_authenticated"):
            auth._submit_manual_login(supabase, MagicMock(), "user@example.com", "secret")
        st.rerun.assert_called_once()

    def test_form_submit_button_disabled_while_inflight(self):
        src = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
        self.assertIn("disabled=_login_in_flight", src)
        self.assertIn('"Signing in…" if _login_in_flight', src)

    def test_recent_signing_in_no_second_request(self):
        st, auth, auth_state = self._load_auth()
        self._seed_recent_attempt(st, auth_state, age_s=2.0)
        supabase = MagicMock()
        with patch.object(auth, "_auth_css"), patch.object(
            auth, "inject_core_premium_ui_auth"
        ), patch.object(auth, "render_auth_transition") as transition, patch.object(
            auth, "_render_auth_page"
        ) as login_form:
            auth.show_auth_ui(supabase, None)
        transition.assert_called_once()
        login_form.assert_not_called()
        supabase.auth.sign_in_with_password.assert_not_called()

    def test_stale_signing_in_recovers_enabled_login(self):
        st, auth, auth_state = self._load_auth()
        timeout = auth_state.MANUAL_LOGIN_STALE_TIMEOUT_SECONDS
        now = self._seed_recent_attempt(st, auth_state, age_s=timeout + 10)
        recovered = auth_state.recover_stale_manual_login(now=now)
        self.assertTrue(recovered)
        self.assertEqual(st.session_state["cadivor_root_state"], auth_state.APP_LOGIN)
        self.assertIn("did not finish", st.session_state.get("cadivor_auth_error", ""))
        self.assertIsNone(st.session_state.get("cadivor_manual_login_in_progress"))
        with patch.object(auth, "_auth_css"), patch.object(
            auth, "inject_core_premium_ui_auth"
        ), patch.object(auth, "render_auth_transition") as transition, patch.object(
            auth, "_render_auth_page"
        ) as login_form:
            auth.show_auth_ui(MagicMock(), None)
        transition.assert_not_called()
        login_form.assert_called_once()
        st.error.assert_called()

    def test_hard_refresh_stale_state_recovers(self):
        st, auth, auth_state = self._load_auth()
        timeout = auth_state.MANUAL_LOGIN_STALE_TIMEOUT_SECONDS
        now = time.time()
        st.session_state.update(
            {
                "cadivor_root_state": auth_state.APP_SIGNING_IN,
                "cadivor_manual_login_in_progress": True,
                "cadivor_auth_status": auth_state.AUTH_SIGNING_IN,
                "cadivor_manual_login_started_at": now - timeout - 1,
                "cadivor_manual_login_attempt_id": "stale-refresh",
            }
        )
        self.assertTrue(auth_state.recover_stale_manual_login(now=now))
        self.assertEqual(st.session_state["cadivor_root_state"], auth_state.APP_LOGIN)

    def test_attempt_id_contains_no_secrets(self):
        st, auth, auth_state = self._load_auth()
        auth_state.begin_manual_login(None)
        attempt_id = str(st.session_state.get("cadivor_manual_login_attempt_id") or "")
        self.assertTrue(attempt_id)
        for forbidden in ("@", "password", "secret", "token", "user@example.com"):
            self.assertNotIn(forbidden, attempt_id.lower())

    def test_logout_clears_attempt_metadata(self):
        st, auth, auth_state = self._load_auth()
        auth_state.begin_manual_login(None)
        auth_state._clear_user_session_for_logout()
        self.assertIsNone(st.session_state.get("cadivor_manual_login_in_progress"))
        self.assertIsNone(st.session_state.get("cadivor_manual_login_started_at"))
        self.assertIsNone(st.session_state.get("cadivor_manual_login_attempt_id"))

    def test_token_invalidation_clears_attempt_metadata(self):
        st, auth, auth_state = self._load_auth()
        auth_state.begin_manual_login(None)
        auth_state.clear_auth_session(keep_status=True, transition_reason="token_validation_failed")
        self.assertIsNone(st.session_state.get("cadivor_manual_login_in_progress"))
        self.assertIsNone(st.session_state.get("cadivor_manual_login_started_at"))
        self.assertIsNone(st.session_state.get("cadivor_manual_login_attempt_id"))

    def test_timing_flag_does_not_change_recovery(self):
        st, auth, auth_state = self._load_auth()
        timeout = auth_state.MANUAL_LOGIN_STALE_TIMEOUT_SECONDS
        now = self._seed_recent_attempt(st, auth_state, age_s=timeout + 2)
        for flag in (None, False, True):
            with patch("src.auth_state.get_secret_bool", return_value=bool(flag) if flag is not None else False):
                st.session_state.update(
                    {
                        "cadivor_manual_login_in_progress": True,
                        "cadivor_manual_login_started_at": now - timeout - 2,
                        "cadivor_manual_login_attempt_id": "t",
                        "cadivor_root_state": auth_state.APP_SIGNING_IN,
                    }
                )
                self.assertEqual(auth_state.manual_login_state(now=now), "stale")
                self.assertTrue(auth_state.recover_stale_manual_login(now=now))

    def test_streamlit_rerun_exception_propagates(self):
        _st, auth, _auth_state = self._load_auth()

        class RerunException(Exception):
            pass

        supabase = MagicMock()
        supabase.auth.sign_in_with_password.side_effect = RerunException("rerun")
        with self.assertRaises(RerunException):
            auth._submit_manual_login(supabase, MagicMock(), "user@example.com", "secret")

    def test_signup_pending_still_wins_over_signing_in(self):
        st, auth, auth_state = self._load_auth()
        st.session_state.update(
            {
                "cadivor_root_state": auth_state.APP_SIGNUP_CONFIRMATION_PENDING,
                "cadivor_manual_login_in_progress": True,
                "cadivor_manual_login_started_at": time.time(),
                "cadivor_manual_login_attempt_id": "x",
                auth_state.SIGNUP_PENDING_EMAIL_KEY: "new@cadivor.com",
            }
        )
        with patch.object(auth, "_auth_css"), patch.object(
            auth, "inject_core_premium_ui_auth"
        ), patch.object(auth, "_render_signup_confirmation_pending") as pending, patch.object(
            auth, "render_auth_transition"
        ) as transition, patch.object(auth, "_render_auth_page") as login_form:
            auth.show_auth_ui(MagicMock(), None)
        pending.assert_called_once()
        transition.assert_not_called()
        login_form.assert_not_called()
        self.assertIsNone(st.session_state.get("cadivor_manual_login_in_progress"))


class CallbackPrecedence752B1Tests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name.startswith("src.auth"):
                sys.modules.pop(name, None)

    def _load_auth(self):
        st = _install_streamlit_stub({}, context_cookies=_FakeContextCookies())
        st.rerun = MagicMock()
        st.error = MagicMock()
        st.success = MagicMock()
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

        return st, importlib.import_module("src.auth"), auth_state

    def _signing_flags(self, st, auth_state, *, stale: bool):
        timeout = auth_state.MANUAL_LOGIN_STALE_TIMEOUT_SECONDS
        age = timeout + 5 if stale else 1.0
        st.session_state.update(
            {
                "cadivor_manual_login_in_progress": True,
                "cadivor_manual_login_started_at": time.time() - age,
                "cadivor_manual_login_attempt_id": "cb-test",
                "cadivor_auth_status": auth_state.AUTH_SIGNING_IN,
            }
        )

    def test_password_recovery_beats_recent_signing_in(self):
        st, auth, auth_state = self._load_auth()
        self._signing_flags(st, auth_state, stale=False)
        st.session_state["cadivor_root_state"] = auth_state.APP_PASSWORD_RECOVERY
        with patch.object(auth, "_auth_css"), patch.object(
            auth, "inject_core_premium_ui_auth"
        ), patch.object(auth, "_render_password_recovery_form") as recovery, patch.object(
            auth, "render_auth_transition"
        ) as transition:
            auth.show_auth_ui(MagicMock(), None)
        recovery.assert_called_once()
        transition.assert_not_called()
        self.assertIsNone(st.session_state.get("cadivor_manual_login_in_progress"))

    def test_password_recovery_beats_stale_signing_in(self):
        st, auth, auth_state = self._load_auth()
        self._signing_flags(st, auth_state, stale=True)
        st.session_state["cadivor_root_state"] = auth_state.APP_PASSWORD_RECOVERY
        with patch.object(auth, "_auth_css"), patch.object(
            auth, "inject_core_premium_ui_auth"
        ), patch.object(auth, "_render_password_recovery_form") as recovery, patch.object(
            auth, "render_auth_transition"
        ) as transition:
            auth.show_auth_ui(MagicMock(), None)
        recovery.assert_called_once()
        transition.assert_not_called()

    def test_signup_success_beats_signing_in(self):
        st, auth, auth_state = self._load_auth()
        self._signing_flags(st, auth_state, stale=False)
        st.session_state["cadivor_root_state"] = auth_state.APP_SIGNUP_CONFIRMATION_SUCCESS
        with patch.object(auth, "_auth_css"), patch.object(
            auth, "inject_core_premium_ui_auth"
        ), patch.object(auth, "_render_signup_confirmation_success") as success, patch.object(
            auth, "render_auth_transition"
        ) as transition:
            auth.show_auth_ui(MagicMock(), None)
        success.assert_called_once()
        transition.assert_not_called()
        self.assertIsNone(st.session_state.get("cadivor_manual_login_in_progress"))

    def test_signup_invalid_beats_signing_in(self):
        st, auth, auth_state = self._load_auth()
        self._signing_flags(st, auth_state, stale=False)
        st.session_state["cadivor_root_state"] = auth_state.APP_SIGNUP_CONFIRMATION_INVALID
        with patch.object(auth, "_auth_css"), patch.object(
            auth, "inject_core_premium_ui_auth"
        ), patch.object(auth, "_render_signup_confirmation_invalid") as invalid, patch.object(
            auth, "render_auth_transition"
        ) as transition:
            auth.show_auth_ui(MagicMock(), None)
        invalid.assert_called_once()
        transition.assert_not_called()

    def test_accepted_callback_clears_manual_login_metadata(self):
        st, auth, auth_state = self._load_auth()
        self._signing_flags(st, auth_state, stale=False)
        st.session_state["cadivor_root_state"] = auth_state.APP_PASSWORD_RECOVERY
        with patch.object(auth, "_auth_css"), patch.object(
            auth, "inject_core_premium_ui_auth"
        ), patch.object(auth, "_render_password_recovery_form"):
            auth.show_auth_ui(MagicMock(), None)
        self.assertIsNone(st.session_state.get("cadivor_manual_login_started_at"))
        self.assertIsNone(st.session_state.get("cadivor_manual_login_attempt_id"))

    def test_conflicting_callback_rejection_remains_in_bootstrap(self):
        src = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("signup_and_recovery_markers_conflict()", src)
        self.assertIn("reject_conflicting_auth_callbacks()", src)


class ShellDataSafety752B1Tests(unittest.TestCase):
    def _load_shell_helper(self):
        sys.path.insert(0, str(ROOT))
        from src.plans import format_limit

        ns: dict = {"format_limit": format_limit}
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        start = src.index("def _shell_saved_summary")
        end = src.index("\ndef _localized_cold_route_load")
        exec(compile(src[start:end], "authenticated_runtime.py", "exec"), ns)
        return ns["_shell_saved_summary"]

    def test_no_bom_count_cache_reference(self):
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("cadivor_saved_bom_count_cache", runtime)
        auth = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
        bootstrap = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
        auth_state = (ROOT / "src" / "auth_state.py").read_text(encoding="utf-8")
        for blob in (auth, bootstrap, auth_state):
            self.assertNotIn("cadivor_saved_bom_count_cache", blob)

    def test_unknown_count_renders_no_saved_line(self):
        fn = self._load_shell_helper()
        self.assertEqual(fn(None, {"max_saved_boms": 10}), "")

    def test_none_does_not_render_emdash(self):
        fn = self._load_shell_helper()
        self.assertNotIn("—", fn(None, {"max_saved_boms": 10}))

    def test_none_does_not_render_zero(self):
        fn = self._load_shell_helper()
        self.assertNotIn("0", fn(None, {"max_saved_boms": 10}))

    def test_valid_live_zero_renders_zero(self):
        fn = self._load_shell_helper()
        live = fn(0, {"max_saved_boms": 10})
        self.assertTrue(live.startswith("0"))
        self.assertIn("saved BOM", live)

    def test_valid_positive_count_renders(self):
        fn = self._load_shell_helper()
        live = fn(7, {"max_saved_boms": 10})
        self.assertTrue(live.startswith("7"))
        self.assertIn("/", live)

    def test_malformed_count_omits_line(self):
        fn = self._load_shell_helper()
        self.assertEqual(fn("not-a-number", {"max_saved_boms": 10}), "")
        self.assertEqual(fn(object(), {"max_saved_boms": 10}), "")

    def test_plan_and_usage_still_passed_when_saved_unknown(self):
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        call = src[src.index("render_unified_shell(") : src.index("render_unified_shell(") + 900]
        self.assertIn("plan_name=selected_plan_name", call)
        self.assertIn("usage_summary=", call)
        self.assertIn("_shell_saved_summary(saved_bom_count, selected_plan)", call)

    def test_unified_shell_omits_empty_saved_span(self):
        src = (ROOT / "src" / "ui" / "unified_shell.py").read_text(encoding="utf-8")
        self.assertIn('if str(saved_summary or "").strip()', src)

    def test_live_workspace_count_query_preserved_once(self):
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertEqual(src.count('operation="saved_bom_count"'), 1)
        self.assertEqual(src.count("saved_bom_count_response = execute_supabase_read"), 1)
        self.assertIn("saved_bom_count = None", src)

    def test_no_new_data_cache_decorator_for_bom_count(self):
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("cadivor_saved_bom_count_cache", src)
        block_start = src.index("saved_bom_count = None")
        block = src[block_start : block_start + 2500]
        self.assertNotIn("@st.cache_data", block)
        self.assertNotIn("@st.cache_resource", block)
        self.assertNotIn("— /", src[src.index("def _shell_saved_summary") : src.index("def _localized_cold_route_load")])

    def test_shell_helper_in_runtime(self):
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn("def _shell_saved_summary(", src)
        self.assertIn("_shell_saved_summary(saved_bom_count, selected_plan)", src)
        self.assertIn("omits saved-BOM usage until a future live-fragment", src)
        self.assertNotIn("next script run", src)

    def test_shell_before_workspace_init(self):
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertLess(
            src.index("render_unified_shell("),
            src.index('timed_phase("runtime.workspace_init"'),
        )

    def test_no_extra_shell_supabase_call(self):
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        shell_region = src[
            src.index("saved_bom_count = None") : src.index('timed_phase("runtime.workspace_init"')
        ]
        self.assertNotIn("execute_supabase_read", shell_region)
        self.assertNotIn("st.rerun(", shell_region)

    def test_multi_user_cannot_carry_saved_count(self):
        """Unknown early-shell summary never reads another user's session count."""
        fn = self._load_shell_helper()
        # Simulate user A having a prior live local value that is not passed to the helper.
        user_a_live = 7
        # User B early shell always starts from None with no cache key available.
        self.assertEqual(fn(None, {"max_saved_boms": 10}), "")
        self.assertNotEqual(fn(None, {"max_saved_boms": 10}), fn(user_a_live, {"max_saved_boms": 10}))
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("cadivor_saved_bom_count_cache", runtime)


class LocalizedLoader752B1Tests(unittest.TestCase):
    def test_loader_success_clears_host(self):
        sys.path.insert(0, str(ROOT))
        # Load helper via targeted exec from source to avoid heavy imports.
        ns: dict = {}
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        start = src.index("def _localized_cold_route_load")
        end = src.index("\ndef run_authenticated_app")
        exec(compile(src[start:end], "authenticated_runtime.py", "exec"), ns)
        host = MagicMock()
        result = ns["_localized_cold_route_load"](
            host,
            message="Loading Reports…",
            module_name="__never_loaded_reports_mod__",
            import_fn=lambda: "ok",
        )
        self.assertEqual(result, "ok")
        host.info.assert_called_once()
        host.empty.assert_called_once()

    def test_loader_importerror_clears_and_propagates(self):
        sys.path.insert(0, str(ROOT))
        ns: dict = {}
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        start = src.index("def _localized_cold_route_load")
        end = src.index("\ndef run_authenticated_app")
        exec(compile(src[start:end], "authenticated_runtime.py", "exec"), ns)
        host = MagicMock()

        def boom():
            raise ImportError("missing module")

        with self.assertRaises(ImportError):
            ns["_localized_cold_route_load"](
                host,
                message="Loading Reports…",
                module_name="__missing__",
                import_fn=boom,
            )
        host.empty.assert_called_once()

    def test_reports_af_ad_use_localized_helper(self):
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn('message="Loading Reports…"', src)
        self.assertIn('message="Loading Alternative Finder…"', src)
        self.assertIn('message="Loading Analysis Details…"', src)
        self.assertEqual(src.count("_localized_cold_route_load("), 4)  # def + 3 call sites

    def test_streamlit_control_exception_not_suppressed(self):
        sys.path.insert(0, str(ROOT))
        ns: dict = {}
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        start = src.index("def _localized_cold_route_load")
        end = src.index("\ndef run_authenticated_app")
        exec(compile(src[start:end], "authenticated_runtime.py", "exec"), ns)
        host = MagicMock()

        class StopException(BaseException):
            pass

        def boom():
            raise StopException("stop")

        with self.assertRaises(StopException):
            ns["_localized_cold_route_load"](
                host,
                message="Loading Reports…",
                module_name="__x__",
                import_fn=boom,
            )
        host.empty.assert_called_once()

    def test_route_unchanged_contract_in_source(self):
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        # Loaders must not reassign cadivor_route / app_mode on failure paths.
        for marker in ("Loading Reports…", "Loading Alternative Finder…", "Loading Analysis Details…"):
            idx = src.index(marker)
            window = src[max(0, idx - 400) : idx + 400]
            self.assertNotIn('cadivor_route"] = "Dashboard"', window)


class PersistentShell752BTests(unittest.TestCase):
    def test_auth_surface_host_is_lazy(self):
        src = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("auth_surface_host = None", src)
        self.assertIn("def _auth_surface():", src)
        self.assertIn("if auth_surface_host is not None:", src)
        tree = ast.parse(src)
        fn = next(
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "ensure_authenticated_or_stop"
        )
        text = ast.get_source_segment(src, fn) or ""
        eager = text.find("auth_surface_host = st.empty()")
        lazy = text.find("auth_surface_host = None")
        self.assertGreaterEqual(lazy, 0)
        self.assertTrue(eager < 0 or eager > lazy)

    def test_shell_renders_before_workspace_init(self):
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        shell = src.index("render_unified_shell(")
        workspace = src.index('timed_phase("runtime.workspace_init"')
        self.assertLess(shell, workspace)

    def test_route_lazy_deferred_imports_remain(self):
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        header = src.split('log_startup_phase("authenticated_runtime_imports_complete")', 1)[0]
        for banned in (
            "from src.pages.analysis_detail",
            "from integrations.supplier_aggregator",
            "from src.alternative_engine",
            "from src.report_generator",
            "from src.ai_report_intelligence",
            "import plotly",
            "from reportlab",
        ):
            self.assertNotIn(banned, header)

    def test_localized_route_loading_markers(self):
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn("Loading Reports…", src)
        self.assertIn("Loading Alternative Finder…", src)
        self.assertIn("Loading Analysis Details…", src)

    def test_pandas_still_module_level(self):
        src = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        header = src.split('log_startup_phase("authenticated_runtime_imports_complete")', 1)[0]
        self.assertIn("import pandas as pd", header)


if __name__ == "__main__":
    unittest.main()

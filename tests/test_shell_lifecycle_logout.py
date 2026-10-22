"""Logout / cookie-clear / boot-restore state-machine coverage."""
from __future__ import annotations

import sys
import types
import unittest
import ast
import html
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _install_streamlit_stub(session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    st.query_params = {}
    st.markdown = MagicMock()
    st.stop = MagicMock(side_effect=RuntimeError("stop"))
    st.rerun = MagicMock(side_effect=RuntimeError("rerun"))
    st.cache_resource = lambda **_kwargs: (lambda fn: fn)
    st.cache_data = lambda **_kwargs: (lambda fn: fn)
    sys.modules["streamlit"] = st
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    components = types.ModuleType("streamlit.components.v1")
    components.html = MagicMock()
    sys.modules["streamlit.components.v1"] = components
    return st


class ClearAuthCookieParityTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name.startswith("src.auth_cookies") or name == "src.auth_state":
                sys.modules.pop(name, None)

    def tearDown(self):
        from tests.secrets_module_isolation import ensure_real_src_secrets_module

        ensure_real_src_secrets_module()

    def test_clear_auth_cookie_mirrors_write_path_secure_attrs(self):
        from tests.secrets_module_isolation import install_src_secrets_stub

        st = _install_streamlit_stub({})
        _secrets, restore = install_src_secrets_stub(
            get_secret_bool=lambda key, default=False: True
            if key == "CADIVOR_COOKIE_SECURE"
            else default,
            get_secret=lambda key, required=False, default=None: default,
            ConfigurationError=RuntimeError,
        )
        try:
            import src.auth_cookies as auth_cookies

            manager = MagicMock()
            auth_cookies.clear_auth_cookie(manager)
            set_calls = [c.kwargs for c in manager.set.call_args_list]
            auth_clears = [
                c
                for c in set_calls
                if c.get("cookie") in {auth_cookies.AUTH_COOKIE_NAME, auth_cookies.AUTH_COOKIE_LEGACY_NAME}
                and c.get("val") == ""
            ]
            self.assertTrue(auth_clears, set_calls)
            for call in auth_clears:
                self.assertEqual(call.get("path"), "/")
                self.assertEqual(call.get("same_site"), "lax")
                self.assertTrue(call.get("secure"))
                self.assertIsInstance(call.get("expires_at"), datetime)
                self.assertLess(call["expires_at"], datetime.now(timezone.utc))
        finally:
            restore()
            del st


class SignedOutQueryAndBootTimeoutTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name.startswith("src.auth_bootstrap") or name.startswith("src.auth_gate"):
                sys.modules.pop(name, None)

    def tearDown(self):
        from tests.secrets_module_isolation import ensure_real_src_secrets_module

        ensure_real_src_secrets_module()

    def test_apply_signed_out_query_marker_forces_login_and_clears_tokens(self):
        from tests.secrets_module_isolation import install_src_secrets_stub

        st = _install_streamlit_stub(
            {
                "access_token": "stale-access",
                "refresh_token": "stale-refresh",
                "user": object(),
            }
        )
        st.query_params = {"cadivor_signed_out": "1"}
        _secrets, restore = install_src_secrets_stub(
            get_secret_bool=lambda key, default=False: default,
            get_secret=lambda key, required=False, default=None: default,
            ConfigurationError=RuntimeError,
        )
        try:
            import src.auth_bootstrap as boot

            self.assertTrue(boot.apply_signed_out_query_marker())
            self.assertTrue(boot.st.session_state["cadivor_force_signed_out"])
            self.assertTrue(boot.st.session_state["cadivor_explicit_logout"])
            self.assertNotIn("access_token", boot.st.session_state)
            self.assertNotIn("refresh_token", boot.st.session_state)
            self.assertNotIn("cadivor_signed_out", boot.st.query_params)
        finally:
            restore()

    def test_boot_restore_timeout_helper(self):
        from tests.secrets_module_isolation import install_src_secrets_stub

        st = _install_streamlit_stub({})
        _secrets, restore = install_src_secrets_stub(
            get_secret_bool=lambda key, default=False: default,
            get_secret=lambda key, required=False, default=None: default,
            ConfigurationError=RuntimeError,
        )
        try:
            import src.auth_bootstrap as boot
            import time as time_mod

            self.assertFalse(boot._boot_restore_timed_out())
            # Write onto the same session_state object auth_bootstrap bound at import.
            boot.st.session_state[boot.BOOT_RESTORE_STARTED_AT_KEY] = (
                time_mod.monotonic() - 30
            )
            self.assertTrue(boot._boot_restore_timed_out())
        finally:
            restore()

    def test_top_frame_clear_script_includes_path_and_signed_out_redirect(self):
        from tests.secrets_module_isolation import install_src_secrets_stub

        _install_streamlit_stub({})
        _secrets, restore = install_src_secrets_stub(
            get_secret_bool=lambda key, default=False: default,
            get_secret=lambda key, required=False, default=None: default,
            ConfigurationError=RuntimeError,
        )
        try:
            import src.auth_cookies as auth_cookies

            script = auth_cookies.top_frame_auth_cookie_clear_script(
                redirect_path="/?cadivor_signed_out=1"
            )
            self.assertIn("cadivor_auth", script)
            self.assertIn("path=/", script)
            self.assertIn("cadivor_signed_out=1", script)
            self.assertIn("SameSite=Lax", script)
        finally:
            restore()


class WorkspaceAdmitCacheTests(unittest.TestCase):
    def test_remember_and_recent_roundtrip(self):
        from src.services.workspace_admit_cache import (
            clear_workspace_admit_cache,
            recent_workspace_admit,
            remember_workspace_admit,
        )

        state: dict = {}
        remember_workspace_admit(
            state,
            user_id="u1",
            payload={"saved_bom_count": 3, "active_workspace": {"id": "w1"}},
            now=1000.0,
        )
        hit = recent_workspace_admit(state, "u1", now=1010.0)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["saved_bom_count"], 3)
        self.assertIsNone(recent_workspace_admit(state, "u2", now=1010.0))
        self.assertIsNone(recent_workspace_admit(state, "u1", now=1200.0))
        clear_workspace_admit_cache(state)
        self.assertIsNone(recent_workspace_admit(state, "u1", now=1010.0))


class MainTransitionMarkerTests(unittest.TestCase):
    def test_route_loading_markup_has_stable_host_marker(self):
        source = (
            Path(__file__).resolve().parents[1] / "src" / "ui" / "main_transition.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "route_loading_markup"
        )
        namespace = {
            "html": html,
            "st": SimpleNamespace(session_state={}),
            "BOM_ANALYSIS_TRANSITION_KEY": "cadivor_bom_analysis_transition",
            "MAIN_TRANSITION_KIND_KEY": "cadivor_main_transition_kind",
        }
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                     "<transition-markup-test>", "exec"), namespace)

        rendered = namespace["route_loading_markup"]("BOM Analyzer", 7)
        self.assertIn('data-cadivor-transition-host="cadivor-main-transition"', rendered)
        self.assertIn('data-testid="cadivor-main-transition-host"', rendered)
        self.assertIn('data-cadivor-transition-gen="7"', rendered)
        self.assertIn("Opening BOM Analyzer", rendered)

    def test_transition_generation_does_not_reuse_ids_after_session_reset(self):
        state = {}
        clock_values = iter((100, 101))
        source = (
            Path(__file__).resolve().parents[1] / "src" / "ui" / "main_transition.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_next_transition_gen"
        )
        namespace = {
            "st": SimpleNamespace(session_state=state),
            "MAIN_TRANSITION_GEN_KEY": "cadivor_main_transition_gen",
            "time": SimpleNamespace(time_ns=lambda: next(clock_values)),
        }
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                     "<transition-generation-test>", "exec"), namespace)

        first = namespace["_next_transition_gen"]()
        state.clear()  # logout clears session state while old DOM may remain
        second = namespace["_next_transition_gen"]()

        self.assertEqual(first, 100)
        self.assertEqual(second, 101)



class OpeningCoverageTests(unittest.TestCase):
    def test_warm_nav_still_uses_cover_during_dom_replacement(self):
        source = (
            Path(__file__).resolve().parents[1] / "src" / "ui" / "main_transition.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "should_paint_opening_overlay"
        )
        namespace = {
            "st": SimpleNamespace(session_state={}),
            "MAIN_TRANSITION_ACTIVE_KEY": "cadivor_main_transition_active",
            "MAIN_TRANSITION_ROUTE_KEY": "cadivor_main_transition_route",
            "PRESENTED_ROUTE_KEY": "cadivor_presented_route",
            "BOM_ANALYSIS_TRANSITION_KEY": "cadivor_bom_analysis_transition",
        }
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                     "<opening-skip-test>", "exec"), namespace)
        should_paint_opening_overlay = namespace["should_paint_opening_overlay"]

        state = {
            "cadivor_foundation_shell_mounted": True,
            "cadivor_main_transition_active": True,
            "cadivor_main_transition_route": "Dashboard",
            "cadivor_presented_route": "Reports",
            "warm": True,
        }
        self.assertTrue(
            should_paint_opening_overlay(
                needs_transition=True,
                target_route="Dashboard",
                session_state=state,
            )
        )
        self.assertTrue(
            should_paint_opening_overlay(
                needs_transition=True,
                target_route="Dashboard",
                session_state={
                    **state,
                    "cadivor_main_transition_active": False,
                    "cadivor_presented_route": "",
                },
            )
        )
        self.assertTrue(
            should_paint_opening_overlay(
                needs_transition=True,
                target_route="Analysis Details",
                session_state=state,
            )
        )
        self.assertTrue(
            should_paint_opening_overlay(
                needs_transition=True,
                target_route="BOM Settings",
                session_state=state,
            )
        )
        self.assertTrue(
            should_paint_opening_overlay(
                needs_transition=True,
                session_state={"cadivor_foundation_shell_mounted": False, "user": {"id": "u1"}},
            )
        )


class CacheInvalidationEvidenceTests(unittest.TestCase):
    def test_different_user_misses_admit_and_profile_cache(self):
        from src.services.authenticated_profile_cache import (
            recent_verified_profile,
            remember_verified_profile,
        )
        from src.services.workspace_admit_cache import (
            recent_workspace_admit,
            remember_workspace_admit,
        )

        state: dict = {}
        remember_verified_profile(
            state, {"id": "u1", "email": "a@b.c"}, now=1000.0
        )
        remember_workspace_admit(
            state, user_id="u1", payload={"saved_bom_count": 1}, now=1000.0
        )
        self.assertIsNotNone(recent_verified_profile(state, "u1", now=1010.0))
        self.assertIsNotNone(recent_workspace_admit(state, "u1", now=1010.0))
        self.assertIsNone(recent_verified_profile(state, "u2", now=1010.0))
        self.assertIsNone(recent_workspace_admit(state, "u2", now=1010.0))

    def test_source_wires_invalidation_for_logout_workspace_refresh_login(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        runtime = (root / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        idle = (root / "src" / "auth_idle_recovery.py").read_text(encoding="utf-8")
        auth_state = (root / "src" / "auth_state.py").read_text(encoding="utf-8")
        self.assertIn("clear_workspace_admit_cache", runtime)
        self.assertIn("active_workspace_id", runtime)
        self.assertIn("clear_verified_profile", idle)
        self.assertIn("clear_workspace_admit_cache", idle)
        self.assertIn("cadivor_retry_workspace_profile", idle)
        self.assertIn("clear_verified_profile", auth_state)
        self.assertIn("clear_workspace_admit_cache", auth_state)


if __name__ == "__main__":
    unittest.main()

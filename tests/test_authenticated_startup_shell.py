"""Sprint 71.9.5 — persistent authenticated workspace shell lifecycle tests."""
from __future__ import annotations

import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def _install_streamlit_stub(session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    st.query_params = {}
    st.stop = MagicMock()
    st.markdown = MagicMock()
    st.caption = MagicMock()

    class _Host:
        def container(self, *args, **kwargs):
            return MagicMock(
                __enter__=MagicMock(return_value=self),
                __exit__=MagicMock(return_value=False),
            )

        def empty(self):
            return self

    st.empty = MagicMock(side_effect=lambda: _Host())

    def cache_resource(**kwargs):
        def decorator(fn):
            return fn
        return decorator

    st.cache_resource = cache_resource

    components = types.ModuleType("streamlit.components.v1")
    components.html = MagicMock()
    sys.modules["streamlit"] = st
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st


def _install_auth_state(st):
    secrets = sys.modules.get("src.secrets")
    if secrets is None:
        secrets = types.ModuleType("src.secrets")
    secrets.get_secret = getattr(
        secrets, "get_secret", lambda key, required=False, default=None: "test-secret"
    )
    secrets.get_secret_bool = getattr(
        secrets, "get_secret_bool", lambda key, default=False: default
    )
    sys.modules["src.secrets"] = secrets

    auth_cookies = types.ModuleType("src.auth_cookies")

    def _noop(*args, **kwargs):
        return None

    auth_cookies.log_auth_restore = _noop
    auth_cookies.persist_session_auth_cookie = _noop
    auth_cookies.clear_auth_cookie = _noop
    auth_cookies.native_context_cookies_available = lambda: True
    auth_cookies.native_cookie_api_available = lambda: True
    auth_cookies.read_auth_cookie_tokens = lambda cookie_manager=None: None
    auth_cookies.read_auth_cookie_tokens_with_source = lambda cookie_manager=None: (None, "none")
    auth_cookies.get_auth_cookie_manager = lambda mount=True: MagicMock()
    auth_cookies.logout_blocks_auth_restore = lambda cookie_manager=None: False
    auth_cookies.invalidate_corrupt_auth_cookie = _noop
    auth_cookies.auth_cookie_hydration_pending = lambda cookie_manager=None: False
    auth_cookies.manager_fallback_hydration_pending = lambda cookie_manager=None: False
    auth_cookies.finalize_auth_cookie_hydration_timeout = _noop
    auth_cookies.finalize_manager_fallback_hydration_timeout = _noop
    auth_cookies.hydrate_session_from_auth_cookie = lambda cookie_manager=None: False
    auth_cookies.record_auth_hydration_attempt = lambda: 0
    auth_cookies._MAX_HYDRATION_ATTEMPTS = 3
    auth_cookies._MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS = 0.25
    sys.modules["src.auth_cookies"] = auth_cookies

    sys.modules.pop("src.auth_state", None)
    import importlib

    return importlib.import_module("src.auth_state")


def _install_bootstrap_deps(st):
    secrets = types.ModuleType("src.secrets")
    secrets.get_secret = lambda key, required=False, default=None: "test-secret"
    secrets.get_secret_bool = lambda key, default=False: default
    sys.modules["src.secrets"] = secrets

    auth_cookies = sys.modules.get("src.auth_cookies")
    if auth_cookies is None:
        auth_cookies = types.ModuleType("src.auth_cookies")
    auth_cookies._MAX_HYDRATION_ATTEMPTS = 3
    auth_cookies.auth_cookie_hydration_pending = lambda cookie_manager=None: False
    auth_cookies.manager_fallback_hydration_pending = lambda cookie_manager=None: False
    auth_cookies.finalize_auth_cookie_hydration_timeout = MagicMock()
    auth_cookies.finalize_manager_fallback_hydration_timeout = MagicMock()
    auth_cookies.get_auth_cookie_manager = lambda mount=True: MagicMock()
    auth_cookies.hydrate_session_from_auth_cookie = lambda cookie_manager=None: False
    auth_cookies.log_auth_restore = MagicMock()
    auth_cookies.native_context_cookies_available = lambda: True
    auth_cookies.native_cookie_api_available = lambda: True
    auth_cookies.persist_session_auth_cookie = MagicMock()
    auth_cookies.read_auth_cookie_tokens = lambda cookie_manager=None: None
    auth_cookies.read_auth_cookie_tokens_with_source = lambda cookie_manager=None: (None, "none")
    auth_cookies.record_auth_hydration_attempt = lambda: 0
    auth_cookies._MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS = 0.25
    sys.modules["src.auth_cookies"] = auth_cookies

    auth_diagnostics = types.ModuleType("src.auth_diagnostics")
    auth_diagnostics.log_auth_correlation = MagicMock()
    auth_diagnostics.log_auth_bounce = MagicMock()
    sys.modules["src.auth_diagnostics"] = auth_diagnostics

    _install_auth_state(st)

    auth = types.ModuleType("src.auth")
    auth.show_auth_ui = MagicMock()
    sys.modules["src.auth"] = auth

    core_premium_ui = types.ModuleType("src.ui.core_premium_ui")
    core_premium_ui.authenticated_surface_ready = lambda: bool(
        st.session_state.get("_cadivor_authenticated_surface_ready")
    )
    core_premium_ui.mark_authenticated_surface_ready = lambda: st.session_state.__setitem__(
        "_cadivor_authenticated_surface_ready", True
    )
    sys.modules["src.ui.core_premium_ui"] = core_premium_ui

    supabase = types.ModuleType("supabase")
    supabase.create_client = MagicMock(return_value=MagicMock(name="supabase"))
    sys.modules["supabase"] = supabase

    sys.modules.pop("src.auth_bootstrap", None)

    import importlib

    return importlib.import_module("src.auth_bootstrap")


class AuthenticatedStartupShellTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name.startswith("src.auth") or name == "src.ui.core_premium_ui":
                sys.modules.pop(name, None)

    def _load_bootstrap(self, session_state=None):
        st = _install_streamlit_stub(session_state or {})
        bootstrap = _install_bootstrap_deps(st)
        return st, bootstrap, sys.modules["src.auth_state"], sys.modules["src.auth"]

    def test_first_authenticated_initialization_may_render_startup_shell(self):
        _st, bootstrap, *_rest = self._load_bootstrap({})
        self.assertTrue(bootstrap.should_render_authenticated_startup_shell())
        self.assertTrue(bootstrap.should_render_authenticated_startup_shell())

    def test_second_authenticated_rerun_does_not_render_startup_shell(self):
        _st, bootstrap, *_rest = self._load_bootstrap(
            {"_cadivor_authenticated_surface_ready": True}
        )
        self.assertFalse(bootstrap.should_render_authenticated_startup_shell())

    def test_dashboard_interaction_rerun_does_not_render_startup_shell(self):
        _st, bootstrap, *_rest = self._load_bootstrap(
            {
                "_cadivor_authenticated_surface_ready": True,
                "cadivor_route": "Dashboard",
                "app_mode": "Dashboard",
            }
        )
        self.assertFalse(bootstrap.should_render_authenticated_startup_shell())

    def test_analysis_details_section_change_does_not_render_startup_shell(self):
        _st, bootstrap, *_rest = self._load_bootstrap(
            {
                "_cadivor_authenticated_surface_ready": True,
                "cadivor_route": "Analysis Details",
                "cadivor_active_analysis_tab": "Risk Overview",
            }
        )
        self.assertFalse(bootstrap.should_render_authenticated_startup_shell())

    def test_ask_cadivor_submit_rerun_does_not_render_startup_shell(self):
        _st, bootstrap, *_rest = self._load_bootstrap(
            {
                "_cadivor_authenticated_surface_ready": True,
                "cadivor_route": "Analysis Details",
                "cv4801_followup_inflight": True,
            }
        )
        self.assertFalse(bootstrap.should_render_authenticated_startup_shell())

    def test_authenticated_startup_shell_copy_is_not_auth_transition_copy(self):
        _st, bootstrap, *_rest = self._load_bootstrap({})
        self.assertEqual(
            bootstrap.AUTHENTICATED_STARTUP_SHELL_MESSAGE,
            "Loading your workspace…",
        )
        self.assertNotIn("Opening your engineering workspace", bootstrap.AUTHENTICATED_STARTUP_SHELL_MESSAGE)

    def test_startup_shell_preserves_workspace_chrome_during_handoff(self):
        st, bootstrap, *_rest = self._load_bootstrap({})
        bootstrap.render_startup_loading_shell(
            bootstrap.AUTHENTICATED_STARTUP_SHELL_MESSAGE
        )

        rendered = "\n".join(
            str(call.args[0])
            for call in st.markdown.call_args_list
            if call.args
        )
        self.assertIn("cv-startup-shell-topbar", rendered)
        self.assertIn("cv-startup-shell-nav", rendered)
        self.assertIn("cv-startup-shell-main", rendered)
        self.assertIn("Dashboard", rendered)
        self.assertIn("BOM Analyzer", rendered)
        self.assertIn("Loading your workspace", rendered)

    def test_startup_shell_does_not_fade_before_real_shell_marker(self):
        st, bootstrap, *_rest = self._load_bootstrap({})
        bootstrap.render_startup_loading_shell()

        rendered = "\n".join(
            str(call.args[0])
            for call in st.markdown.call_args_list
            if call.args
        )
        self.assertIn("[data-stale]:has(.cv-startup-shell)", rendered)
        self.assertIn(":has(.cv-workspace-ready-marker) .cv-startup-shell", rendered)
        self.assertNotIn(":has(.cv-foundation-topbar) .cv-startup-shell", rendered)
        self.assertIn("position:fixed", rendered)
        self.assertIn("pointer-events:none", rendered)

    def test_workspace_ready_marker_is_emitted_after_final_geometry(self):
        runtime_source = (ROOT / "src" / "authenticated_runtime.py").read_text(
            encoding="utf-8"
        )
        geometry_index = runtime_source.rfind("inject_workspace_geometry_final()")
        marker_index = runtime_source.rfind("cv-workspace-ready-marker")
        self.assertGreater(geometry_index, -1)
        self.assertGreater(marker_index, geometry_index)
        self.assertEqual(runtime_source.count("cv-workspace-ready-marker"), 1)

    def test_startup_overlay_does_not_retire_on_shell_chrome_alone(self):
        bootstrap_source = (ROOT / "src" / "auth_bootstrap.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            ":has(.cv-workspace-ready-marker) .cv-startup-shell",
            bootstrap_source,
        )
        self.assertNotIn(
            ":has(.cv-foundation-topbar) .cv-startup-shell",
            bootstrap_source,
        )

    def test_startup_shell_is_visual_only_and_not_an_auth_surface(self):
        st, bootstrap, *_rest = self._load_bootstrap({})
        bootstrap.render_startup_loading_shell()

        rendered = "\n".join(
            str(call.args[0])
            for call in st.markdown.call_args_list
            if call.args
        )
        self.assertNotIn("cadivor_auth_form", rendered)
        self.assertNotIn("st-key-cadivor_auth_card", rendered)
        self.assertNotIn("text_input", rendered)
        self.assertNotIn("st.rerun", rendered)

    def test_streamlit_entrypoint_gates_startup_shell(self):
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("should_render_authenticated_startup_shell()", source)
        self.assertIn("AUTHENTICATED_STARTUP_SHELL_MESSAGE", source)
        self.assertNotIn(
            'render_startup_loading_shell("Opening your engineering workspace',
            source,
        )

    def test_valid_cookie_f5_restores_without_forcing_login(self):
        st, bootstrap, auth_state, auth = self._load_bootstrap(
            {
                "user": object(),
                "access_token": "a",
                "refresh_token": "r",
            }
        )

        with patch.object(bootstrap, "resolve_auth_state", return_value=auth_state.AUTH_AUTHENTICATED):
            bootstrap.ensure_authenticated_or_stop()

        auth.show_auth_ui.assert_not_called()

    def test_auth_login_query_with_authenticated_session_does_not_display_login(self):
        st, bootstrap, auth_state, auth = self._load_bootstrap(
            {
                "user": object(),
                "access_token": "a",
                "refresh_token": "r",
                "cadivor_root_state": "login",
                "cadivor_auth_intent_applied": True,
            }
        )
        st.query_params = {"auth": "login"}

        with patch.object(bootstrap, "resolve_auth_state", return_value=auth_state.AUTH_AUTHENTICATED):
            bootstrap.ensure_authenticated_or_stop()

        auth.show_auth_ui.assert_not_called()

    def test_invalid_credentials_fail_closed_to_login(self):
        st, bootstrap, auth_state, auth = self._load_bootstrap({})

        with patch.object(bootstrap, "resolve_auth_state", return_value=auth_state.AUTH_SIGNED_OUT):
            with patch.object(st, "stop", side_effect=RuntimeError("stop")):
                try:
                    bootstrap.ensure_authenticated_or_stop()
                except RuntimeError:
                    pass

        auth.show_auth_ui.assert_called_once()

    def test_expired_credentials_fail_closed_to_login(self):
        st, bootstrap, auth_state, auth = self._load_bootstrap(
            {
                "access_token": "stale",
                "refresh_token": "stale",
                "cadivor_root_state": "authenticated",
            }
        )

        with patch.object(bootstrap, "resolve_auth_state", return_value=auth_state.AUTH_SIGNED_OUT):
            with patch.object(st, "stop", side_effect=RuntimeError("stop")):
                try:
                    bootstrap.ensure_authenticated_or_stop()
                except RuntimeError:
                    pass

        auth.show_auth_ui.assert_called_once()

    def test_auth_gate_uses_resolved_status_only(self):
        source = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("if auth_status != AUTH_AUTHENTICATED:", source)
        self.assertNotIn("root_state != APP_AUTHENTICATED", source)

    def test_authenticated_runtime_never_imports_marketing_modules(self):
        runtime_source = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        tree = ast.parse(runtime_source)
        imports = {
            (node.module, node.names[0].name if node.names else "")
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        marketing_modules = {
            pair
            for pair in imports
            if pair[0] and ("marketing" in pair[0].lower())
        }
        self.assertEqual(marketing_modules, set())
        self.assertNotIn("render_marketing_site", runtime_source)
        self.assertNotIn("CADIVOR_MARKETING_URL", runtime_source)

    def test_no_automatic_marketing_navigation_in_authenticated_modules(self):
        scan_roots = [
            ROOT / "src" / "authenticated_runtime.py",
            ROOT / "src" / "ui",
            ROOT / "src" / "pages",
        ]
        forbidden = (
            "location.replace(",
            "CADIVOR_MARKETING_URL",
            "marketing_url(",
            "render_marketing_site",
        )
        hits: list[str] = []
        for root in scan_roots:
            paths = [root] if root.is_file() else root.rglob("*.py")
            for path in paths:
                text = path.read_text(encoding="utf-8")
                for token in forbidden:
                    if token in text:
                        hits.append(f"{path.relative_to(ROOT)}:{token}")
        self.assertEqual(hits, [])

    def test_marketing_links_in_auth_shell_are_manual_only(self):
        auth_source = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
        self.assertIn("CADIVOR_MARKETING_URL", auth_source)
        self.assertNotIn("location.replace", auth_source)


if __name__ == "__main__":
    unittest.main()

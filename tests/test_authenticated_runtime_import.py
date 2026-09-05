"""Regression tests for Sprint 71.7D lazy runtime client initialization."""
from __future__ import annotations

import ast
import importlib
import pathlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "src" / "authenticated_runtime.py"


def _runtime_source() -> str:
    return RUNTIME_PATH.read_text(encoding="utf-8")


class AuthenticatedRuntimeImportTests(unittest.TestCase):
    def test_no_module_level_client_init_calls(self):
        tree = ast.parse(_runtime_source())
        forbidden = {"get_auth_cookie_manager", "get_supabase_client"}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                if node.name == "load_user_data":
                    break
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                func = sub.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name in forbidden:
                    self.fail(
                        f"Module-level call to {name}() at line {sub.lineno} "
                        "must not run during import"
                    )

    def test_module_level_clients_default_to_none(self):
        tree = ast.parse(_runtime_source())
        assigned = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "load_user_data":
                break
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned[target.id] = ast.unparse(node.value)
        self.assertEqual(assigned.get("cookie_manager"), "None")
        self.assertEqual(assigned.get("supabase"), "None")

    def _install_streamlit_stub(self):
        st = types.ModuleType("streamlit")
        st.session_state = {}
        st.query_params = {}
        st.markdown = MagicMock()
        st.stop = MagicMock(side_effect=RuntimeError("stop"))
        st.cache_data = lambda *args, **kwargs: (lambda fn: fn)
        st.cache_resource = lambda *args, **kwargs: (lambda fn: fn)
        components_v1 = types.ModuleType("streamlit.components.v1")
        components_v1.html = MagicMock()
        components_v1.declare_component = MagicMock(
            return_value=MagicMock(return_value=None)
        )
        sys.modules["streamlit"] = st
        sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
        sys.modules["streamlit.components.v1"] = components_v1
        return st

    def _install_auth_cookies_stub(self):
        auth_cookies = types.ModuleType("src.auth_cookies")
        auth_cookies.get_auth_cookie_manager = MagicMock(return_value=MagicMock(name="cookie_manager"))
        sys.modules["src.auth_cookies"] = auth_cookies
        return auth_cookies

    def _install_auth_bootstrap_stub(self):
        auth_bootstrap = types.ModuleType("src.auth_bootstrap")
        auth_bootstrap.get_supabase_client = MagicMock(return_value=MagicMock(name="supabase"))
        auth_bootstrap.log_startup_phase = MagicMock()
        auth_bootstrap.qp_value = lambda name, default="": default
        sys.modules["src.auth_bootstrap"] = auth_bootstrap
        return auth_bootstrap

    def _load_runtime_module(self):
        self._install_streamlit_stub()
        auth_cookies = self._install_auth_cookies_stub()
        auth_bootstrap = self._install_auth_bootstrap_stub()
        for name in (
            "src.authenticated_runtime",
            "src.browser_navigation",
            "src.auth_idle_recovery",
        ):
            sys.modules.pop(name, None)
        try:
            runtime = importlib.import_module("src.authenticated_runtime")
        except ModuleNotFoundError as exc:
            raise exc
        return runtime, auth_cookies, auth_bootstrap

    def test_import_does_not_call_runtime_client_helpers(self):
        try:
            runtime, auth_cookies, auth_bootstrap = self._load_runtime_module()
        except ModuleNotFoundError:
            self.skipTest("Full runtime import requires optional app dependencies")

        auth_cookies.get_auth_cookie_manager.assert_not_called()
        auth_bootstrap.get_supabase_client.assert_not_called()
        self.assertIsNone(runtime.cookie_manager)
        self.assertIsNone(runtime.supabase)

    def test_init_runtime_clients_binds_cached_helpers(self):
        try:
            runtime, auth_cookies, auth_bootstrap = self._load_runtime_module()
        except ModuleNotFoundError:
            self.skipTest("Full runtime import requires optional app dependencies")

        cookie = MagicMock(name="cookie_manager")
        sb = MagicMock(name="supabase")
        auth_cookies.get_auth_cookie_manager.return_value = cookie
        auth_bootstrap.get_supabase_client.return_value = sb

        runtime._init_runtime_clients()
        auth_cookies.get_auth_cookie_manager.assert_called_once_with()
        auth_bootstrap.get_supabase_client.assert_called_once_with()
        self.assertIs(runtime.cookie_manager, cookie)
        self.assertIs(runtime.supabase, sb)

        runtime._init_runtime_clients()
        auth_cookies.get_auth_cookie_manager.assert_called_once_with()
        auth_bootstrap.get_supabase_client.assert_called_once_with()

    def test_run_authenticated_app_calls_init_before_load_user_data(self):
        call_order: list[str] = []

        def _track_init():
            call_order.append("init")

        def _track_load():
            call_order.append("load")
            raise RuntimeError("stop_after_load")

        try:
            runtime, _, _ = self._load_runtime_module()
        except ModuleNotFoundError:
            self.skipTest("Full runtime import requires optional app dependencies")

        # Patch logout helpers after import so module-level auth_state symbols remain.
        with patch("src.auth_state.explicit_logout_pending", return_value=False), patch(
            "src.auth_state.handle_explicit_logout_if_pending", return_value=False
        ), patch.object(
            runtime, "_init_runtime_clients", side_effect=_track_init
        ), patch.object(runtime, "load_user_data", side_effect=_track_load):
            with self.assertRaises(RuntimeError):
                runtime.run_authenticated_app()

        self.assertEqual(call_order, ["init", "load"])


if __name__ == "__main__":
    unittest.main()

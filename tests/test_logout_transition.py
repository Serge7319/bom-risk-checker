"""Logout transition tests for Sprint 71.7."""
from __future__ import annotations

import ast
import inspect
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _install_streamlit_stub(session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    st.query_params = {}
    sys.modules["streamlit"] = st
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = types.ModuleType("streamlit.components.v1")
    return st


class LogoutTransitionTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name in {"src.auth_state", "src.auth_cookies"}:
                sys.modules.pop(name, None)

    def _load_auth_state(self, session_state=None):
        st = _install_streamlit_stub(session_state)
        secrets = types.ModuleType("src.secrets")
        secrets.get_secret_bool = lambda key, default=False: default
        sys.modules["src.secrets"] = secrets

        auth_cookies = types.ModuleType("src.auth_cookies")
        auth_cookies.clear_auth_cookie = MagicMock()
        auth_cookies.log_auth_restore = MagicMock()
        sys.modules["src.auth_cookies"] = auth_cookies

        sys.modules.pop("src.auth_state", None)
        import importlib

        return st, importlib.import_module("src.auth_state")

    def test_begin_logout_sets_reload_pending(self):
        st, auth_state = self._load_auth_state({"user": object()})
        supabase = MagicMock()
        auth_state.begin_logout(supabase, cookie_manager=None)
        self.assertTrue(st.session_state["cadivor_logout_reload_pending"])
        self.assertTrue(st.session_state["cadivor_force_signed_out"])
        self.assertNotIn("user", st.session_state)

    def test_remote_sign_out_does_not_reference_session_state(self):
        _, auth_state = self._load_auth_state()
        source = inspect.getsource(auth_state._remote_sign_out)
        tree = ast.parse(source)
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertNotIn("st", names)
        self.assertNotIn("session_state", names)

    def test_resolve_auth_state_signed_out_after_force_flag(self):
        st, auth_state = self._load_auth_state({"cadivor_force_signed_out": True})
        status = auth_state.resolve_auth_state(MagicMock(), cookie_manager=None)
        self.assertEqual(status, auth_state.AUTH_SIGNED_OUT)
        self.assertNotIn("user", st.session_state)


if __name__ == "__main__":
    unittest.main()

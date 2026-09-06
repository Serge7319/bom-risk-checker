"""Authenticated startup shell tests — gate model (legacy topbar shell retired)."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]


def _install_streamlit_stub(session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    st.query_params = {}
    st.stop = MagicMock()
    st.markdown = MagicMock()
    st.caption = MagicMock()
    st.button = MagicMock(return_value=False)
    st.empty = MagicMock()
    st.cache_resource = lambda **kwargs: (lambda fn: fn)
    components = types.ModuleType("streamlit.components.v1")
    components.html = MagicMock()
    sys.modules["streamlit"] = st
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st


class AuthGateStartupContracts(unittest.TestCase):
    def test_entrypoint_has_no_competing_shell(self):
        source = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("ensure_authenticated_or_stop()", source)
        self.assertNotIn("should_render_authenticated_startup_shell()", source)
        self.assertNotIn("render_startup_loading_shell(", source)

    def test_should_render_always_false(self):
        st = _install_streamlit_stub({})
        import importlib

        import src.auth_bootstrap as bootstrap

        importlib.reload(bootstrap)
        self.assertFalse(bootstrap.should_render_authenticated_startup_shell())
        st.session_state["cadivor_login_handoff_active"] = True
        self.assertFalse(bootstrap.should_render_authenticated_startup_shell())

    def test_legacy_shell_redirects_to_gate_without_topbar(self):
        st = _install_streamlit_stub({})
        frames: list[str] = []
        st.markdown = MagicMock(side_effect=lambda html, **kwargs: frames.append(str(html)))
        # Fresh import after streamlit stub is installed.
        for name in list(sys.modules):
            if name == "src.auth_gate" or name.startswith("src.auth_gate."):
                del sys.modules[name]
            if name == "src.auth_bootstrap" or name.startswith("src.auth_bootstrap."):
                del sys.modules[name]
        import src.auth_bootstrap as bootstrap

        bootstrap.render_startup_loading_shell("Preparing…")
        joined = "\n".join(frames)
        self.assertIn("data-auth-gate=", joined)
        self.assertIn("Signing you in…", joined)
        self.assertNotIn("cv-startup-shell-topbar", joined)


if __name__ == "__main__":
    unittest.main()

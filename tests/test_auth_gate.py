"""Auth-gate unit + lifecycle smoke (no env-based mock auth)."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


class AuthGateModuleTests(unittest.TestCase):
    def test_states_and_paint_markers(self):
        from src import auth_gate

        self.assertEqual(
            set(auth_gate._VALID_STATES),
            {"boot", "login", "authenticating", "ready", "error"},
        )
        source = (ROOT / "src" / "auth_gate.py").read_text(encoding="utf-8")
        self.assertIn("data-auth-gate=", source)
        self.assertIn("Restoring your session…", source)
        self.assertIn("Signing you in…", source)
        self.assertNotRegex(source, r"(?m)^\s*st\.empty\(\)")
        self.assertNotIn("cv-startup-shell-topbar", source)
        self.assertNotIn("CADIVOR_AUTH_GATE_MOCK", source)
        self.assertNotIn("mock_auth_enabled", source)
        # Cold visitors must not default into boot.
        self.assertIn('return "login"', source)
        self.assertIn("_inject_gate_css", source)

    def test_resolve_initial_login_without_tokens(self):
        from src.auth_gate import resolve_initial_gate_state

        self.assertEqual(
            resolve_initial_gate_state(has_tokens=False),
            "login",
        )
        self.assertEqual(
            resolve_initial_gate_state(has_tokens=True),
            "boot",
        )
        self.assertEqual(
            resolve_initial_gate_state(pending_credentials=True),
            "authenticating",
        )
        self.assertEqual(
            resolve_initial_gate_state(
                has_tokens=True,
                already_authenticated=True,
            ),
            "ready",
        )

    def test_continuity_shell_never_inserts_global_skeleton(self):
        shell = (ROOT / "src" / "ui" / "unified_shell.py").read_text(encoding="utf-8")
        fn = shell[
            shell.find("def paint_authenticated_continuity_shell") : shell.find(
                "def _escape"
            )
        ]
        self.assertIn("cv-foundation-continuity", fn)
        self.assertIn("cadivor-continuity-shell", fn)
        self.assertNotIn("render_page_skeleton", fn)
        self.assertNotIn("content_skeleton", fn)
        self.assertNotIn("cv56-skeleton-page", fn.split("Never leave")[0])
        self.assertIn("height:0!important", fn)

    def test_bootstrap_no_longer_uses_empty_host_root(self):
        bootstrap = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
        gate_fn = bootstrap[
            bootstrap.find("def ensure_authenticated_or_stop") : bootstrap.find(
                "# NOTE: auth gate owns paint"
            )
        ]
        self.assertIn("paint_auth_gate(", gate_fn)
        self.assertIn("set_auth_gate_state(", gate_fn)
        self.assertNotIn("auth_surface_host = st.empty()", gate_fn)
        self.assertNotIn("auth_surface_host.empty()", gate_fn)
        self.assertNotIn("mock_auth_enabled", gate_fn)
        self.assertNotIn("CADIVOR_AUTH_GATE_MOCK", gate_fn)

    def test_entrypoint_has_no_competing_startup_shell(self):
        entry = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("ensure_authenticated_or_stop()", entry)
        self.assertNotIn("should_render_authenticated_startup_shell()", entry)
        self.assertNotIn("render_startup_loading_shell(", entry)
        self.assertNotIn("mock_auth_enabled", entry)
        self.assertNotIn("CADIVOR_AUTH_GATE_MOCK", entry)

    def test_login_submit_stashes_then_reruns(self):
        auth = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
        submit = auth[
            auth.find("def _submit_manual_login") : auth.find("def execute_password_login")
        ]
        self.assertIn("stash_pending_credentials", submit)
        self.assertIn('set_auth_gate_state("authenticating"', submit)
        self.assertIn("st.rerun()", submit)
        self.assertNotIn("mount_auth_progress_surface", submit)
        self.assertNotIn("render_startup_loading_shell", submit)
        self.assertNotIn("mock_auth_enabled", auth)

    def test_production_sources_have_no_mock_env_switch(self):
        for rel in (
            "src/auth_gate.py",
            "src/auth_bootstrap.py",
            "src/auth.py",
            "streamlit_app.py",
        ):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("CADIVOR_AUTH_GATE_MOCK", text, rel)
            self.assertNotIn("mock_auth_enabled", text, rel)
            self.assertNotIn("try_mock_password_login", text, rel)


class AuthGateLifecycleSmokeTests(unittest.TestCase):
    """Simulate gate transitions with a Streamlit stub — no network, no PII logs."""

    def setUp(self):
        self.frames: list[str] = []

        class _Session(dict):
            def get(self, key, default=None):
                return dict.get(self, key, default)

            def pop(self, key, default=None):
                return dict.pop(self, key, default)

        self.st = MagicMock()
        self.st.session_state = _Session()
        self.st.markdown = MagicMock(
            side_effect=lambda html, **kwargs: self.frames.append(str(html))
        )
        self.st.button = MagicMock(return_value=False)
        self.st.rerun = MagicMock(side_effect=RuntimeError("rerun"))
        self.st.stop = MagicMock(side_effect=RuntimeError("stop"))
        self.st.caption = MagicMock()

        modules = {
            "streamlit": self.st,
        }
        self.patches = [
            patch.dict("sys.modules", modules),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_boot_login_authenticating_ready_never_blank(self):
        import importlib
        import sys

        sys.modules.pop("src.auth_gate", None)
        gate = importlib.import_module("src.auth_gate")

        gate.set_auth_gate_state("boot", reason="cold")
        gate.paint_auth_gate("boot")
        self.assertTrue(any('data-auth-gate="boot"' in f for f in self.frames))
        self.assertTrue(any("Restoring your session…" in f for f in self.frames))

        self.frames.clear()
        gate.set_auth_gate_state("login", reason="signed_out")
        gate.paint_auth_gate("login")
        self.assertTrue(any('data-auth-gate="login"' in f for f in self.frames))
        self.assertFalse(any("cv-startup-shell-topbar" in f for f in self.frames))

        self.frames.clear()
        gate.stash_pending_credentials("user@example.com", "secret")
        gate.set_auth_gate_state("authenticating", reason="submit")
        gate.paint_auth_gate("authenticating")
        self.assertTrue(any('data-auth-gate="authenticating"' in f for f in self.frames))
        self.assertTrue(any("Signing you in…" in f for f in self.frames))
        joined = "\n".join(self.frames)
        self.assertIn("cv-auth-gate-card", joined)
        self.assertNotIn("cv-startup-shell-topbar", joined)

        self.frames.clear()
        gate.set_auth_gate_state("ready", reason="ok")
        gate.paint_auth_gate("ready")
        self.assertEqual(self.frames, [])

        self.frames.clear()
        gate.set_auth_gate_state(
            "login",
            reason="invalid",
            error_message="Email or password is incorrect. Please try again.",
        )
        gate.paint_auth_gate("login")
        self.assertTrue(any('data-auth-gate="login"' in f for f in self.frames))
        self.assertEqual(
            gate.auth_gate_error_message(),
            "Email or password is incorrect. Please try again.",
        )
        # Login chrome is CSS-only — no intermediate brand card / raw HTML body.
        joined_login = "\n".join(self.frames)
        self.assertNotIn("cv-auth-gate-inline", joined_login)
        self.assertNotIn("<div class=\"cv-auth-gate-card\"", joined_login)


class ProductionMockEnvCannotReadyTests(unittest.TestCase):
    """Regression: arbitrary mock env vars cannot force the production gate to ready."""

    def test_env_mock_flags_do_not_exist_on_production_gate(self):
        import importlib
        import sys

        os.environ["CADIVOR_AUTH_GATE_MOCK"] = "1"
        os.environ["CADIVOR_AUTH_MOCK"] = "1"
        os.environ["AUTH_GATE_MOCK"] = "true"
        os.environ["RAILWAY_ENVIRONMENT"] = "production"
        try:
            sys.modules.pop("src.auth_gate", None)
            gate = importlib.import_module("src.auth_gate")
            self.assertFalse(hasattr(gate, "mock_auth_enabled"))
            self.assertFalse(hasattr(gate, "try_mock_password_login"))
            self.assertNotIn("CADIVOR_AUTH_GATE_MOCK", dir(gate))
        finally:
            for key in (
                "CADIVOR_AUTH_GATE_MOCK",
                "CADIVOR_AUTH_MOCK",
                "AUTH_GATE_MOCK",
                "RAILWAY_ENVIRONMENT",
            ):
                os.environ.pop(key, None)

    def test_ensure_authenticated_cannot_ready_from_mock_env_alone(self):
        """With mock env set but no valid session, gate must not become ready."""
        import importlib
        import sys
        import types

        os.environ["CADIVOR_AUTH_GATE_MOCK"] = "1"
        os.environ["RAILWAY_ENVIRONMENT"] = "production"

        st = types.ModuleType("streamlit")
        st.session_state = {}
        st.query_params = {}
        st.stop = MagicMock(side_effect=RuntimeError("stop"))
        st.rerun = MagicMock(side_effect=RuntimeError("rerun"))
        st.markdown = MagicMock()
        st.button = MagicMock(return_value=False)
        st.caption = MagicMock()
        st.cache_resource = lambda **kwargs: (lambda fn: fn)
        components = types.ModuleType("streamlit.components.v1")
        components.html = MagicMock()
        sys.modules["streamlit"] = st
        sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
        sys.modules["streamlit.components.v1"] = components

        for name in list(sys.modules):
            if name.startswith("src.auth"):
                del sys.modules[name]

        try:
            # Stub secrets/supabase so bootstrap can initialize without network.
            secrets = types.ModuleType("src.secrets")
            secrets.get_secret = lambda key, required=False, default=None: (
                "https://example.supabase.co"
                if key == "SUPABASE_URL"
                else "public-key"
            )
            secrets.get_secret_bool = lambda *a, **k: False
            sys.modules["src.secrets"] = secrets

            supabase_mod = types.ModuleType("supabase")
            client = MagicMock()
            client.auth.get_user.side_effect = Exception("no session")
            client.auth.set_session.side_effect = Exception("no session")
            supabase_mod.create_client = MagicMock(return_value=client)
            sys.modules["supabase"] = supabase_mod

            bootstrap = importlib.import_module("src.auth_bootstrap")
            gate = importlib.import_module("src.auth_gate")

            # Force signed-out path: no tokens.
            st.session_state.clear()
            st.session_state["cadivor_force_signed_out"] = True

            with patch.object(bootstrap, "show_auth_ui", MagicMock()), patch.object(
                bootstrap, "apply_auth_intent_from_query", MagicMock()
            ), patch.object(
                bootstrap, "hydrate_session_from_auth_cookie", return_value=False
            ), patch.object(
                bootstrap, "resolve_auth_state", return_value="signed_out"
            ), patch.object(
                bootstrap, "get_auth_cookie_manager", return_value=None
            ):
                try:
                    bootstrap.ensure_authenticated_or_stop()
                except RuntimeError as exc:
                    self.assertIn(str(exc), {"stop", "rerun"})

            self.assertNotEqual(gate.get_auth_gate_state(), "ready")
            self.assertNotEqual(
                str(st.session_state.get("cadivor_auth_status") or ""),
                "authenticated",
            )
        finally:
            os.environ.pop("CADIVOR_AUTH_GATE_MOCK", None)
            os.environ.pop("RAILWAY_ENVIRONMENT", None)


class DatasheetQaProgressContractTests(unittest.TestCase):
    def test_visible_progress_sequence(self):
        page = (ROOT / "src" / "pages" / "datasheet_qa.py").read_text(encoding="utf-8")
        self.assertIn("Retrieving relevant pages", page)
        self.assertIn("Ask Cadivor is analyzing the datasheet", page)
        self.assertIn("Working on your question", page)
        self.assertIn("disabled=status == STATUS_PROCESSING", page)


if __name__ == "__main__":
    unittest.main()

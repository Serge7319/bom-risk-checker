"""Sprint 74.2B.5.4 — auth-scoped Streamlit scroll-anchoring correction."""
from __future__ import annotations

import ast
import importlib
import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]
AUTH_PATH = REPO / "src" / "auth.py"
AUTH_STATE_PATH = REPO / "src" / "auth_state.py"
BOOTSTRAP_PATH = REPO / "src" / "auth_bootstrap.py"
COOKIES_PATH = REPO / "src" / "auth_cookies.py"


def _css_blocks(source: str) -> str:
    return source


class AuthScrollAnchoringSourceGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth = AUTH_PATH.read_text(encoding="utf-8")
        cls.state = AUTH_STATE_PATH.read_text(encoding="utf-8")
        cls.bootstrap = BOOTSTRAP_PATH.read_text(encoding="utf-8")
        cls.cookies = COOKIES_PATH.read_text(encoding="utf-8")

    def test_boot_css_has_scoped_stmain_overflow_anchor(self):
        self.assertIn(
            '[data-testid="stMain"]:has(.cv-auth-transition){{overflow-anchor:none}}',
            self.state,
        )
        # Exactly one boot-scoped stMain overflow-anchor rule.
        matches = re.findall(
            r'\[data-testid="stMain"\]:has\(\.cv-auth-transition\)\s*\{\{?[^}]*overflow-anchor\s*:\s*none',
            self.state,
        )
        self.assertEqual(len(matches), 1)

    def test_auth_css_has_scoped_stmain_overflow_anchor(self):
        self.assertRegex(
            self.auth,
            r'\[data-testid="stMain"\]:has\(\.st-key-cadivor_auth_card\)\s*\{\s*overflow-anchor\s*:\s*none\s*;',
        )
        matches = re.findall(
            r'\[data-testid="stMain"\]:has\(\.st-key-cadivor_auth_card\)\s*\{[^}]*overflow-anchor\s*:\s*none',
            self.auth,
        )
        self.assertEqual(len(matches), 1)

    def test_auth_css_has_scoped_main_vertical_block_gap_reset(self):
        self.assertIn(
            '[data-testid="stMain"]:has(.st-key-cadivor_auth_card)',
            self.auth,
        )
        self.assertRegex(
            self.auth,
            r'\[data-testid="stMain"\]:has\(\.st-key-cadivor_auth_card\)\s*\n\s*\[data-testid="stMainBlockContainer"\]\s*\n\s*>\s*\[data-testid="stVerticalBlock"\]\s*\{\s*gap:0!important;\s*row-gap:0!important;\s*\}',
        )
        matches = re.findall(
            r'\[data-testid="stMainBlockContainer"\]\s*>\s*\[data-testid="stVerticalBlock"\]\s*\{\s*gap:0!important;\s*row-gap:0!important;',
            self.auth,
        )
        self.assertEqual(len(matches), 1)

    def test_boot_css_has_scoped_main_vertical_block_gap_reset(self):
        self.assertRegex(
            self.state,
            r'\[data-testid="stMain"\]:has\(\.cv-auth-transition\)\s*\n\s*\[data-testid="stMainBlockContainer"\]\s*\n\s*>\s*\[data-testid="stVerticalBlock"\]\s*\{\{\s*gap:0!important;\s*row-gap:0!important;\s*\}\}',
        )
        matches = re.findall(
            r'\[data-testid="stMainBlockContainer"\]\s*>\s*\[data-testid="stVerticalBlock"\]\s*\{\{\s*gap:0!important;\s*row-gap:0!important;',
            self.state,
        )
        self.assertEqual(len(matches), 1)

    def test_no_unscoped_stmain_overflow_anchor(self):
        joined = self.auth + "\n" + self.state
        # Forbid bare stMain { overflow-anchor:none } without :has(...)
        for m in re.finditer(
            r'\[data-testid="stMain"\](?!:has)\s*\{\s*[^}]*overflow-anchor\s*:\s*none',
            joined,
        ):
            self.fail(f"unscoped stMain overflow-anchor rule found: {m.group(0)[:120]}")

    def test_no_unscoped_main_vertical_block_gap_reset(self):
        joined = self.auth + "\n" + self.state
        for m in re.finditer(
            r'\[data-testid="stMainBlockContainer"\]\s*>\s*\[data-testid="stVerticalBlock"\]\s*\{[^}]*gap:0!important',
            joined,
        ):
            context_start = max(0, m.start() - 120)
            context = joined[context_start : m.start() + 80]
            if ':has(.st-key-cadivor_auth_card)' not in context and ':has(.cv-auth-transition)' not in context:
                self.fail(f"unscoped main vertical-block gap reset found: {m.group(0)[:120]}")

    def test_no_javascript_scroll_calls(self):
        joined = "\n".join([self.auth, self.state, self.bootstrap])
        for banned in ("scrollIntoView", "window.scrollTo", "scrollTo(", "pageYOffset"):
            self.assertNotIn(banned, joined)

    def test_stable_host_contract_intact(self):
        # Sprint 75.2B: lazy host via _auth_surface(); still one st.empty() allocation site.
        self.assertIn("auth_surface_host = None", self.bootstrap)
        self.assertIn("def _auth_surface():", self.bootstrap)
        self.assertIn("auth_surface_host = st.empty()", self.bootstrap)
        self.assertIn("with _auth_surface().container():", self.bootstrap)
        self.assertIn("render_auth_boot()", self.bootstrap)
        self.assertIn("show_auth_ui", self.bootstrap)

    def test_hydration_and_cookie_manager_unchanged(self):
        self.assertIn("_MAX_HYDRATION_ATTEMPTS = 6", self.cookies)
        self.assertIn("_MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS = 0.25", self.cookies)
        self.assertIn("stx.CookieManager(key=_AUTH_COOKIE_MANAGER_COMPONENT_KEY)", self.cookies)
        self.assertNotIn("overflow-anchor", self.cookies)
        self.assertNotIn("overflow-anchor", self.bootstrap)

    def test_subtree_opt_out_merged_into_surface_layout_rules(self):
        # Complementary exclusions live on the surface layout rules (not a global stMain).
        self.assertRegex(
            self.state,
            r"\.cv-auth-transition\{\{[^}]*overflow-anchor:none",
        )
        self.assertRegex(
            self.auth,
            r"\.st-key-cadivor_auth_card\s*\{[^}]*overflow-anchor\s*:\s*none",
        )


class AuthScrollAnchoringLifecycleTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name.startswith("src.auth") or name in {
                "src.secrets",
                "src.config",
                "src.ui.core_premium_ui",
            }:
                sys.modules.pop(name, None)

        st = types.ModuleType("streamlit")
        st.session_state = {
            "cadivor_root_state": "login",
            "cadivor_auth_cookie_absent": True,
            "cadivor_auth_intent_applied": True,
        }
        st.query_params = {}
        bodies: list[str] = []

        def capture(body, **kwargs):
            bodies.append(str(body))

        st.markdown = MagicMock(side_effect=capture)
        self.bodies = bodies

        class _CM:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        st.container = MagicMock(side_effect=lambda **k: _CM())
        st.form = MagicMock(side_effect=lambda *a, **k: _CM())
        st.radio = MagicMock(return_value="Login")
        st.text_input = MagicMock(return_value="")
        st.form_submit_button = MagicMock(return_value=False)
        st.button = MagicMock(return_value=False)
        st.success = MagicMock()
        st.error = MagicMock()
        st.warning = MagicMock()
        st.checkbox = MagicMock(return_value=False)
        st.expander = MagicMock(return_value=_CM())
        st.empty = MagicMock(return_value=MagicMock(container=lambda: _CM(), empty=lambda: None))
        st.cache_resource = lambda **k: (lambda fn: fn)

        class _Ctx:
            script_run_id = "scroll-anchor-run"

        scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
        scriptrunner.get_script_run_ctx = lambda: _Ctx()
        runtime = types.ModuleType("streamlit.runtime")
        runtime.scriptrunner = scriptrunner
        sys.modules["streamlit"] = st
        sys.modules["streamlit.runtime"] = runtime
        sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
        sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
        sys.modules["streamlit.components.v1"] = types.ModuleType("streamlit.components.v1")

        secrets = types.ModuleType("src.secrets")
        secrets.get_secret = lambda *a, **k: "x"
        secrets.get_secret_bool = lambda *a, **k: False
        sys.modules["src.secrets"] = secrets
        config = types.ModuleType("src.config")
        config.CADIVOR_MARKETING_URL = "https://www.cadivor.com"
        sys.modules["src.config"] = config
        premium = types.ModuleType("src.ui.core_premium_ui")
        premium.inject_core_premium_ui_auth = lambda: None
        sys.modules.setdefault("src.ui", types.ModuleType("src.ui"))
        sys.modules["src.ui.core_premium_ui"] = premium

        self.st = st
        self.state = importlib.import_module("src.auth_state")
        self.auth = importlib.import_module("src.auth")

    def test_boot_emit_includes_scoped_anchor_rule(self):
        self.state.render_auth_boot()
        joined = "\n".join(self.bodies)
        self.assertIn('[data-testid="stMain"]:has(.cv-auth-transition)', joined)
        self.assertIn("overflow-anchor:none", joined)
        self.assertIn("gap:0!important", joined)
        self.assertIn("row-gap:0!important", joined)
        self.assertIn("cv-auth-transition", joined)
        self.assertIn("Restoring your secure workspace…", joined)

    def test_auth_css_emit_includes_scoped_anchor_rule(self):
        with patch.object(self.auth, "inject_core_premium_ui_auth"):
            self.auth.show_auth_ui(MagicMock(), None)
        joined = "\n".join(self.bodies)
        self.assertIn('[data-testid="stMain"]:has(.st-key-cadivor_auth_card)', joined)
        self.assertRegex(joined, r"overflow-anchor\s*:\s*none")
        self.assertIn("gap:0!important", joined)
        self.assertIn("row-gap:0!important", joined)
        self.assertNotIn("Restoring your secure workspace…", joined)
        self.assertEqual(
            self.st.container.call_args.kwargs.get("key"),
            self.auth.AUTH_CARD_CONTAINER_KEY,
        )

    def test_create_account_still_immediate(self):
        self.st.session_state[self.auth.AUTH_MODE_WIDGET_KEY] = self.auth.AUTH_MODE_SIGNUP
        self.st.radio = MagicMock(return_value=self.auth.AUTH_MODE_SIGNUP)
        labels: list[str] = []
        self.st.form_submit_button = MagicMock(
            side_effect=lambda label, **k: labels.append(str(label)) or False
        )
        with patch.object(self.auth, "inject_core_premium_ui_auth"):
            self.auth.show_auth_ui(MagicMock(), None)
        joined = "\n".join(self.bodies)
        self.assertIn("Terms summary", joined)
        self.assertIn(self.auth.AUTH_MODE_SIGNUP, labels)


class AuthScrollAnchoringAuthenticatedScopeGuard(unittest.TestCase):
    def test_authenticated_workspace_css_files_lack_auth_stmain_anchor(self):
        """Workspace CSS must not globally disable stMain anchoring."""
        roots = [
            REPO / "src" / "assets" / "css",
            REPO / "src" / "css",
        ]
        pattern = re.compile(
            r'\[data-testid="stMain"\](?!:has)\s*\{[^}]*overflow-anchor\s*:\s*none',
            re.S,
        )
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*.css"):
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertIsNone(
                    pattern.search(text),
                    f"unscoped stMain overflow-anchor in {path}",
                )


if __name__ == "__main__":
    unittest.main()

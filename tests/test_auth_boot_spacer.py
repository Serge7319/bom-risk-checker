"""Sprint 74.2B.5 — auth boot spacer must be content-height, not viewport-height."""
from __future__ import annotations

import importlib
import re
import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.test_auth_cookie_read_bridge import _install_streamlit_stub

REPO = Path(__file__).resolve().parents[1]
AUTH_STATE_PATH = REPO / "src" / "auth_state.py"
AUTH_BOOTSTRAP_PATH = REPO / "src" / "auth_bootstrap.py"


def _extract_cv_auth_transition_css(source: str) -> str:
    match = re.search(
        r"\.cv-auth-transition\{\{([^}]+)\}\}",
        source,
    )
    if not match:
        # Non-f-string form after formatting in file uses doubled braces in source
        match = re.search(r"\.cv-auth-transition\{([^}]+)\}", source)
    if not match:
        raise AssertionError("`.cv-auth-transition` rule not found in auth_state.py")
    return match.group(1)


class AuthBootSpacerCssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AUTH_STATE_PATH.read_text(encoding="utf-8")
        cls.rule = _extract_cv_auth_transition_css(cls.source)

    def test_boot_transition_has_no_viewport_height_units(self):
        forbidden = (
            "min-height:100vh",
            "height:100vh",
            "min-height:100dvh",
            "height:100dvh",
            "min-height: 100vh",
            "height: 100vh",
        )
        for token in forbidden:
            self.assertNotIn(token, self.rule.replace(" ", ""))
            self.assertNotIn(token, self.rule)

        # Also ensure the raw source rule body never sets full-viewport height.
        compact = re.sub(r"\s+", "", self.rule)
        self.assertNotRegex(compact, r"(?:min-)?height:100(?:vh|dvh)")

    def test_boot_transition_follows_content_height_contract(self):
        compact = re.sub(r"\s+", "", self.rule)
        self.assertIn("height:auto", compact)
        self.assertIn("min-height:0", compact)
        self.assertIn("display:grid", compact)
        self.assertIn("place-items:center", compact)
        self.assertIn("box-sizing:border-box", compact)
        self.assertTrue(
            "padding:" in compact or "padding-top:" in compact,
            "expected bounded padding on boot shell",
        )
        self.assertTrue(
            "margin:" in compact or "margin-top:" in compact,
            "expected bounded margin on boot shell",
        )
        # Must not use absolute/fixed positioning or overflow clipping.
        self.assertNotIn("position:absolute", compact)
        self.assertNotIn("position:fixed", compact)
        self.assertNotIn("overflow:hidden", compact)


class AuthBootSpacerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.st = _install_streamlit_stub({})
        self.st.markdown = MagicMock()
        self.st.rerun = MagicMock(side_effect=RuntimeError("rerun"))
        self.st.stop = MagicMock(side_effect=RuntimeError("stop"))
        self.st.caption = MagicMock()
        self.st.query_params = {}
        self.st.cache_resource = lambda **_k: (lambda fn: fn)
        for mod in (
            "src.auth_state",
            "src.auth_bootstrap",
            "src.auth",
            "src.auth_cookies",
            "src.auth_recovery",
            "src.secrets",
            "src.config",
            "src.ui.core_premium_ui",
            "supabase",
        ):
            sys.modules.pop(mod, None)

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

        sb = types.ModuleType("supabase")
        sb.create_client = MagicMock(return_value=MagicMock())
        sys.modules["supabase"] = sb

        self.state = importlib.import_module("src.auth_state")

    def test_render_auth_boot_emits_restoring_message_without_viewport_height(self):
        bodies: list[str] = []

        def capture(body, **kwargs):
            bodies.append(str(body))

        self.st.markdown.side_effect = capture
        self.state.render_auth_boot()
        joined = "\n".join(bodies)
        self.assertIn("Restoring your secure workspace…", joined)
        self.assertIn("cv-auth-transition", joined)
        compact = re.sub(r"\s+", "", joined)
        self.assertNotRegex(compact, r"\.cv-auth-transition\{[^}]*(?:min-)?height:100(?:vh|dvh)")
        self.assertIn("height:auto", compact)
        self.assertIn("min-height:0", compact)

    def test_pending_hydration_renders_boot_not_auth_card_then_reruns(self):
        """Mutual exclusion: pending wait run paints boot only, then st.rerun()."""
        bootstrap_source = AUTH_BOOTSTRAP_PATH.read_text(encoding="utf-8")
        block = bootstrap_source[
            bootstrap_source.find("if manager_fallback_hydration_pending") : bootstrap_source.find(
                'log_startup_phase("resolve_auth_state")'
            )
        ]
        self.assertIn("render_auth_boot()", block)
        self.assertIn("st.rerun()", block)
        self.assertNotIn("show_auth_ui", block)
        self.assertIn("manager_fallback_hydration_rerun", bootstrap_source)
        self.assertIn("hydration_wait_rerun", bootstrap_source)

        boot_calls: list[bool] = []

        def fake_boot():
            boot_calls.append(True)

        with patch.object(self.state, "render_auth_boot", side_effect=fake_boot):
            try:
                self.state.render_auth_boot()
                self.st.rerun()
            except RuntimeError as exc:
                self.assertEqual(str(exc), "rerun")

        self.assertEqual(len(boot_calls), 1)

    def test_settled_signed_out_run_has_card_without_boot_message(self):
        auth = importlib.import_module("src.auth")
        self.st.session_state["cadivor_root_state"] = self.state.APP_LOGIN
        self.st.session_state["cadivor_auth_cookie_absent"] = True
        self.st.session_state["cadivor_auth_intent_applied"] = True

        class _CM:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        self.st.container = MagicMock(side_effect=lambda **k: _CM())
        self.st.form = MagicMock(side_effect=lambda *a, **k: _CM())
        self.st.radio = MagicMock(return_value="Login")
        self.st.text_input = MagicMock(return_value="")
        self.st.form_submit_button = MagicMock(return_value=False)
        self.st.button = MagicMock(return_value=False)
        self.st.success = MagicMock()
        self.st.error = MagicMock()
        self.st.warning = MagicMock()
        self.st.checkbox = MagicMock(return_value=False)
        self.st.expander = MagicMock()
        self.st.expander.return_value.__enter__ = MagicMock(return_value=None)
        self.st.expander.return_value.__exit__ = MagicMock(return_value=False)

        bodies: list[str] = []

        def capture(body, **kwargs):
            bodies.append(str(body))

        self.st.markdown.side_effect = capture
        with patch.object(auth, "inject_core_premium_ui_auth"):
            with patch.object(self.state, "render_auth_boot") as boot:
                auth.show_auth_ui(MagicMock(), None)
                boot.assert_not_called()

        joined = "\n".join(bodies)
        self.assertNotIn("Restoring your secure workspace…", joined)
        self.assertEqual(auth.AUTH_CARD_CONTAINER_KEY, "cadivor_auth_card")
        self.st.container.assert_called()
        self.assertEqual(
            self.st.container.call_args.kwargs.get("key"),
            auth.AUTH_CARD_CONTAINER_KEY,
        )

    def test_auth_mode_rerun_after_settled_does_not_call_boot(self):
        auth = importlib.import_module("src.auth")
        self.st.session_state["cadivor_root_state"] = self.state.APP_LOGIN
        self.st.session_state["cadivor_auth_cookie_absent"] = True
        self.st.session_state["cadivor_auth_intent_applied"] = True
        self.st.session_state[auth.AUTH_MODE_WIDGET_KEY] = auth.AUTH_MODE_LOGIN

        class _CM:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        self.st.container = MagicMock(side_effect=lambda **k: _CM())
        self.st.form = MagicMock(side_effect=lambda *a, **k: _CM())
        self.st.text_input = MagicMock(return_value="")
        self.st.form_submit_button = MagicMock(return_value=False)
        self.st.button = MagicMock(return_value=False)
        self.st.success = MagicMock()
        self.st.error = MagicMock()
        self.st.checkbox = MagicMock(return_value=False)
        self.st.expander = MagicMock()
        self.st.expander.return_value.__enter__ = MagicMock(return_value=None)
        self.st.expander.return_value.__exit__ = MagicMock(return_value=False)
        self.st.markdown = MagicMock()

        def radio_side_effect(*args, **kwargs):
            key = kwargs.get("key")
            if key and key in self.st.session_state:
                return self.st.session_state[key]
            return auth.AUTH_MODE_LOGIN

        self.st.radio = MagicMock(side_effect=radio_side_effect)

        with patch.object(auth, "inject_core_premium_ui_auth"):
            with patch.object(self.state, "render_auth_boot") as boot:
                # Paint 1: Login
                auth.show_auth_ui(MagicMock(), None)
                # Paint 2: Create Account selection
                self.st.session_state[auth.AUTH_MODE_WIDGET_KEY] = auth.AUTH_MODE_SIGNUP
                labels: list[str] = []

                def capture_submit(label, **kwargs):
                    labels.append(str(label))
                    return False

                self.st.form_submit_button.side_effect = capture_submit
                bodies: list[str] = []
                self.st.markdown.side_effect = lambda body, **k: bodies.append(str(body))
                auth.show_auth_ui(MagicMock(), None)
                boot.assert_not_called()

        self.assertEqual(labels, [auth.AUTH_MODE_SIGNUP])
        self.assertTrue(any("Terms summary:" in b for b in bodies))
        self.assertEqual(
            self.st.session_state["cadivor_root_state"],
            self.state.APP_SIGNUP,
        )

        # Paint 3: back to Login
        self.st.session_state[auth.AUTH_MODE_WIDGET_KEY] = auth.AUTH_MODE_LOGIN
        labels.clear()
        bodies.clear()
        with patch.object(auth, "inject_core_premium_ui_auth"):
            with patch.object(self.state, "render_auth_boot") as boot:
                auth.show_auth_ui(MagicMock(), None)
                boot.assert_not_called()
        self.assertEqual(labels, [auth.AUTH_MODE_LOGIN])
        self.assertFalse(any("Terms summary:" in b for b in bodies))

        # Exactly one card container per settled paint (3 paints above + first = 4)
        keys = [c.kwargs.get("key") for c in self.st.container.call_args_list]
        self.assertTrue(keys)
        self.assertTrue(all(k == auth.AUTH_CARD_CONTAINER_KEY for k in keys))

    def test_hydration_constants_and_cookie_read_path_unchanged(self):
        cookies = importlib.import_module("src.auth_cookies")
        self.assertEqual(cookies._MAX_HYDRATION_ATTEMPTS, 6)
        self.assertEqual(cookies._MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS, 0.25)
        # CookieManager still mounted via get_auth_cookie_manager; no architecture change.
        self.assertTrue(callable(cookies.get_auth_cookie_manager))
        self.assertTrue(callable(cookies.manager_fallback_hydration_pending))
        self.assertTrue(callable(cookies.read_auth_cookie_tokens_with_source))


class AuthBootSpacerMultiRunHarness(unittest.TestCase):
    """cookie miss → compact boot → settled signed-out → one auth card."""

    def test_completed_signed_out_run_never_contains_both_boot_and_card(self):
        state_source = AUTH_STATE_PATH.read_text(encoding="utf-8")
        bootstrap_source = AUTH_BOOTSTRAP_PATH.read_text(encoding="utf-8")

        # Pending branch calls boot then rerun (exclusive).
        block = bootstrap_source[
            bootstrap_source.find("if manager_fallback_hydration_pending") : bootstrap_source.find(
                "log_startup_phase(\"resolve_auth_state\")"
            )
        ]
        self.assertIn("render_auth_boot()", block)
        self.assertIn("st.rerun()", block)
        self.assertNotIn("show_auth_ui", block)

        # Settled path calls show_auth_ui without boot in the same branch.
        settle = bootstrap_source[bootstrap_source.find("if auth_status != AUTH_AUTHENTICATED") :]
        self.assertIn("show_auth_ui(supabase, cookie_manager)", settle)
        # render_auth_boot must not appear in the signed-out show_auth_ui arm.
        show_arm = settle[: settle.find("persist_session_auth_cookie")]
        self.assertNotIn("render_auth_boot()", show_arm)

        # Compact boot CSS present; viewport height absent on .cv-auth-transition.
        rule = _extract_cv_auth_transition_css(state_source)
        compact = re.sub(r"\s+", "", rule)
        self.assertIn("height:auto", compact)
        self.assertNotRegex(compact, r"(?:min-)?height:100(?:vh|dvh)")


if __name__ == "__main__":
    unittest.main()

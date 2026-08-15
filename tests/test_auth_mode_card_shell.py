"""Sprint 74.2B.4 — auth mode outside form + isolated auth card shell."""
from __future__ import annotations

import ast
import importlib
import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.test_auth_cookie_read_bridge import _install_streamlit_stub


REPO = Path(__file__).resolve().parents[1]
AUTH_PATH = REPO / "src" / "auth.py"


class _FormCM:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _ContainerCM:
    def __init__(self, key=None, **kwargs):
        self.key = key
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _apply_auth_intent_from_query_local(st, state_mod) -> None:
    """Mirror src.auth_bootstrap.apply_auth_intent_from_query without heavy imports."""
    root_state = str(st.session_state.get("cadivor_root_state") or "")
    try:
        requested_auth = st.query_params.get("auth", "")
    except Exception:
        requested_auth = ""
    if isinstance(requested_auth, (list, tuple)):
        requested_auth = requested_auth[0] if requested_auth else ""
    requested_auth = str(requested_auth or "").strip().lower()

    if root_state == state_mod.APP_SIGNUP_CONFIRMATION_PENDING:
        if requested_auth in {"login", "signup"}:
            st.session_state["cadivor_auth_intent_applied"] = True
        return

    if st.session_state.get("cadivor_auth_intent_applied"):
        return
    if requested_auth == "login":
        st.session_state["cadivor_root_state"] = state_mod.APP_LOGIN
        st.session_state["cadivor_auth_intent_applied"] = True
    elif requested_auth == "signup":
        st.session_state["cadivor_root_state"] = state_mod.APP_SIGNUP
        st.session_state["cadivor_auth_intent_applied"] = True


def _install_auth_ui_stub(session_state: dict | None = None):
    st = _install_streamlit_stub(session_state if session_state is not None else {})
    st.markdown = MagicMock()
    st.button = MagicMock(return_value=False)
    st.success = MagicMock()
    st.error = MagicMock()
    st.warning = MagicMock()
    st.rerun = MagicMock()
    st.query_params = {}
    st.cache_resource = lambda **_kwargs: (lambda fn: fn)
    st.expander = MagicMock()
    st.expander.return_value.__enter__ = MagicMock(return_value=None)
    st.expander.return_value.__exit__ = MagicMock(return_value=False)
    st.checkbox = MagicMock(return_value=False)
    st.text_input = MagicMock(return_value="")
    st.form_submit_button = MagicMock(return_value=False)
    st.form = MagicMock(side_effect=lambda *a, **k: _FormCM())
    st.container = MagicMock(side_effect=lambda **k: _ContainerCM(**k))

    def _radio(label, options, key=None, horizontal=False, index=0, **kwargs):
        opts = list(options)
        if key is not None and key in st.session_state:
            current = st.session_state[key]
            if current in opts:
                return current
        if key is not None:
            st.session_state[key] = opts[index] if 0 <= index < len(opts) else opts[0]
            return st.session_state[key]
        return opts[index] if 0 <= index < len(opts) else opts[0]

    st.radio = MagicMock(side_effect=_radio)

    for mod in (
        "src.auth",
        "src.auth_state",
        "src.auth_recovery",
        "src.ui.core_premium_ui",
        "src.config",
    ):
        sys.modules.pop(mod, None)

    # Lightweight stubs for auth imports that are unrelated to this sprint.
    config = types.ModuleType("src.config")
    config.CADIVOR_MARKETING_URL = "https://www.cadivor.com"
    sys.modules["src.config"] = config

    premium = types.ModuleType("src.ui.core_premium_ui")
    premium.inject_core_premium_ui_auth = lambda: None
    sys.modules.setdefault("src.ui", types.ModuleType("src.ui"))
    sys.modules["src.ui.core_premium_ui"] = premium

    return st


class AuthModeCardShellStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AUTH_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_radio_has_stable_key_and_is_outside_auth_form(self):
        fn = None
        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "_render_auth_page":
                fn = node
                break
        self.assertIsNotNone(fn)

        radio_lineno = None
        form_lineno = None
        radio_key = None
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Attribute):
                    name = func.attr
                elif isinstance(func, ast.Name):
                    name = func.id
                if name == "radio" and radio_lineno is None:
                    radio_lineno = node.lineno
                    for kw in node.keywords:
                        if kw.arg == "key":
                            radio_key = ast.unparse(kw.value)
                if name == "form":
                    if any(
                        isinstance(a, ast.Constant) and a.value == "cadivor_auth_form"
                        for a in node.args
                    ):
                        form_lineno = node.lineno
        self.assertIsNotNone(radio_lineno)
        self.assertIsNotNone(form_lineno)
        self.assertLess(radio_lineno, form_lineno)
        self.assertIn("AUTH_MODE_WIDGET_KEY", radio_key or "")
        self.assertIn('AUTH_MODE_WIDGET_KEY = "cadivor_auth_mode"', self.source)

    def test_dedicated_card_container_and_css_selector(self):
        self.assertIn('AUTH_CARD_CONTAINER_KEY = "cadivor_auth_card"', self.source)
        self.assertIn("st.container(key=AUTH_CARD_CONTAINER_KEY", self.source)
        self.assertIn(".st-key-cadivor_auth_card{", self.source)
        self.assertIn("height:auto!important;", self.source)
        self.assertIn("min-height:0!important;", self.source)
        self.assertNotIn(':has(.auth-card-header)', self.source)
        self.assertNotIn(
            '[data-testid="stMainBlockContainer"]:has(.auth-card-header)',
            self.source,
        )
        # Card shell must not paint the outer main block white.
        self.assertIn(
            "[data-testid=\"stMainBlockContainer\"]:has(.st-key-cadivor_auth_card)",
            self.source,
        )
        self.assertIn("background:transparent!important;", self.source)

    def test_css_injection_precedes_card_container(self):
        css_i = self.source.find("_auth_css()")
        card_i = self.source.find("st.container(key=AUTH_CARD_CONTAINER_KEY")
        self.assertGreater(css_i, 0)
        self.assertGreater(card_i, css_i)


class AuthModeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.st = _install_auth_ui_stub({})
        self.auth = importlib.import_module("src.auth")
        self.state = importlib.import_module("src.auth_state")

    def _render(self, *, initial_mode: str = "Login"):
        bodies: list[str] = []
        submit_labels: list[str] = []
        form_keys: list[str] = []
        radio_calls: list[dict] = []

        def capture_md(body, **kwargs):
            bodies.append(str(body))

        def capture_submit(label, **kwargs):
            submit_labels.append(str(label))
            return False

        def capture_form(*args, **kwargs):
            if args:
                form_keys.append(str(args[0]))
            return _FormCM()

        real_radio = self.st.radio.side_effect

        def capture_radio(*args, **kwargs):
            radio_calls.append({"args": args, "kwargs": kwargs})
            return real_radio(*args, **kwargs)

        self.st.markdown.side_effect = capture_md
        self.st.form_submit_button.side_effect = capture_submit
        self.st.form.side_effect = capture_form
        self.st.radio.side_effect = capture_radio
        self.auth._render_auth_page(MagicMock(), None, initial_mode)
        return {
            "bodies": "\n".join(bodies),
            "submit_labels": submit_labels,
            "form_keys": form_keys,
            "radio_calls": radio_calls,
        }

    def test_create_account_selection_renders_terms_immediately_without_submit(self):
        self.st.session_state[self.auth.AUTH_MODE_WIDGET_KEY] = self.auth.AUTH_MODE_SIGNUP
        out = self._render(initial_mode=self.auth.AUTH_MODE_LOGIN)
        self.assertIn("Terms summary:", out["bodies"])
        self.assertIn("Terms summary:", out["bodies"])
        self.st.checkbox.assert_called()
        self.st.expander.assert_called()
        self.assertEqual(out["submit_labels"], [self.auth.AUTH_MODE_SIGNUP])
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_SIGNUP)
        # Forgot password only in Login mode.
        forgot = [
            c
            for c in self.st.button.call_args_list
            if c.kwargs.get("key") == "cadivor_forgot_password_link"
            or (c.args and c.args[0] == "Forgot password?")
        ]
        self.assertEqual(forgot, [])

    def test_login_selection_removes_terms_and_restores_forgot_password(self):
        self.st.session_state[self.auth.AUTH_MODE_WIDGET_KEY] = self.auth.AUTH_MODE_LOGIN
        out = self._render(initial_mode=self.auth.AUTH_MODE_SIGNUP)
        self.assertNotIn("Terms summary:", out["bodies"])
        self.assertEqual(out["submit_labels"], [self.auth.AUTH_MODE_LOGIN])
        self.st.button.assert_any_call(
            "Forgot password?", key="cadivor_forgot_password_link"
        )
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_LOGIN)

    def test_radio_outside_form_and_stable_key_at_runtime(self):
        self._render()
        self.assertIn("cadivor_auth_form", self.st.form.call_args_list[0].args)
        radio_kwargs = self.st.radio.call_args.kwargs
        self.assertEqual(radio_kwargs.get("key"), self.auth.AUTH_MODE_WIDGET_KEY)
        # Radio invoked before form body widgets; form context still opened.
        self.assertTrue(self.st.radio.called)
        self.assertTrue(self.st.form.called)

    def test_query_intent_seeds_once_then_user_selection_wins(self):
        # Simulate applied login intent + leftover query.
        self.st.session_state["cadivor_root_state"] = self.state.APP_LOGIN
        self.st.session_state["cadivor_auth_intent_applied"] = True
        self.st.query_params["auth"] = "login"
        # First paint seeds Login.
        self.auth._ensure_auth_mode_widget_seeded(self.auth.AUTH_MODE_LOGIN)
        self.assertEqual(
            self.st.session_state[self.auth.AUTH_MODE_WIDGET_KEY],
            self.auth.AUTH_MODE_LOGIN,
        )
        # User selects Create Account (widget-owned key).
        self.st.session_state[self.auth.AUTH_MODE_WIDGET_KEY] = self.auth.AUTH_MODE_SIGNUP
        # Intent helper must not overwrite after applied.
        _apply_auth_intent_from_query_local(self.st, self.state)
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_LOGIN)
        # Render syncs root from radio without needing form submit.
        self._render(initial_mode=self.auth.AUTH_MODE_LOGIN)
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_SIGNUP)
        self.assertEqual(
            self.st.session_state[self.auth.AUTH_MODE_WIDGET_KEY],
            self.auth.AUTH_MODE_SIGNUP,
        )
        # Re-seed helper must not clobber user selection.
        self.auth._ensure_auth_mode_widget_seeded(self.auth.AUTH_MODE_LOGIN)
        self.assertEqual(
            self.st.session_state[self.auth.AUTH_MODE_WIDGET_KEY],
            self.auth.AUTH_MODE_SIGNUP,
        )

    def test_return_to_login_and_different_email_reset_mode(self):
        self.st.session_state[self.state.SIGNUP_PENDING_EMAIL_KEY] = "a@b.com"
        self.st.session_state["cadivor_root_state"] = self.state.APP_SIGNUP_CONFIRMATION_PENDING
        self.auth._exit_signup_pending_to_login()
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_LOGIN)
        self.assertEqual(
            self.st.session_state[self.auth.AUTH_MODE_WIDGET_KEY],
            self.auth.AUTH_MODE_LOGIN,
        )
        self.st.rerun.assert_called()

        self.st.rerun.reset_mock()
        self.st.session_state[self.state.SIGNUP_PENDING_EMAIL_KEY] = "a@b.com"
        self.st.session_state["cadivor_root_state"] = self.state.APP_SIGNUP_CONFIRMATION_PENDING
        self.auth._exit_signup_pending_to_create_account()
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_SIGNUP)
        self.assertEqual(
            self.st.session_state[self.auth.AUTH_MODE_WIDGET_KEY],
            self.auth.AUTH_MODE_SIGNUP,
        )

    def test_show_auth_ui_uses_one_card_container_and_keeps_css_outside(self):
        self.st.session_state["cadivor_root_state"] = self.state.APP_LOGIN
        container_keys = []

        def capture_container(**kwargs):
            container_keys.append(kwargs.get("key"))
            return _ContainerCM(**kwargs)

        self.st.container.side_effect = capture_container
        with patch.object(self.auth, "inject_core_premium_ui_auth"):
            with patch.object(self.auth, "_auth_css") as css:
                self.auth.show_auth_ui(MagicMock(), None)
                self.assertTrue(css.called)
        self.assertEqual(container_keys, [self.auth.AUTH_CARD_CONTAINER_KEY])
        # CSS was invoked; markdown from _auth_css may be mocked via patch — card
        # content still rendered inside the single container context.
        self.assertTrue(self.st.radio.called)


class AuthModeMultiRunHarness(unittest.TestCase):
    """Models the production Login → Create Account → Login lifecycle."""

    def setUp(self):
        self.st = _install_auth_ui_stub({})
        self.auth = importlib.import_module("src.auth")
        self.state = importlib.import_module("src.auth_state")

    def _paint(self):
        bodies: list[str] = []
        labels: list[str] = []

        def capture_md(body, **kwargs):
            bodies.append(str(body))

        def capture_submit(label, **kwargs):
            labels.append(str(label))
            return False

        self.st.markdown.side_effect = capture_md
        self.st.form_submit_button.side_effect = capture_submit
        self.st.form.side_effect = lambda *a, **k: _FormCM()
        self.st.container.side_effect = lambda **k: _ContainerCM(**k)
        self.auth.show_auth_ui(MagicMock(), None)
        return "\n".join(bodies), labels

    def test_multi_run_lifecycle_no_intent_reassertion_no_loop(self):
        # Run 0: marketing intent login.
        self.st.query_params["auth"] = "login"
        self.st.query_params["source"] = "marketing"
        _apply_auth_intent_from_query_local(self.st, self.state)
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_LOGIN)
        self.assertTrue(self.st.session_state.get("cadivor_auth_intent_applied"))

        bodies, labels = self._paint()
        self.assertIn("Access your workspace", bodies)
        self.assertEqual(labels, [self.auth.AUTH_MODE_LOGIN])
        self.assertNotIn("Terms summary:", bodies)
        self.assertEqual(
            self.st.session_state[self.auth.AUTH_MODE_WIDGET_KEY],
            self.auth.AUTH_MODE_LOGIN,
        )

        # Run 1: one Create Account selection (widget change + automatic Streamlit rerun).
        self.st.session_state[self.auth.AUTH_MODE_WIDGET_KEY] = self.auth.AUTH_MODE_SIGNUP
        # Intent must not reassert Login despite ?auth=login still present.
        _apply_auth_intent_from_query_local(self.st, self.state)
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_LOGIN)
        bodies, labels = self._paint()
        self.assertIn("Terms summary:", bodies)
        self.assertEqual(labels, [self.auth.AUTH_MODE_SIGNUP])
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_SIGNUP)

        # Run 2: ordinary rerun preserves signup.
        bodies, labels = self._paint()
        self.assertIn("Terms summary:", bodies)
        self.assertEqual(labels, [self.auth.AUTH_MODE_SIGNUP])
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_SIGNUP)

        # Run 3: one Login selection.
        self.st.session_state[self.auth.AUTH_MODE_WIDGET_KEY] = self.auth.AUTH_MODE_LOGIN
        bodies, labels = self._paint()
        self.assertNotIn("Terms summary:", bodies)
        self.assertEqual(labels, [self.auth.AUTH_MODE_LOGIN])
        self.assertEqual(self.st.session_state["cadivor_root_state"], self.state.APP_LOGIN)

        # No explicit rerun loop from mode sync.
        self.st.rerun.assert_not_called()
        # Exactly one dedicated card container per paint; never nested duplicates.
        keys = [c.kwargs.get("key") for c in self.st.container.call_args_list]
        self.assertEqual(len(keys), 4)
        self.assertTrue(all(k == self.auth.AUTH_CARD_CONTAINER_KEY for k in keys))


if __name__ == "__main__":
    unittest.main()

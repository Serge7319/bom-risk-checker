"""Sprint 74.2B.5.2 — stable authentication surface host (st.empty slot)."""
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
BOOTSTRAP_PATH = REPO / "src" / "auth_bootstrap.py"
AUTH_PATH = REPO / "src" / "auth.py"
AUTH_COOKIES_PATH = REPO / "src" / "auth_cookies.py"
AUTH_STATE_PATH = REPO / "src" / "auth_state.py"


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _AuthSurfaceHost:
    """Tracks fill/clear of the stable auth surface placeholder."""

    created: list["_AuthSurfaceHost"] = []

    def __init__(self):
        type(self).created.append(self)
        self.container_enters = 0
        self.cleared = 0
        self.events: list[str] = []

    def container(self, *args, **kwargs):
        host = self

        class _Ctx(_NullContext):
            def __enter__(inner_self):
                host.container_enters += 1
                host.events.append("container_enter")
                return inner_self

            def __exit__(inner_self, *a):
                host.events.append("container_exit")
                return False

        return _Ctx()

    def empty(self):
        self.cleared += 1
        self.events.append("empty_clear")
        return self


def _install_streamlit_stub(session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    st.query_params = {}
    st.stop = MagicMock(side_effect=RuntimeError("stop"))
    st.rerun = MagicMock(side_effect=RuntimeError("rerun"))
    st.markdown = MagicMock()
    st.caption = MagicMock()
    st.container = MagicMock(side_effect=lambda **k: _NullContext())
    st.form = MagicMock(side_effect=lambda *a, **k: _NullContext())
    st.radio = MagicMock(return_value="Login")
    st.text_input = MagicMock(return_value="")
    st.form_submit_button = MagicMock(return_value=False)
    st.button = MagicMock(return_value=False)
    st.success = MagicMock()
    st.error = MagicMock()
    st.warning = MagicMock()
    st.checkbox = MagicMock(return_value=False)
    st.expander = MagicMock(return_value=_NullContext())

    _AuthSurfaceHost.created = []

    def _empty():
        return _AuthSurfaceHost()

    st.empty = MagicMock(side_effect=_empty)

    def cache_resource(**_kwargs):
        def decorator(fn):
            return fn

        return decorator

    st.cache_resource = cache_resource

    class _Ctx:
        script_run_id = "surface-host-run"

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = lambda: _Ctx()
    runtime = types.ModuleType("streamlit.runtime")
    runtime.scriptrunner = scriptrunner
    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
    components = types.ModuleType("streamlit.components.v1")
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st


def _purge_auth_modules() -> None:
    for name in list(sys.modules):
        if name.startswith("src.auth") or name in {
            "src.secrets",
            "src.config",
            "src.ui.core_premium_ui",
            "supabase",
            "extra_streamlit_components",
        }:
            sys.modules.pop(name, None)


class AuthSurfaceHostSourceGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bootstrap = BOOTSTRAP_PATH.read_text(encoding="utf-8")
        cls.auth = AUTH_PATH.read_text(encoding="utf-8")
        cls.cookies = AUTH_COOKIES_PATH.read_text(encoding="utf-8")
        cls.state = AUTH_STATE_PATH.read_text(encoding="utf-8")

    def test_single_st_empty_in_ensure_authenticated(self):
        tree = ast.parse(self.bootstrap)
        fn = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "ensure_authenticated_or_stop"
        )
        empty_calls = []
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "empty"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "st"
            ):
                empty_calls.append(node)
        self.assertEqual(len(empty_calls), 1, "exactly one st.empty() in ensure_authenticated_or_stop")

    def test_host_created_before_cookie_read_and_hydration(self):
        src = self.bootstrap
        fn = src[src.find("def ensure_authenticated_or_stop") :]
        empty_idx = fn.find("auth_surface_host = st.empty()")
        cookie_idx = fn.find("read_auth_cookie_tokens_with_source(")
        boot_idx = fn.find("render_auth_boot()")
        show_idx = fn.find("with auth_surface_host.container():\n            show_auth_ui")
        self.assertGreater(empty_idx, 0)
        self.assertGreater(cookie_idx, empty_idx)
        self.assertGreater(boot_idx, empty_idx)
        self.assertGreater(show_idx, empty_idx)

    def test_boot_and_auth_ui_render_inside_host_container(self):
        # Both hydration arms and signed-out arm use the host container.
        self.assertGreaterEqual(self.bootstrap.count("with auth_surface_host.container():"), 3)
        self.assertIn(
            "with auth_surface_host.container():\n                    render_auth_boot()",
            self.bootstrap,
        )
        self.assertIn("with auth_surface_host.container():\n            show_auth_ui", self.bootstrap)
        # Every render_auth_boot() in ensure_authenticated is nested under the host.
        for match in re.finditer(r"render_auth_boot\(\)", self.bootstrap):
            window = self.bootstrap[max(0, match.start() - 120) : match.start()]
            self.assertIn(
                "auth_surface_host.container()",
                window,
                "render_auth_boot must execute inside auth_surface_host.container()",
            )

    def test_authenticated_path_mounts_progress_without_blank_clear(self):
        """Authenticated path must remount progress — never empty() to blank."""
        self.assertIn("mount_auth_progress_surface(auth_surface_host)", self.bootstrap)
        boundary = self.bootstrap.find('log_startup_phase("auth_boundary_passed")')
        auth_path = self.bootstrap[
            self.bootstrap.find("if auth_status != AUTH_AUTHENTICATED:") : boundary
        ]
        # Logout may still empty; authenticated fall-through must not.
        self.assertNotIn("auth_surface_host.empty()", auth_path)
        self.assertIn("mount_auth_progress_surface(auth_surface_host)", auth_path)
        self.assertIn("continue_authenticated", auth_path)

    def test_hydration_config_unchanged(self):
        cookies = self.cookies
        self.assertIn("_MAX_HYDRATION_ATTEMPTS = 6", cookies)
        self.assertIn("_MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS = 0.25", cookies)
        self.assertIn("time.sleep(_MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS)", self.bootstrap)
        self.assertIn("st.rerun()", self.bootstrap)

    def test_no_deltagenerator_in_session_state(self):
        joined = "\n".join([self.bootstrap, self.auth, self.cookies, self.state])
        self.assertNotIn("session_state[\"auth_surface", joined)
        self.assertNotIn("session_state['auth_surface", joined)
        self.assertNotRegex(joined, r"session_state\[.auth_surface_host.\]")

    def test_no_scroll_or_global_stale_hacks(self):
        joined = "\n".join([self.bootstrap, self.auth, self.state])
        for banned in (
            "scrollIntoView",
            "window.scrollTo",
            "scrollTo(",
            "iframe{display:none",
            "stCustomComponentV1{display:none",
        ):
            self.assertNotIn(banned, joined)
        # A startup-shell-only stale selector is allowed to keep that visual
        # handoff opaque. Never suppress or restyle stale elements globally.
        self.assertNotIn("[data-stale]{", joined)
        self.assertIn("[data-stale]:has(.cv-startup-shell)", self.bootstrap)

    def test_auth_cookies_module_untouched_by_this_sprint_marker(self):
        # Behavioral invariants: CookieManager still constructed only in auth_cookies.
        self.assertIn("stx.CookieManager(key=_AUTH_COOKIE_MANAGER_COMPONENT_KEY)", self.cookies)
        self.assertNotIn("auth_surface_host", self.cookies)


class AuthSurfaceHostLifecycleTests(unittest.TestCase):
    def setUp(self):
        _purge_auth_modules()
        self.st = _install_streamlit_stub({})

        from tests.secrets_module_isolation import install_src_secrets_stub
        _secrets, restore_secrets = install_src_secrets_stub(
            get_secret=lambda *a, **k: "x",
            get_secret_bool=lambda *a, **k: False,
            ConfigurationError=RuntimeError,
        )
        self.addCleanup(restore_secrets)

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

        diagnostics = types.ModuleType("src.auth_diagnostics")
        diagnostics.log_auth_correlation = MagicMock()
        diagnostics.log_auth_bounce = MagicMock()
        sys.modules["src.auth_diagnostics"] = diagnostics

        recovery = types.ModuleType("src.auth_recovery")
        recovery.apply_password_recovery_from_query = MagicMock()
        recovery.password_recovery_active = MagicMock(return_value=False)
        recovery._RECOVERY_NOTICE_KEY = "cadivor_recovery_notice"
        sys.modules["src.auth_recovery"] = recovery

        # Lightweight cookies module for bootstrap import surface.
        cookies = types.ModuleType("src.auth_cookies")
        cookies._MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS = 0.25
        cookies._MAX_HYDRATION_ATTEMPTS = 6
        cookies.auth_cookie_hydration_pending = MagicMock(return_value=False)
        cookies.finalize_auth_cookie_hydration_timeout = MagicMock()
        cookies.finalize_manager_fallback_hydration_timeout = MagicMock()
        cookies.get_auth_cookie_manager = MagicMock(return_value=None)
        cookies.hydrate_session_from_auth_cookie = MagicMock(return_value=False)
        cookies.log_auth_restore = MagicMock()
        cookies.manager_fallback_hydration_pending = MagicMock(return_value=False)
        cookies.persist_session_auth_cookie = MagicMock()
        cookies.record_auth_hydration_attempt = MagicMock(return_value=1)
        cookies.native_cookie_api_available = MagicMock(return_value=True)
        cookies.read_auth_cookie_tokens_with_source = MagicMock(return_value=(None, "none"))
        sys.modules["src.auth_cookies"] = cookies
        self.cookies = cookies

        auth = types.ModuleType("src.auth")
        auth.show_auth_ui = MagicMock()
        sys.modules["src.auth"] = auth
        self.auth = auth

        # Import real auth_state for constants + render_auth_boot, but patch render.
        sys.modules.pop("src.auth_state", None)
        self.state = importlib.import_module("src.auth_state")

        sys.modules.pop("src.auth_bootstrap", None)
        # Re-bind bootstrap imports: auth_bootstrap imports show_auth_ui and render_auth_boot at load.
        self.bootstrap = importlib.import_module("src.auth_bootstrap")

    def _run_until(self, exc_name: str):
        try:
            self.bootstrap.ensure_authenticated_or_stop()
        except RuntimeError as exc:
            self.assertEqual(str(exc), exc_name)
        else:
            self.fail(f"expected RuntimeError({exc_name!r})")

    def test_one_host_created_per_script_run(self):
        with patch.object(self.bootstrap, "resolve_auth_state", return_value=self.state.AUTH_SIGNED_OUT):
            self._run_until("stop")
        self.assertEqual(self.st.empty.call_count, 1)
        self.assertEqual(len(_AuthSurfaceHost.created), 1)

    def test_hydration_pending_boot_inside_host_no_auth_card(self):
        boot = MagicMock()
        with patch.object(self.bootstrap, "manager_fallback_hydration_pending", return_value=True):
            with patch.object(self.bootstrap, "record_auth_hydration_attempt", return_value=1):
                with patch.object(self.bootstrap, "render_auth_boot", boot):
                    with patch.object(self.bootstrap.time, "sleep") as sleep:
                        self._run_until("rerun")
                        sleep.assert_called_once_with(0.25)
        boot.assert_called_once()
        self.auth.show_auth_ui.assert_not_called()
        host = _AuthSurfaceHost.created[0]
        self.assertEqual(host.container_enters, 1)
        self.assertEqual(host.cleared, 0)

    def test_settled_signed_out_auth_ui_inside_same_host_no_boot(self):
        boot = MagicMock()
        with patch.object(self.bootstrap, "render_auth_boot", boot):
            with patch.object(self.bootstrap, "resolve_auth_state", return_value=self.state.AUTH_SIGNED_OUT):
                self._run_until("stop")
        boot.assert_not_called()
        self.auth.show_auth_ui.assert_called_once()
        host = _AuthSurfaceHost.created[0]
        self.assertEqual(host.container_enters, 1)
        self.assertEqual(self.st.empty.call_count, 1)

    def test_authenticated_mounts_progress_without_blank_clear(self):
        with patch.object(self.bootstrap, "resolve_auth_state", return_value=self.state.AUTH_AUTHENTICATED):
            self.bootstrap.ensure_authenticated_or_stop()
        self.auth.show_auth_ui.assert_not_called()
        host = _AuthSurfaceHost.created[0]
        self.assertEqual(host.cleared, 0)
        self.assertGreaterEqual(host.container_enters, 1)
        self.cookies.persist_session_auth_cookie.assert_called()
        self.assertTrue(
            self.st.session_state.get(self.bootstrap.AUTH_PROGRESS_MOUNTED_KEY)
        )

    def test_mode_switch_settled_no_boot_one_host(self):
        """Login/Create Account settled path: host once, auth UI once, no boot."""
        self.st.session_state["cadivor_auth_cookie_absent"] = True
        self.st.session_state["cadivor_auth_restore_attempts"] = 6
        boot = MagicMock()
        with patch.object(self.bootstrap, "render_auth_boot", boot):
            with patch.object(self.bootstrap, "resolve_auth_state", return_value=self.state.AUTH_SIGNED_OUT):
                self._run_until("stop")
        boot.assert_not_called()
        self.assertEqual(self.st.empty.call_count, 1)
        self.auth.show_auth_ui.assert_called_once()

    def test_recovery_route_uses_same_host(self):
        sys.modules["src.auth_recovery"].password_recovery_active = MagicMock(return_value=True)
        self._run_until("stop")
        self.auth.show_auth_ui.assert_called_once()
        host = _AuthSurfaceHost.created[0]
        self.assertEqual(host.container_enters, 1)
        self.assertEqual(self.st.empty.call_count, 1)

    def test_six_attempts_and_quarter_second_wait_still_wired(self):
        self.assertEqual(self.cookies._MAX_HYDRATION_ATTEMPTS, 6)
        self.assertEqual(self.cookies._MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS, 0.25)
        with patch.object(self.bootstrap, "manager_fallback_hydration_pending", return_value=True):
            with patch.object(self.bootstrap, "record_auth_hydration_attempt", return_value=2):
                with patch.object(self.bootstrap, "render_auth_boot"):
                    with patch.object(self.bootstrap.time, "sleep") as sleep:
                        self._run_until("rerun")
                        sleep.assert_called_once_with(0.25)


class AuthSurfaceHostCardAndModeTests(unittest.TestCase):
    """Real show_auth_ui path: card key + immediate mode (no bootstrap host needed)."""

    def setUp(self):
        _purge_auth_modules()
        self.st = _install_streamlit_stub(
            {
                "cadivor_root_state": "login",
                "cadivor_auth_cookie_absent": True,
                "cadivor_auth_intent_applied": True,
            }
        )
        from tests.secrets_module_isolation import install_src_secrets_stub
        _secrets, restore_secrets = install_src_secrets_stub(
            get_secret=lambda *a, **k: "x",
            get_secret_bool=lambda *a, **k: False,
            ConfigurationError=RuntimeError,
        )
        self.addCleanup(restore_secrets)
        config = types.ModuleType("src.config")
        config.CADIVOR_MARKETING_URL = "https://www.cadivor.com"
        sys.modules["src.config"] = config
        premium = types.ModuleType("src.ui.core_premium_ui")
        premium.inject_core_premium_ui_auth = lambda: None
        sys.modules.setdefault("src.ui", types.ModuleType("src.ui"))
        sys.modules["src.ui.core_premium_ui"] = premium
        recovery = types.ModuleType("src.auth_recovery")
        recovery.password_recovery_active = MagicMock(return_value=False)
        recovery._RECOVERY_NOTICE_KEY = "cadivor_recovery_notice"
        sys.modules["src.auth_recovery"] = recovery
        self.auth = importlib.import_module("src.auth")
        self.state = importlib.import_module("src.auth_state")

    def test_exactly_one_auth_card_key_on_settled_ui(self):
        card_keys: list[str] = []

        def capture_container(**kwargs):
            key = kwargs.get("key")
            if key:
                card_keys.append(str(key))
            return _NullContext()

        self.st.container = MagicMock(side_effect=capture_container)
        with patch.object(self.auth, "inject_core_premium_ui_auth"):
            self.auth.show_auth_ui(MagicMock(), None)
        self.assertEqual(card_keys.count("cadivor_auth_card"), 1)

    def test_create_account_shows_terms_immediately(self):
        self.st.session_state[self.auth.AUTH_MODE_WIDGET_KEY] = self.auth.AUTH_MODE_SIGNUP
        bodies: list[str] = []
        self.st.markdown = MagicMock(side_effect=lambda b, **k: bodies.append(str(b)))
        labels: list[str] = []

        def submit(label, **kwargs):
            labels.append(str(label))
            return False

        self.st.form_submit_button = MagicMock(side_effect=submit)
        self.st.radio = MagicMock(return_value=self.auth.AUTH_MODE_SIGNUP)
        with patch.object(self.auth, "inject_core_premium_ui_auth"):
            self.auth.show_auth_ui(MagicMock(), None)
        joined = "\n".join(bodies)
        self.assertIn("Terms summary", joined)
        self.assertIn(self.auth.AUTH_MODE_SIGNUP, labels)

    def test_login_mode_shows_login_immediately(self):
        self.st.session_state[self.auth.AUTH_MODE_WIDGET_KEY] = self.auth.AUTH_MODE_LOGIN
        self.st.radio = MagicMock(return_value=self.auth.AUTH_MODE_LOGIN)
        atomic_calls: list[dict] = []

        def capture_atomic_login(**kwargs):
            atomic_calls.append(dict(kwargs))
            return None

        with patch.object(self.auth, "inject_core_premium_ui_auth"), patch.object(
            self.auth, "render_atomic_login", side_effect=capture_atomic_login
        ):
            self.auth.show_auth_ui(MagicMock(), None)
        self.assertEqual(len(atomic_calls), 1)
        self.assertEqual(atomic_calls[0].get("submit_label"), self.auth.AUTH_MODE_LOGIN)
        self.assertNotIn(
            "Terms summary",
            "\n".join(str(c) for c in self.st.markdown.call_args_list),
        )


class AuthSurfaceHostMultiRunHarness(unittest.TestCase):
    def test_host_order_relative_to_cookie_manager_call_site(self):
        """Prove empty precedes cookie token read in source control flow."""
        src = BOOTSTRAP_PATH.read_text(encoding="utf-8")
        fn_start = src.find("def ensure_authenticated_or_stop")
        fn_body = src[fn_start:]
        empty = fn_body.find("auth_surface_host = st.empty()")
        cookie = fn_body.find("read_auth_cookie_tokens_with_source(")
        manager_pending = fn_body.find("manager_fallback_hydration_pending(")
        self.assertLess(empty, cookie)
        self.assertLess(empty, manager_pending)


if __name__ == "__main__":
    unittest.main()

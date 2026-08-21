"""Sprint 75.1 — performance timing helper and privacy guards."""
from __future__ import annotations

import importlib
import io
import json
import os
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]


class PerformanceTimingHelperTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("src.performance_timing", None)
        self.mod = importlib.import_module("src.performance_timing")
        self._env_backup = os.environ.get("CADIVOR_STARTUP_TIMING")
        os.environ.pop("CADIVOR_STARTUP_TIMING", None)

    def tearDown(self):
        if self._env_backup is None:
            os.environ.pop("CADIVOR_STARTUP_TIMING", None)
        else:
            os.environ["CADIVOR_STARTUP_TIMING"] = self._env_backup
        sys.modules.pop("src.performance_timing", None)

    def _enable(self):
        os.environ["CADIVOR_STARTUP_TIMING"] = "1"

    def test_disabled_means_no_timing_log(self):
        os.environ["CADIVOR_STARTUP_TIMING"] = "0"
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.mod.timed_phase("auth.test"):
                pass
            self.mod.emit_timing("auth.test", duration_ms=12.3)
        self.assertNotIn("CADIVOR_PERF", buf.getvalue())

    def test_enabled_emits_stable_structured_json(self):
        self._enable()
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.mod.emit_timing(
                "auth.cookie_hydration",
                duration_ms=251.4,
                outcome="success",
                attempt=2,
                max_attempts=6,
            )
        line = buf.getvalue().strip()
        self.assertTrue(line.startswith("CADIVOR_PERF "))
        payload = json.loads(line[len("CADIVOR_PERF ") :])
        self.assertEqual(payload["event"], "phase_complete")
        self.assertEqual(payload["phase"], "auth.cookie_hydration")
        self.assertEqual(payload["duration_ms"], 251.4)
        self.assertEqual(payload["outcome"], "success")
        self.assertEqual(payload["attempt"], 2)
        self.assertEqual(payload["max_attempts"], 6)
        self.assertIn("deploy", payload)

    def test_success_duration_and_exception_reraise(self):
        self._enable()
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.mod.timed_phase("auth.demo"):
                pass
        payload = json.loads(buf.getvalue().strip().split(" ", 1)[1])
        self.assertEqual(payload["outcome"], "success")
        self.assertGreaterEqual(payload["duration_ms"], 0.0)

        buf2 = io.StringIO()
        with self.assertRaises(RuntimeError), redirect_stdout(buf2):
            with self.mod.timed_phase("auth.demo"):
                raise RuntimeError("secret boom token=abc email=a@b.com")
        line = buf2.getvalue().strip()
        self.assertIn("CADIVOR_PERF", line)
        self.assertNotIn("secret boom", line)
        self.assertNotIn("token=abc", line)
        self.assertNotIn("a@b.com", line)
        payload = json.loads(line.split(" ", 1)[1])
        self.assertEqual(payload["outcome"], "error")

    def test_route_provider_allowlisting(self):
        self.assertEqual(self.mod.normalize_route("Dashboard"), "dashboard")
        self.assertEqual(self.mod.normalize_route("BOM Analyzer"), "bom_analyzer")
        self.assertEqual(self.mod.normalize_route("totally-new-page"), "unknown")
        self.assertEqual(self.mod.normalize_provider("Mouser"), "mouser")
        self.assertEqual(self.mod.normalize_provider("DigiKey"), "digikey")
        self.assertEqual(self.mod.normalize_provider("Acme"), "unknown")

    def test_deployment_version_allowlist_only(self):
        with patch.dict(os.environ, {"RAILWAY_GIT_COMMIT_SHA": "abcdef1234567890"}, clear=False):
            self.assertEqual(self.mod.deployment_version(), "abcdef123456")
        with patch.dict(os.environ, {"SECRET_TOKEN": "nope"}, clear=False):
            # Does not read SECRET_TOKEN
            ver = self.mod.deployment_version()
            self.assertNotEqual(ver, "nope")

    def test_malformed_flag_treated_as_disabled(self):
        os.environ["CADIVOR_STARTUP_TIMING"] = "maybe"
        self.assertFalse(self.mod.timing_enabled())

    def test_instrumentation_failure_cannot_break_work(self):
        self._enable()
        ran = []
        with patch.object(self.mod, "emit_timing", side_effect=RuntimeError("log fail")):
            with self.mod.timed_phase("auth.demo"):
                ran.append(1)
        self.assertEqual(ran, [1])

    def test_no_environment_dump_in_logs(self):
        self._enable()
        os.environ["SUPABASE_KEY"] = "super-secret-key-value"
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.mod.emit_timing("auth.demo", duration_ms=1.0, outcome="success")
        out = buf.getvalue()
        self.assertNotIn("super-secret-key-value", out)
        self.assertNotIn("SUPABASE_KEY", out)
        os.environ.pop("SUPABASE_KEY", None)


class PerformanceTimingSecurityTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("src.performance_timing", None)
        self.mod = importlib.import_module("src.performance_timing")
        os.environ["CADIVOR_STARTUP_TIMING"] = "1"

    def tearDown(self):
        os.environ.pop("CADIVOR_STARTUP_TIMING", None)
        sys.modules.pop("src.performance_timing", None)

    def test_forbidden_fixtures_do_not_appear(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            # Callers must not pass these; ensure helper ignores unknown kwargs.
            self.mod.emit_timing(
                "auth.demo",
                duration_ms=1.0,
                outcome="success",
                email="user@example.com",
                access_token="tok_live_abc",
                part_number="LM358",
                password="hunter2",
                filter="user_id=eq.123",
            )
        out = buf.getvalue()
        for banned in (
            "user@example.com",
            "tok_live_abc",
            "LM358",
            "hunter2",
            "user_id=eq.123",
        ):
            self.assertNotIn(banned, out)

    def test_raw_exception_text_not_logged(self):
        buf = io.StringIO()
        with self.assertRaises(ValueError), redirect_stdout(buf):
            with self.mod.timed_phase("supabase.read"):
                raise ValueError("SELECT * FROM users WHERE email='x@y.com'")
        self.assertNotIn("x@y.com", buf.getvalue())
        self.assertNotIn("SELECT", buf.getvalue())


class PerformanceTimingSourceGuards(unittest.TestCase):
    def test_no_new_sleep_or_rerun_or_network_in_helper(self):
        src = (REPO / "src" / "performance_timing.py").read_text(encoding="utf-8")
        self.assertNotIn("time.sleep", src)
        self.assertNotIn("st.rerun", src)
        self.assertNotIn("requests.", src)
        self.assertNotIn("create_client", src)

    def test_hydration_constants_unchanged(self):
        cookies = (REPO / "src" / "auth_cookies.py").read_text(encoding="utf-8")
        self.assertIn("_MAX_HYDRATION_ATTEMPTS = 6", cookies)
        self.assertIn("_MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS = 0.25", cookies)

    def test_bootstrap_still_sleeps_and_reruns_same_way(self):
        boot = (REPO / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("time.sleep(_MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS)", boot)
        self.assertIn("st.rerun()", boot)
        self.assertIn("timed_phase", boot)
        self.assertIn("apply_signup_confirmation_from_query", boot)
        self.assertIn("apply_password_recovery_from_query", boot)

    def test_a1_not_introduced_in_committed_auth(self):
        auth = (REPO / "src" / "auth.py").read_text(encoding="utf-8")
        idx_login = auth.find("if state in (APP_LOGIN, APP_SIGNUP):")
        a1 = "if recovery.password_recovery_active() or state == APP_PASSWORD_RECOVERY:"
        self.assertTrue(idx_login > 0)
        self.assertTrue(auth.find(a1) < 0 or auth.find(a1) > idx_login)


class SupabaseReadTimingTests(unittest.TestCase):
    def setUp(self):
        os.environ["CADIVOR_STARTUP_TIMING"] = "1"
        for name in list(sys.modules):
            if name.startswith("src.supabase_read") or name.startswith("src.performance_timing"):
                sys.modules.pop(name, None)
        self.read = importlib.import_module("src.supabase_read")

    def tearDown(self):
        os.environ.pop("CADIVOR_STARTUP_TIMING", None)

    def test_success_timing_no_result_leakage(self):
        builder = MagicMock()
        builder.execute.return_value = types.SimpleNamespace(
            data=[{"email": "secret@cadivor.com", "id": "u1"}]
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.read.execute_supabase_read(builder, operation="load_user_data")
        out = buf.getvalue()
        self.assertIn("CADIVOR_PERF", out)
        self.assertNotIn("secret@cadivor.com", out)
        self.assertNotIn("u1", out)
        payload = json.loads([ln for ln in out.splitlines() if ln.startswith("CADIVOR_PERF")][0].split(" ", 1)[1])
        self.assertEqual(payload["outcome"], "success")
        self.assertEqual(payload["row_count_bucket"], "1_10")

    def test_retries_unchanged(self):
        import httpx

        builder = MagicMock()
        builder.execute.side_effect = [
            httpx.ConnectError("x"),
            httpx.ConnectError("x"),
            types.SimpleNamespace(data=[]),
        ]
        with patch("src.supabase_read.time.sleep") as sleep_mock:
            result = self.read.execute_supabase_read(builder, attempts=3, operation="supabase_read")
        self.assertEqual(result.data, [])
        self.assertEqual(builder.execute.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 2)


class SupplierTimingTests(unittest.TestCase):
    def setUp(self):
        os.environ["CADIVOR_STARTUP_TIMING"] = "1"
        sys.modules.pop("integrations.supplier_aggregator", None)
        sys.modules.pop("src.performance_timing", None)

    def tearDown(self):
        os.environ.pop("CADIVOR_STARTUP_TIMING", None)

    def test_mocked_lookup_emits_safe_timing_without_part_number(self):
        # Avoid importing streamlit-heavy module path issues by loading aggregator carefully.
        st = types.ModuleType("streamlit")
        st.cache_data = lambda **k: (lambda f: f)
        sys.modules.setdefault("streamlit", st)
        agg = importlib.import_module("integrations.supplier_aggregator")

        def lookup(_part):
            return {
                "manufacturer_part_number": "LM358",
                "stock_total": 1,
            }

        buf = io.StringIO()
        with redirect_stdout(buf):
            result = agg._safe_supplier_lookup("Mouser", lookup, "LM358DR")
        out = buf.getvalue()
        self.assertEqual(result.get("provider_status"), agg.PROVIDER_AVAILABLE)
        self.assertIn("CADIVOR_PERF", out)
        self.assertNotIn("LM358DR", out)
        # manufacturer_part_number may exist in result object but must not be printed by timing
        perf_lines = [ln for ln in out.splitlines() if ln.startswith("CADIVOR_PERF")]
        self.assertTrue(perf_lines)
        self.assertNotIn("LM358", perf_lines[0])

    def test_disabled_path_no_extra_provider_call(self):
        os.environ["CADIVOR_STARTUP_TIMING"] = "0"
        st = types.ModuleType("streamlit")
        st.cache_data = lambda **k: (lambda f: f)
        sys.modules["streamlit"] = st
        sys.modules.pop("integrations.supplier_aggregator", None)
        agg = importlib.import_module("integrations.supplier_aggregator")
        calls = []

        def lookup(part):
            calls.append(part)
            return {"manufacturer_part_number": "X", "stock_total": 1}

        buf = io.StringIO()
        with redirect_stdout(buf):
            agg._safe_supplier_lookup("Mouser", lookup, "ABC")
        self.assertEqual(calls, ["ABC"])
        self.assertNotIn("CADIVOR_PERF", buf.getvalue())


def _streamlit_control_exceptions():
    from streamlit.runtime.scriptrunner_utils.exceptions import (
        RerunException,
        StopException,
    )
    from streamlit.runtime.scriptrunner_utils.script_requests import RerunData

    return RerunException, StopException, RerunData


class TimedPhaseStreamlitControlFlowTests(unittest.TestCase):
    """Sprint 75.1.2 — finally must not suppress Streamlit control exceptions."""

    def setUp(self):
        sys.modules.pop("src.performance_timing", None)
        self.mod = importlib.import_module("src.performance_timing")
        self._env_backup = os.environ.get("CADIVOR_STARTUP_TIMING")
        self.RerunException, self.StopException, self.RerunData = (
            _streamlit_control_exceptions()
        )
        self.assertFalse(issubclass(self.RerunException, Exception))
        self.assertFalse(issubclass(self.StopException, Exception))
        self.assertTrue(issubclass(self.RerunException, BaseException))
        self.assertTrue(issubclass(self.StopException, BaseException))

    def tearDown(self):
        if self._env_backup is None:
            os.environ.pop("CADIVOR_STARTUP_TIMING", None)
        else:
            os.environ["CADIVOR_STARTUP_TIMING"] = self._env_backup
        sys.modules.pop("src.performance_timing", None)

    def _set_flag(self, value):
        if value is None:
            os.environ.pop("CADIVOR_STARTUP_TIMING", None)
        else:
            os.environ["CADIVOR_STARTUP_TIMING"] = value
        sys.modules.pop("src.performance_timing", None)
        self.mod = importlib.import_module("src.performance_timing")

    def _assert_control_transparent(self, flag_value, *, expect_perf: bool):
        self._set_flag(flag_value)

        # 1) ordinary success
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.mod.timed_phase("ctl.success"):
                pass
        if expect_perf:
            self.assertIn("CADIVOR_PERF", buf.getvalue())
            payload = json.loads(buf.getvalue().strip().split(" ", 1)[1])
            self.assertEqual(payload["outcome"], "success")
            self.assertNotIn("password", payload)
        else:
            self.assertNotIn("CADIVOR_PERF", buf.getvalue())

        # 2) ordinary Exception re-raised unchanged (same instance)
        exc = RuntimeError("ordinary-failure email=a@b.com token=sekrit")
        buf = io.StringIO()
        with self.assertRaises(RuntimeError) as raised, redirect_stdout(buf):
            with self.mod.timed_phase("ctl.error"):
                raise exc
        self.assertIs(raised.exception, exc)
        if expect_perf:
            self.assertIn("CADIVOR_PERF", buf.getvalue())
            self.assertNotIn("a@b.com", buf.getvalue())
            self.assertNotIn("sekrit", buf.getvalue())
            self.assertNotIn("ordinary-failure", buf.getvalue())
            payload = json.loads(buf.getvalue().strip().split(" ", 1)[1])
            self.assertEqual(payload["outcome"], "error")
        else:
            self.assertNotIn("CADIVOR_PERF", buf.getvalue())

        # 3) BaseException sentinel propagates unchanged
        class _Sentinel(BaseException):
            pass

        sentinel = _Sentinel("sentinel")
        after = []
        with self.assertRaises(_Sentinel) as raised:
            with self.mod.timed_phase("ctl.base"):
                raise sentinel
            after.append("continued")
        self.assertIs(raised.exception, sentinel)
        self.assertEqual(after, [])

        # 4–7) RerunException / StopException: propagate; code after with must not run
        for exc_factory, label in (
            (lambda: self.RerunException(self.RerunData()), "rerun"),
            (lambda: self.StopException(), "stop"),
        ):
            after = []
            work_calls = []
            buf = io.StringIO()
            control_exc = exc_factory()
            with self.assertRaises(type(control_exc)) as raised, redirect_stdout(buf):
                with self.mod.timed_phase(f"ctl.{label}"):
                    work_calls.append(1)
                    raise control_exc
                after.append("after_with")
                work_calls.append(2)
            self.assertIs(raised.exception, control_exc)
            self.assertEqual(after, [])
            self.assertEqual(work_calls, [1])
            if expect_perf:
                self.assertIn("CADIVOR_PERF", buf.getvalue())
                self.assertNotIn("email=", buf.getvalue())
            else:
                self.assertNotIn("CADIVOR_PERF", buf.getvalue())

    def test_control_flow_flag_absent(self):
        self._assert_control_transparent(None, expect_perf=False)

    def test_control_flow_flag_false(self):
        self._assert_control_transparent("false", expect_perf=False)

    def test_control_flow_flag_true(self):
        self._assert_control_transparent("true", expect_perf=True)

    def test_finally_has_no_return(self):
        src = (REPO / "src" / "performance_timing.py").read_text(encoding="utf-8")
        # Narrow: the timed_phase finally must not contain a return statement.
        start = src.index("def timed_phase(")
        finally_idx = src.index("finally:", start)
        next_def = src.find("\ndef ", finally_idx + 1)
        block = src[finally_idx:next_def if next_def > 0 else None]
        self.assertNotIn("\n            return\n", block)
        self.assertNotIn("\n        return\n", block)


class EntrypointAuthBoundaryControlFlowTests(unittest.TestCase):
    """Outer streamlit_app pattern: timed_phase around ensure_authenticated_or_stop."""

    def setUp(self):
        sys.modules.pop("src.performance_timing", None)
        self.mod = importlib.import_module("src.performance_timing")
        self.RerunException, self.StopException, self.RerunData = (
            _streamlit_control_exceptions()
        )
        self._env_backup = os.environ.get("CADIVOR_STARTUP_TIMING")

    def tearDown(self):
        if self._env_backup is None:
            os.environ.pop("CADIVOR_STARTUP_TIMING", None)
        else:
            os.environ["CADIVOR_STARTUP_TIMING"] = self._env_backup
        sys.modules.pop("src.performance_timing", None)

    def _reload(self, flag):
        if flag is None:
            os.environ.pop("CADIVOR_STARTUP_TIMING", None)
        else:
            os.environ["CADIVOR_STARTUP_TIMING"] = flag
        sys.modules.pop("src.performance_timing", None)
        self.mod = importlib.import_module("src.performance_timing")

    def test_entrypoint_rerun_and_stop_block_authenticated_path(self):
        for flag in (None, "false", "0", "true"):
            self._reload(flag)

            after_rerun = []
            with self.assertRaises(self.RerunException):
                with self.mod.timed_phase(
                    "startup.ensure_authenticated", operation="resolve"
                ):
                    # hydration st.rerun() equivalent
                    raise self.RerunException(self.RerunData())
                after_rerun.append("authenticated_runtime")
            self.assertEqual(after_rerun, [])

            after_stop = []
            with self.assertRaises(self.StopException):
                with self.mod.timed_phase(
                    "startup.ensure_authenticated", operation="resolve"
                ):
                    # signed-out st.stop() equivalent
                    raise self.StopException()
                after_stop.append("authenticated_runtime")
            self.assertEqual(after_stop, [])

    def test_no_cookie_multi_run_settlement_budget(self):
        """Simulate Incognito hydration: 6 x 0.25s then signed-out stop; no auth path."""
        from src.auth_cookies import (
            _MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS,
            _MAX_HYDRATION_ATTEMPTS,
        )

        self.assertEqual(_MAX_HYDRATION_ATTEMPTS, 6)
        self.assertEqual(_MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS, 0.25)

        for flag in (None, "false"):
            self._reload(flag)
            attempts = 0
            surfaces = []
            authenticated_crossed = False
            sleeps = []

            class _FakeSleep:
                def __call__(self, seconds):
                    sleeps.append(seconds)

            fake_sleep = _FakeSleep()

            # Multi-run loop mimicking Streamlit script restarts after RerunException
            for _run in range(1, 20):
                try:
                    with self.mod.timed_phase(
                        "startup.ensure_authenticated", operation="resolve"
                    ):
                        attempts += 1
                        if attempts < _MAX_HYDRATION_ATTEMPTS:
                            surfaces.append("boot")
                            fake_sleep(_MANAGER_FALLBACK_HYDRATION_WAIT_SECONDS)
                            raise self.RerunException(self.RerunData())
                        surfaces.append("login")
                        raise self.StopException()
                    authenticated_crossed = True
                    break
                except self.RerunException:
                    continue
                except self.StopException:
                    break

            self.assertFalse(authenticated_crossed)
            self.assertEqual(attempts, _MAX_HYDRATION_ATTEMPTS)
            self.assertEqual(surfaces.count("boot"), _MAX_HYDRATION_ATTEMPTS - 1)
            self.assertEqual(surfaces[-1], "login")
            self.assertEqual(sleeps, [0.25] * (_MAX_HYDRATION_ATTEMPTS - 1))
            self.assertAlmostEqual(sum(sleeps), 1.25, places=5)
            self.assertNotIn("boot", surfaces[-1:])


if __name__ == "__main__":
    unittest.main()

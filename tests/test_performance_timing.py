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


if __name__ == "__main__":
    unittest.main()

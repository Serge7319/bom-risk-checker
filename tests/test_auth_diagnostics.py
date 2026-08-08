"""Sprint 71.9.3A — authentication correlation diagnostic tests."""
from __future__ import annotations

import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch


def _install_streamlit_stub(session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    st.query_params = {}
    sys.modules["streamlit"] = st
    return st


class _FakeScriptRunContext:
    def __init__(self, session_id: str, script_run_id: str):
        self.session_id = session_id
        self.script_run_id = script_run_id


class AuthDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name in {"src.auth_diagnostics", "src.auth_cookies", "src.auth_state"}:
                sys.modules.pop(name, None)

    def _load_diagnostics(self, session_state=None):
        st = _install_streamlit_stub(session_state)
        secrets = types.ModuleType("src.secrets")
        secrets.get_secret_bool = lambda key, default=False: default
        sys.modules["src.secrets"] = secrets

        auth_cookies = types.ModuleType("src.auth_cookies")

        def _read_raw_auth_cookie(_manager):
            return None

        def _hydration_pending(_manager):
            return False

        auth_cookies._read_raw_auth_cookie = _read_raw_auth_cookie
        auth_cookies.auth_cookie_hydration_pending = _hydration_pending
        sys.modules["src.auth_cookies"] = auth_cookies

        import importlib

        diagnostics = importlib.import_module("src.auth_diagnostics")
        return st, diagnostics

    def _ctx(self, session_id: str, script_run_id: str):
        return _FakeScriptRunContext(session_id, script_run_id)

    def test_session_hash_contains_no_raw_session_id(self):
        _, diagnostics = self._load_diagnostics()
        raw_session = "super-secret-streamlit-session-id-abc123"
        hashed = diagnostics.hash_session_id(raw_session)
        self.assertEqual(len(hashed), 8)
        self.assertNotIn(raw_session, hashed)
        self.assertNotIn("abc123", hashed)

    def test_same_session_same_hash_across_script_runs(self):
        _, diagnostics = self._load_diagnostics()
        raw_session = "session-alpha-001"
        ctx_a = self._ctx(raw_session, "run-1")
        ctx_b = self._ctx(raw_session, "run-2")
        with patch.object(diagnostics, "_raw_session_id", side_effect=[raw_session, raw_session]):
            hash_a = diagnostics.hash_session_id()
            hash_b = diagnostics.hash_session_id()
        self.assertEqual(hash_a, hash_b)
        self.assertNotEqual(ctx_a.script_run_id, ctx_b.script_run_id)

    def test_different_sessions_produce_different_hashes(self):
        _, diagnostics = self._load_diagnostics()
        hash_a = diagnostics.hash_session_id("session-one")
        hash_b = diagnostics.hash_session_id("session-two")
        self.assertNotEqual(hash_a, hash_b)

    def test_diagnostics_contain_no_secrets(self):
        st, diagnostics = self._load_diagnostics(
            {
                "cadivor_auth_status": "authenticated",
                "user": object(),
                "access_token": "secret-access-token-value",
                "refresh_token": "secret-refresh-token-value",
            }
        )
        ctx = self._ctx("session-for-log-test", "run-log-1")

        def _read_with_cookie(_manager):
            return '{"access_token":"cookie-access","refresh_token":"cookie-refresh"}'

        sys.modules["src.auth_cookies"]._read_raw_auth_cookie = _read_with_cookie

        with patch.object(diagnostics, "_raw_session_id", return_value=ctx.session_id):
            with patch.object(diagnostics, "current_script_run_id", return_value=ctx.script_run_id):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    diagnostics.log_auth_correlation(
                        "test_checkpoint",
                        cookie_manager=MagicMock(),
                        auth_status_in="authenticated",
                        transition_reason="unit_test",
                    )
                output = buffer.getvalue()

        self.assertIn("AUTH_CORRELATE checkpoint=test_checkpoint", output)
        self.assertIn("session_hash=", output)
        self.assertIn("script_run_id=run-log-1", output)
        self.assertNotIn(ctx.session_id, output)
        self.assertNotIn("secret-access-token-value", output)
        self.assertNotIn("secret-refresh-token-value", output)
        self.assertNotIn("cookie-access", output)
        self.assertNotIn("cookie-refresh", output)
        self.assertNotIn("email", output.lower())

    def test_instrumentation_does_not_mutate_authentication_state(self):
        st, diagnostics = self._load_diagnostics(
            {
                "cadivor_auth_status": "authenticated",
                "user": {"id": "user-1"},
                "access_token": "access",
                "refresh_token": "refresh",
                "cadivor_force_signed_out": False,
            }
        )
        before = dict(st.session_state)
        with patch.object(diagnostics, "_raw_session_id", return_value="session-stable"):
            with patch.object(diagnostics, "current_script_run_id", return_value="run-stable"):
                diagnostics.log_auth_correlation(
                    "bootstrap_entry",
                    cookie_manager=MagicMock(),
                    transition_reason="no_mutation",
                )
                fields = diagnostics.build_auth_correlation_fields(
                    cookie_manager=MagicMock(),
                    transition_reason="no_mutation",
                )
        after = dict(st.session_state)
        self.assertEqual(before, after)
        self.assertEqual(fields["has_user"], "True")
        self.assertEqual(fields["has_access_token"], "True")
        self.assertEqual(fields["has_refresh_token"], "True")

    def test_build_fields_include_required_keys(self):
        _, diagnostics = self._load_diagnostics({"cadivor_auth_status": "signed_out"})
        with patch.object(diagnostics, "_raw_session_id", return_value="session-fields"):
            with patch.object(diagnostics, "current_script_run_id", return_value="run-fields"):
                fields = diagnostics.build_auth_correlation_fields(
                    cookie_manager=MagicMock(),
                    auth_status_in="signed_out",
                    transition_reason="fields_test",
                )
        required = {
            "session_hash",
            "script_run_id",
            "auth_status_in",
            "has_user",
            "has_access_token",
            "has_refresh_token",
            "cookie_present",
            "cookie_absent_flag",
            "hydration_pending",
            "force_signed_out",
            "transition_reason",
        }
        self.assertTrue(required.issubset(set(fields)))


if __name__ == "__main__":
    unittest.main()

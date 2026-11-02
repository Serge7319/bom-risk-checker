"""Login provider claim / orphan handoff regressions.

Covers the production failure where a concurrent Streamlit rerun popped
pending credentials mid-flight and left Signing-you-in orphaned.
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.test_auth_cookie_read_bridge import (
    _FakeContextCookies,
    _install_auth_modules,
    _install_streamlit_stub,
)

ROOT = Path(__file__).resolve().parents[1]


class LoginProviderClaimRaceTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name.startswith("src.auth") or name == "src.boot_read_budget":
                sys.modules.pop(name, None)

    def _load(self, session_state=None):
        st, restore_streamlit = _install_streamlit_stub(
            session_state or {}, context_cookies=_FakeContextCookies()
        )
        self.addCleanup(restore_streamlit)
        st.rerun = MagicMock(side_effect=RuntimeError("rerun"))
        st.stop = MagicMock(side_effect=RuntimeError("stop"))
        st.button = MagicMock(return_value=False)
        st.markdown = MagicMock()
        st.error = MagicMock()

        ui = types.ModuleType("src.ui.core_premium_ui")
        ui.inject_core_premium_ui_auth = MagicMock()
        sys.modules["src.ui.core_premium_ui"] = ui

        config = types.ModuleType("src.config")
        config.CADIVOR_MARKETING_URL = "https://www.cadivor.com/"
        sys.modules["src.config"] = config

        _auth_cookies, auth_state, restore_secrets = _install_auth_modules(st)
        self.addCleanup(restore_secrets)
        return st, auth_state

    def test_claim_is_exclusive_across_runs(self):
        st, _auth_state = self._load()
        from src import auth_gate

        with patch.object(auth_gate, "_current_script_run_id", return_value="run-a"):
            self.assertTrue(auth_gate.try_claim_login_provider())
        with patch.object(auth_gate, "_current_script_run_id", return_value="run-b"):
            self.assertFalse(auth_gate.try_claim_login_provider())
        with patch.object(auth_gate, "_current_script_run_id", return_value="run-a"):
            self.assertTrue(auth_gate.try_claim_login_provider())
            auth_gate.release_login_provider_claim()
        with patch.object(auth_gate, "_current_script_run_id", return_value="run-b"):
            self.assertTrue(auth_gate.try_claim_login_provider())

    def test_peek_keeps_credentials_until_clear(self):
        self._load()
        from src.auth_gate import (
            clear_pending_credentials,
            has_pending_credentials,
            peek_pending_credentials,
            stash_pending_credentials,
        )

        stash_pending_credentials("user@example.com", "secret")
        self.assertTrue(has_pending_credentials())
        email, password = peek_pending_credentials()
        self.assertEqual(email, "user@example.com")
        self.assertEqual(password, "secret")
        self.assertTrue(has_pending_credentials())
        clear_pending_credentials()
        self.assertFalse(has_pending_credentials())

    def test_slow_provider_timeout_fails_recoverably(self):
        st, auth_state = self._load({"cadivor_manual_login_in_progress": True})
        import importlib

        auth = importlib.import_module("src.auth")
        supabase = MagicMock()

        def hang(_credentials):
            import time

            time.sleep(0.2)
            return types.SimpleNamespace(
                user=types.SimpleNamespace(id="u"),
                session=types.SimpleNamespace(access_token="a", refresh_token="r"),
            )

        supabase.auth.sign_in_with_password.side_effect = hang
        with patch.object(auth, "PROVIDER_LOGIN_BUDGET_SECONDS", 0.05), patch.object(
            auth, "mark_authenticated"
        ), patch.object(auth, "_fail_manual_login_and_rerun") as fail:
            ok = auth.execute_password_login(
                supabase, MagicMock(), "user@example.com", "secret"
            )
        self.assertFalse(ok)
        fail.assert_called_once()
        self.assertEqual(fail.call_args.kwargs["event"], "manual_login_provider_timeout")

    def test_bootstrap_source_keeps_claim_and_orphan_paths(self):
        bootstrap = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("try_claim_login_provider()", bootstrap)
        self.assertIn("peek_pending_credentials()", bootstrap)
        self.assertIn("orphan_authenticating_handoff", bootstrap)
        self.assertIn("resolved_signing_in_timeout", bootstrap)
        self.assertIn('reason=f"resolved_{auth_status}_keep"', bootstrap)
        gate = (ROOT / "src" / "auth_gate.py").read_text(encoding="utf-8")
        self.assertIn("AUTH_GATE_LOGIN_CLAIM_RUN_KEY", gate)
        self.assertIn("def peek_pending_credentials", gate)
        auth = (ROOT / "src" / "auth.py").read_text(encoding="utf-8")
        self.assertIn("PROVIDER_LOGIN_BUDGET_SECONDS", auth)
        self.assertIn("manual_login_provider_timeout", auth)

    def test_deep_link_and_logout_login_contracts_present(self):
        """Source contracts for the login scenarios required by the Nov 2 fix."""
        bootstrap = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
        idle = (ROOT / "src" / "auth_idle_recovery.py").read_text(encoding="utf-8")
        self.assertIn('st.session_state["cadivor_requested_page"] = requested_page', bootstrap)
        self.assertIn("preserve_requested_page_for_reauth", idle)
        self.assertIn("enter_session_expired_recovery", idle)
        self.assertIn("Retry workspace load", idle)
        self.assertIn("Back to Login", bootstrap)


if __name__ == "__main__":
    unittest.main()

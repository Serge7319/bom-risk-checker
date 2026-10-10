"""Public one-time report signup route and email-confirmation contracts."""
from __future__ import annotations

import importlib
import re
from pathlib import Path
import sys
import types
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import MagicMock, patch

from tests.test_auth_cookie_read_bridge import _install_streamlit_stub


ROOT = Path(__file__).resolve().parents[1]


class OneTimeReportPublicEntryTests(unittest.TestCase):
    def setUp(self):
        self.st, restore_streamlit = _install_streamlit_stub({})
        self.addCleanup(restore_streamlit)
        self.st.query_params = {}
        self.st.rerun = MagicMock()
        self.st.warning = MagicMock()
        self.st.markdown = MagicMock()
        for name in ("src.auth", "src.auth_state", "src.auth_signup_confirmation"):
            sys.modules.pop(name, None)
        self.auth = importlib.import_module("src.auth")
        self.confirm = importlib.import_module("src.auth_signup_confirmation")

    def test_report_signup_email_redirect_preserves_checkout_destination(self):
        url = self.confirm.signup_confirmation_redirect_url(report_purchase=True)
        query = parse_qs(urlparse(url).query)

        self.assertEqual(query["cadivor_signup_confirm"], ["1"])
        self.assertEqual(query["cadivor_purchase"], ["one_time_report"])
        self.assertEqual(query["page"], ["BOM Analyzer"])

    def test_ordinary_signup_confirmation_url_remains_unchanged(self):
        query = parse_qs(urlparse(self.confirm.signup_confirmation_redirect_url()).query)

        self.assertEqual(query, {"cadivor_signup_confirm": ["1"]})

    def test_signup_sends_report_intent_as_low_privilege_auth_metadata(self):
        self.st.query_params = {"cadivor_purchase": "one_time_report"}
        supabase = MagicMock()
        supabase.auth.sign_up.return_value = types.SimpleNamespace(user=object(), session=None)

        with patch.object(self.auth, "_one_time_report_checkout_price", return_value="USD 49.00"), \
             patch.object(self.auth, "begin_manual_login"), \
             patch.object(self.auth, "render_auth_transition"), \
             patch.object(self.auth, "_log_manual_login_event"):
            self.auth._submit_manual_signup(supabase, MagicMock(), "new@example.com", "password")

        payload = supabase.auth.sign_up.call_args.args[0]
        options = payload["options"]
        self.assertEqual(options["data"], {"cadivor_signup_intent": "one_time_report"})
        redirect_query = parse_qs(urlparse(options["email_redirect_to"]).query)
        self.assertEqual(redirect_query["cadivor_purchase"], ["one_time_report"])
        self.assertEqual(redirect_query["page"], ["BOM Analyzer"])

    def test_report_signup_fails_closed_when_checkout_is_not_ready(self):
        self.st.query_params = {"cadivor_purchase": "one_time_report"}
        supabase = MagicMock()

        with patch.object(self.auth, "_one_time_report_checkout_price", return_value=None):
            self.auth._submit_manual_signup(supabase, MagicMock(), "new@example.com", "password")

        supabase.auth.sign_up.assert_not_called()
        self.st.warning.assert_called_once()

    def test_verified_callback_restores_report_destination_and_clears_purchase_marker(self):
        self.st.query_params = {
            "cadivor_signup_confirm": "1",
            "cadivor_purchase": "one_time_report",
            "page": "BOM Analyzer",
            "token_hash": "test-token-hash",
            "type": "email",
        }

        with patch.object(self.confirm, "_activate_from_token_hash", return_value=self.confirm.RESULT_SESSION_READY):
            self.confirm.apply_signup_confirmation_from_query(MagicMock())

        self.assertTrue(self.st.session_state["cadivor_report_purchase_pending"])
        self.assertEqual(self.st.session_state["cadivor_requested_page"], "BOM Analyzer")
        self.assertNotIn("cadivor_purchase", self.st.query_params)

    def test_public_page_offers_checkout_and_separate_signin_routes(self):
        markup = (ROOT / "marketing-web" / "index.html").read_text()
        javascript = (ROOT / "marketing-web" / "app.js").read_text()

        self.assertIn('data-app="single-report">Create account and analyze your BOM', markup)
        self.assertIn('data-app="single-report-login">Already have an account? Sign in', markup)
        self.assertIn("purchase: 'one_time_report'", javascript)
        self.assertIn("page: 'BOM Analyzer'", javascript)
        self.assertIn("auth: 'signup'", javascript)

    def test_report_only_flow_counts_and_analyzes_before_checkout(self):
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text()
        auth = (ROOT / "src" / "auth.py").read_text()
        markup = (ROOT / "marketing-web" / "index.html").read_text()

        self.assertIn("Try the free audit first", markup)
        self.assertIn("upload and run your BOM. Cadivor shows the exact unique-component count and active one-time price before checkout", markup)
        self.assertIn("covers up to 100 unique components", markup)

        upload_match = re.search(r'st\.file_uploader\(\s*"Upload your BOM file"', runtime)
        self.assertIsNotNone(upload_match)
        upload_at = upload_match.start()
        count_at = runtime.index("This BOM has {len(bom_df)} unique components.")
        analyze_at = runtime.index("if analyze_requested:")
        paywall_at = runtime.index("Cadivor analyzed {_one_time_component_count} unique components.")
        report_at = runtime.index("render_first_analysis_brief(", paywall_at)

        self.assertLess(upload_at, count_at)
        self.assertLess(count_at, analyze_at)
        self.assertLess(analyze_at, paywall_at)
        self.assertLess(paywall_at, report_at)
        self.assertIn("if len(bom_df) > ONE_TIME_BOM_MAX_PARTS:", runtime)
        self.assertIn("no payment will be requested", runtime)
        self.assertIn("payment unlocks the full report", auth.lower())
        self.assertNotIn("Continue existing checkout", runtime)


if __name__ == "__main__":
    unittest.main()

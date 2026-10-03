"""Security and response-boundary checks for the anonymous audit."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from src import public_bom_stress_test as funnel


class PublicBomStressTest(unittest.TestCase):
    def test_real_homepage_embeds_the_signed_out_app_route_before_auth_gate(self):
        root = Path(__file__).resolve().parents[1]
        homepage = (root / "marketing-web/index.html").read_text()
        script = (root / "marketing-web/app.js").read_text()
        entrypoint = (root / "streamlit_app.py").read_text()
        self.assertIn('id="bomStressTestFrame"', homepage)
        self.assertIn('id="bomStressTestSection"', homepage)
        self.assertIn('aria-labelledby="stressFunnelTitle" hidden', homepage)
        self.assertIn("CADIVOR_PUBLIC_BOM_STRESS_TEST_ENABLED === true", script)
        self.assertLess(homepage.index('class="stress-funnel"'), homepage.index('class="hero experience-scene"'))
        self.assertIn("/?public=stress&embed=true", script)
        self.assertLess(entrypoint.index('st.query_params.get("public"'),
                        entrypoint.index("ensure_authenticated_or_stop()"))

    def test_visitor_must_be_signed_by_ingress(self):
        secret = "a" * 48
        stamp = 1_000_000
        ip = "2001:db8::1"
        digest = hmac.new(secret.encode(), f"v1|{stamp}|{ip}".encode(), hashlib.sha256).hexdigest()
        header = f"v1;{stamp};{ip};{digest}"
        self.assertEqual(len(funnel.visitor_hash(header, now=stamp, secret=secret)), 64)
        with self.assertRaises(funnel.StressTestError):
            funnel.visitor_hash(header.replace(ip, "2001:db8::2"), now=stamp, secret=secret)
        with self.assertRaises(funnel.StressTestError):
            funnel.visitor_hash(header, now=stamp + 7201, secret=secret)
        with self.assertRaises(funnel.StressTestError):
            funnel.visitor_hash("1.2.3.4", now=stamp, secret=secret)

    def test_corporate_email_gate_and_bounded_parser(self):
        for address in ("person@gmail.com", "person@outlook.com", "person@yahoo.co.uk", "bad-address"):
            with self.subTest(address=address), self.assertRaises(funnel.StressTestError):
                funnel.work_email(address)
        self.assertEqual(funnel.work_email(" Director@Acme-Systems.com "), "director@acme-systems.com")
        bom = b"Manufacturer Part Number,Qty\nMCP2551-I/SN,2\nTPS5430DDAR,5\n"
        self.assertEqual(funnel.parse_bom("board.csv", bom)[0], {"mpn": "MCP2551-I/SN", "quantity": 2})
        with self.assertRaises(funnel.StressTestError):
            funnel.parse_bom("board.csv", b"MPN,Qty\n=HYPERLINK(\"bad\"),1\n")
        with self.assertRaises(funnel.StressTestError):
            funnel.parse_bom("board.csv", b"MPN,Qty\n" + b"PART,1\n" * 31)
        with self.assertRaises(funnel.StressTestError):
            funnel.parse_bom("board.csv", b"x" * (funnel.MAX_BYTES + 1))
        self.assertEqual(funnel._safe_export_cell(" =WEBSERVICE(\"https://example.com\")"),
                         "' =WEBSERVICE(\"https://example.com\")")

    def test_rate_slot_is_reserved_before_any_provider_call_and_locked_rows_never_return(self):
        class FakeUpdate:
            def __init__(self):
                self.saved = None

            def table(self, name):
                self.table_name = name
                return self

            def update(self, payload):
                self.saved = payload
                return self

            def eq(self, *_):
                return self

            def execute(self):
                return None

        fake = FakeUpdate()
        calls = []

        def reserve(_):
            calls.append("reserve")
            return "00000000-0000-0000-0000-000000000000"

        def enrich(index, row):
            self.assertEqual(calls[0], "reserve")
            return index, {
                **row, "risk": "High" if index >= 5 else "Low",
                "verified": True, "risk_reasons": [f"private-evidence-{index}"],
                "lifecycle": "Active", "stock": 7, "lead_time_weeks": 1.0,
                "supplier_count": 2, "sources": "DigiKey, Mouser",
            }

        csv = ("MPN,Qty\n" + "".join(f"PART{i},1\n" for i in range(10))).encode()
        with patch.object(funnel, "enabled", return_value=True), \
             patch.object(funnel, "visitor_hash", return_value="f" * 64), \
             patch.object(funnel, "_reserve", side_effect=reserve), \
             patch.object(funnel, "_service_client", return_value=fake), \
             patch.object(funnel, "_enrich_one", side_effect=enrich):
            teaser = funnel.run_audit("prototype.csv", csv, "signed")
        self.assertEqual(len(teaser["preview"]), 5)
        self.assertEqual(teaser["remaining_high_risk"], 5)
        self.assertEqual(len(fake.saved["results"]), 10)
        self.assertNotIn("PART5", str(teaser))
        self.assertNotIn("private-evidence-5", str(teaser))

    def test_full_results_require_a_confirmed_supabase_identity_with_matching_email(self):
        class FakeQuery:
            def __init__(self):
                self.filters = []

            def table(self, name):
                self.name = name
                return self

            def select(self, *_):
                return self

            def eq(self, key, value):
                self.filters.append((key, value))
                return self

            def gte(self, *_):
                return self

            def order(self, *_args, **_kwargs):
                return self

            def limit(self, *_):
                return self

            def execute(self):
                return types.SimpleNamespace(data=[{"results": [{"mpn": "PRIVATE-PART"}]}])

        query = FakeQuery()
        user = types.SimpleNamespace(email="engineer@company.com", email_confirmed_at=None)
        auth = types.SimpleNamespace(auth=types.SimpleNamespace(
            get_user=lambda token: types.SimpleNamespace(user=user)))
        supabase = types.SimpleNamespace(create_client=lambda *_: auth)
        with patch.dict(sys.modules, {"supabase": supabase}), \
             patch.object(funnel, "enabled", return_value=True), \
             patch.object(funnel, "get_secret", return_value="configured"), \
             patch.object(funnel, "_service_client", return_value=query):
            self.assertIsNone(funnel.verified_report(""))
            self.assertIsNone(funnel.verified_report("unverified-jwt"))
            self.assertEqual(query.filters, [])
            user.email_confirmed_at = "2026-10-03T10:00:00Z"
            report = funnel.verified_report("confirmed-jwt")
        self.assertEqual(report["results"][0]["mpn"], "PRIVATE-PART")
        self.assertIn(("work_email", "engineer@company.com"), query.filters)

    def test_supplier_outage_is_unverified_not_a_fabricated_high_risk_dependency(self):
        supplier_module = types.SimpleNamespace(get_best_part_data=lambda _: {
            "supplier_data_verified": False, "stock_total": 0,
            "lifecycle_status": "Unknown", "supplier_count": 0,
        })
        with patch.dict(sys.modules, {"integrations.supplier_aggregator": supplier_module}):
            _, result = funnel._enrich_one(0, {"mpn": "PART1", "quantity": 2})
        self.assertFalse(result["verified"])
        self.assertEqual(result["risk"], "Needs verification")
        self.assertIsNone(result["stock"])

    def test_email_link_uses_existing_verified_callback_without_password(self):
        sent = []
        auth = types.SimpleNamespace(auth=types.SimpleNamespace(
            sign_in_with_otp=lambda payload: sent.append(payload)))
        supabase = types.SimpleNamespace(create_client=lambda *_: auth)
        callback = types.SimpleNamespace(
            signup_confirmation_redirect_url=lambda: "https://app.cadivor.com/?cadivor_signup_confirm=1")
        with patch.dict(sys.modules, {
            "supabase": supabase, "src.auth_signup_confirmation": callback,
        }), patch.object(funnel, "get_secret", return_value="configured"):
            funnel.send_report_verification("Director@Company.com")
        self.assertEqual(sent[0]["email"], "director@company.com")
        self.assertTrue(sent[0]["options"]["should_create_user"])
        self.assertIn("cadivor_signup_confirm=1", sent[0]["options"]["email_redirect_to"])

    def test_verified_email_callback_hands_off_to_reports_only_after_success(self):
        fake_st = types.ModuleType("streamlit")
        fake_st.session_state = {}
        fake_st.query_params = {
            "cadivor_signup_confirm": "1", "cadivor_stress_report": "1",
            "token_hash": "one-time-hash", "type": "email",
        }
        auth_state = types.ModuleType("src.auth_state")
        for name in ("APP_LOGIN", "APP_SIGNUP", "APP_SIGNUP_CONFIRMATION_INVALID",
                     "APP_SIGNUP_CONFIRMATION_SUCCESS", "AUTH_SIGNED_OUT",
                     "SIGNUP_PENDING_EMAIL_KEY"):
            setattr(auth_state, name, name)
        auth_state.log_auth_diagnostic = lambda *args, **kwargs: None
        filename = Path(__file__).resolve().parents[1] / "src/auth_signup_confirmation.py"
        spec = importlib.util.spec_from_file_location("stress_confirmation_test", filename)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"streamlit": fake_st, "src.auth_state": auth_state}):
            spec.loader.exec_module(module)
            with patch.object(module, "_activate_from_token_hash", return_value=module.RESULT_SESSION_READY):
                module.apply_signup_confirmation_from_query(object())
            self.assertTrue(fake_st.session_state["cadivor_stress_landing_pending"])
            self.assertNotIn("token_hash", fake_st.query_params)
            self.assertNotIn("cadivor_stress_report", fake_st.query_params)
            fake_st.session_state.clear()
            fake_st.query_params.update({
                "cadivor_signup_confirm": "1", "cadivor_stress_report": "1",
                "token_hash": "bad-hash", "type": "email",
            })
            with patch.object(module, "_activate_from_token_hash", return_value=module.RESULT_INVALID):
                module.apply_signup_confirmation_from_query(object())
            self.assertNotIn("cadivor_stress_landing_pending", fake_st.session_state)

    def test_verified_handoff_keeps_reports_in_url_and_session(self):
        fake_st = types.ModuleType("streamlit")
        fake_st.session_state = {"cadivor_stress_landing_pending": True}
        fake_st.query_params = {}
        components = types.ModuleType("streamlit.components")
        component_v1 = types.ModuleType("streamlit.components.v1")
        components.v1 = component_v1
        fake_st.components = components
        auth_diagnostics = types.ModuleType("src.auth_diagnostics")
        auth_diagnostics.log_auth_correlation = lambda *args, **kwargs: None
        auth_cookies = types.ModuleType("src.auth_cookies")
        auth_cookies.persist_session_auth_cookie = lambda *args, **kwargs: None
        auth_cookies.get_auth_cookie_manager = lambda **kwargs: object()
        filename = Path(__file__).resolve().parents[1] / "src/auth_state.py"
        spec = importlib.util.spec_from_file_location("stress_auth_state_test", filename)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "streamlit": fake_st, "streamlit.components": components,
            "streamlit.components.v1": component_v1,
            "src.auth_diagnostics": auth_diagnostics, "src.auth_cookies": auth_cookies,
        }):
            spec.loader.exec_module(module)
            session = types.SimpleNamespace(access_token="token", refresh_token="refresh")
            module.mark_authenticated(types.SimpleNamespace(id="user1"), session, object())
        self.assertEqual(fake_st.session_state["cadivor_route"], "Reports")
        self.assertEqual(fake_st.query_params["page"], "Reports")


if __name__ == "__main__":
    unittest.main()

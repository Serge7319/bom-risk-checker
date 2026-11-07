"""Regression coverage for the Next API's preserved analysis and purchase path."""
from __future__ import annotations

import json
import os
import sys
import types
import unittest
from unittest.mock import patch

# The API image installs the root application requirements. Keep these tests
# runnable in a minimal migration-only environment as well.
if "requests" not in sys.modules:
    requests_stub = types.ModuleType("requests")
    requests_stub.get = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("unexpected network request in synthetic test")
    )
    requests_stub.post = requests_stub.get
    sys.modules["requests"] = requests_stub

if "streamlit" not in sys.modules:
    streamlit_stub = types.ModuleType("streamlit")
    streamlit_stub.cache_data = lambda *args, **kwargs: (lambda function: function)
    streamlit_stub.cache_resource = lambda *args, **kwargs: (lambda function: function)
    sys.modules["streamlit"] = streamlit_stub

import pandas as pd
from starlette.testclient import TestClient

from apps.api import main, plan_limits
from apps.api.legacy_supplier_workflow import find_replacements
from apps.api.one_time_report_service import request_action
from apps.api.synthetic_analyze import analyze_dataframe


class LegacyAnalysisBridgeTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.context = {
            "workspace_id": "ws-test",
            "user_id": "00000000-0000-4000-8000-000000000001",
        }

    def test_bom_analysis_uses_established_supplier_risk_engine(self):
        supplier_part = {
            "mpn": "LM358DR",
            "manufacturer_part_number": "LM358DR",
            "manufacturer": "Texas Instruments",
            "description": "Dual operational amplifier",
            "lifecycle_status": "NRND",
            "total_market_stock": 2,
            "stock_total": 2,
            "stock_data_complete": True,
            "supplier_count": 2,
            "supplier_data_verified": True,
            "unit_price": 0.42,
            "source": "DigiKey",
            "provider_health": {
                "configured_count": 2,
                "failed_count": 0,
                "summary_message": "Two configured providers responded.",
            },
            "stock_data_sources": ["DigiKey", "Mouser"],
        }
        frame = pd.DataFrame(
            [{"mpn": "LM358DR", "mpn_normalized": "LM358DR", "quantity": 10}]
        )
        with (
            patch(
                "integrations.supplier_aggregator.get_best_part_data",
                return_value=supplier_part,
            ),
            patch("src.alternative_engine.suggest_alternatives_v2", return_value=[]),
        ):
            report = analyze_dataframe(
                frame,
                analysis_mode="legacy-supplier",
                analysis_id="e53ff5ed-9f23-4ad7-9f41-9ef04c84540e",
            )

        row = report["parts"][0]
        self.assertEqual(report["mode"], "legacy-supplier-engine")
        self.assertEqual(row["risk_score"], 85)
        self.assertEqual(row["risk_level"], "High")
        self.assertEqual(row["risk_reasons"], [
            "Part is not recommended for new designs",
            "Severe stock shortage relative to BOM quantity",
            "Two checked suppliers with inventory below BOM quantity",
        ])
        self.assertEqual(row["source"], "DigiKey")
        self.assertTrue(row["supplier_data_verified"])

    def test_replacement_adapter_uses_alternative_finder_result(self):
        def fake_search(state, mpn):
            state["alternative_finder_result"] = {
                "status": "partial_success",
                "search_outcome": "partial_success",
                "original_data": {
                    "manufacturer_part_number": mpn,
                    "supplier_data_verified": False,
                },
                "original_risk": {},
                "candidates": [{
                    "Alternative Part": "LM358ADR",
                    "Manufacturer": "Texas Instruments",
                    "Classification": "Same device family",
                    "Candidate Disposition": "Discovery lead only",
                }],
                "discovery_metadata": {},
            }
            return {"status": "partial_success", "search_outcome": "partial_success"}

        with patch(
            "src.alternative_finder_search.run_alternative_finder_search",
            side_effect=fake_search,
        ):
            result = find_replacements("LM358DR")

        self.assertEqual(result["mode"], "legacy-supplier-engine")
        self.assertEqual(result["candidates"][0]["mpn"], "LM358ADR")
        self.assertFalse(result["candidates"][0]["source_identity_verified"])

    def test_paid_credit_is_reserved_saved_and_consumed_once(self):
        csv_data = b"MPN,Quantity\nLM358DR,10\n"

        def fake_analysis(**kwargs):
            return {
                "id": kwargs["analysis_id"],
                "total_parts": 1,
                "health_score": 85,
                "health_status": "High Risk",
                "high_risk_count": 1,
                "medium_risk_count": 0,
                "low_risk_count": 0,
                "mode": "legacy-supplier-engine",
                "persisted": True,
                "workspace_id": kwargs["workspace_id"],
                "parts": [],
            }

        with (
            patch.object(main, "_auth_context", return_value=(self.context, None)),
            patch.object(
                plan_limits,
                "assert_analysis_allowed",
                side_effect=plan_limits.PlanLimitError("plan_limit", "limit reached"),
            ),
            patch.object(
                main.one_time_report_service,
                "request_action",
                side_effect=[
                    ({"ok": True, "order_id": "00000000-0000-4000-8000-000000000002"}, 200),
                    ({"ok": True}, 200),
                ],
            ) as billing,
            patch.object(main, "analyze_upload", side_effect=fake_analysis) as analyze,
        ):
            response = self.client.post(
                "/boms/analyze",
                headers={"Authorization": "Bearer synthetic-test-jwt"},
                files={"file": ("fixture.csv", csv_data, "text/csv")},
            )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["mode"], "legacy-supplier-engine")
        self.assertEqual([call.kwargs["action"] for call in billing.call_args_list], ["reserve", "consume"])
        self.assertEqual(analyze.call_args.kwargs["analysis_id"], result["analysis_id"])

    def test_plan_limit_without_paid_credit_links_to_purchase(self):
        csv_data = b"MPN,Quantity\nLM358DR,10\n"
        with (
            patch.object(main, "_auth_context", return_value=(self.context, None)),
            patch.object(
                plan_limits,
                "assert_analysis_allowed",
                side_effect=plan_limits.PlanLimitError("plan_limit", "limit reached"),
            ),
            patch.object(
                main.one_time_report_service,
                "request_action",
                return_value=({"ok": False, "detail": "no paid credit"}, 402),
            ),
            patch.object(main, "analyze_upload") as analyze,
        ):
            response = self.client.post(
                "/boms/analyze",
                headers={"Authorization": "Bearer synthetic-test-jwt"},
                files={"file": ("fixture.csv", csv_data, "text/csv")},
            )

        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()["code"], "one_time_report_required")
        self.assertEqual(response.json()["one_time_report"]["href"], "/single-bom-report")
        analyze.assert_not_called()

    def test_one_time_service_bridge_forwards_user_token_only(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _limit):
                return json.dumps({"ok": True, "available_credit": True}).encode()

        with (
            patch.dict(os.environ, {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "public-test-key",
            }),
            patch("apps.api.one_time_report_service.urlopen", return_value=FakeResponse()) as call,
        ):
            result, status = request_action(
                access_token="synthetic-test-jwt",
                action="status",
            )

        sent = call.call_args.args[0]
        self.assertEqual(status, 200)
        self.assertTrue(result["available_credit"])
        self.assertEqual(sent.full_url, "https://example.supabase.co/functions/v1/one-time-report")
        self.assertEqual(sent.get_header("Authorization"), "Bearer synthetic-test-jwt")
        self.assertNotIn("service_role", str(dict(sent.header_items())).lower())


if __name__ == "__main__":
    unittest.main()

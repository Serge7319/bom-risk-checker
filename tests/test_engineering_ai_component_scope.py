"""Regression tests for component-scoped Ask Cadivor recommendations."""
from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _load_engineering_ai():
    for name in list(sys.modules):
        if name in {"src.services.engineering_ai", "src.secrets"}:
            sys.modules.pop(name, None)
    streamlit = types.ModuleType("streamlit")
    streamlit.secrets = {}
    sys.modules["streamlit"] = streamlit

    import importlib

    return importlib.import_module("src.services.engineering_ai")


class EngineeringAIComponentScopeTests(unittest.TestCase):
    def test_named_component_answer_excludes_unrelated_bom_evidence(self):
        ai = _load_engineering_ai()
        context = {
            "analysis": {"project_name": "TEST - Synthetic QA BOM"},
            "components": [
                {
                    "part_number": "TARGET-123",
                    "risk_score": 72,
                    "risk_level": "High",
                    "lifecycle_status": "Active",
                    "supplier_count": 1,
                    "stock_available": 0,
                    "lead_time_weeks": 24,
                    "risk_reasons": "Synthetic single-source review required.",
                },
                {
                    "part_number": "UNRELATED-999",
                    "risk_score": 98,
                    "risk_level": "High",
                    "lifecycle_status": "Obsolete",
                    "supplier_count": 0,
                    "stock_available": 0,
                    "lead_time_weeks": 48,
                    "risk_reasons": "Unrelated synthetic lifecycle evidence.",
                },
            ],
            "alternatives": [
                {
                    "original_part": "TARGET-123",
                    "alternative_part": "TARGET-ALT",
                    "supplier": "Synthetic Supplier A",
                    "recommendation_score": 63,
                },
                {
                    "original_part": "UNRELATED-999",
                    "alternative_part": "UNRELATED-ALT",
                    "supplier": "Unrelated Synthetic Supplier",
                    "recommendation_score": 99,
                },
            ],
            "monitoring": [
                {"part_number": "TARGET-123", "alert_type": "Synthetic stock change"},
                {"part_number": "UNRELATED-999", "alert_type": "Unrelated lifecycle change"},
            ],
            "decisions": [],
            "coverage": {"score": 100},
        }
        client = ai.EngineeringAI(
            api_key="sk-live-test-key-value",
            model="synthetic-test",
            base_url="https://example.invalid/v1",
        )

        with patch.object(
            ai.request,
            "urlopen",
            side_effect=AssertionError("component-scoped recommendations must use scoped saved evidence"),
        ) as provider_request:
            response = client.ask(
                question="Why is TARGET-123 ranked first?",
                context=context,
            )

        self.assertEqual(response.provider, "cadivor-grounded")
        self.assertIn("TARGET-123", response.answer)
        self.assertNotIn("UNRELATED-999", response.answer)
        self.assertNotIn("UNRELATED-ALT", response.answer)
        self.assertNotIn("Unrelated Synthetic Supplier", response.answer)
        provider_request.assert_not_called()


    def test_component_mention_requires_a_complete_identifier(self):
        ai = _load_engineering_ai()
        context = {
            "components": [
                {"part_number": "U1", "risk_score": 98},
                {"part_number": "U10", "risk_score": 32},
            ],
            "analysis": {"project_name": "TEST - Synthetic QA BOM"},
        }

        scoped = ai._component_scoped_context(
            "Why is U10 ranked first?",
            context,
        )

        self.assertIsNotNone(scoped)
        self.assertEqual(
            [row["part_number"] for row in scoped["components"]],
            ["U10"],
        )

    def test_component_fact_question_keeps_provider_path(self):
        ai = _load_engineering_ai()
        client = ai.EngineeringAI(
            api_key="sk-live-test-key-value",
            model="synthetic-test",
            base_url="https://example.invalid/v1",
        )
        provider_response = MagicMock()
        provider_response.read.return_value = json.dumps(
            {"output_text": "TARGET-123 package evidence is available for review."}
        ).encode("utf-8")
        provider_response.__enter__.return_value = provider_response

        with patch.object(
            ai.request,
            "urlopen",
            return_value=provider_response,
        ) as provider_request:
            response = client.ask(
                question="What package does TARGET-123 use?",
                context={
                    "components": [{"part_number": "TARGET-123"}],
                    "analysis": {"project_name": "TEST - Synthetic QA BOM"},
                },
            )

        self.assertEqual(response.provider, "openai")
        self.assertIn("package evidence", response.answer)
        provider_request.assert_called_once()


if __name__ == "__main__":
    unittest.main()

"""Sprint 72.2.1 — EngineeringAI response length and prompt contract tests."""
from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _install_streamlit_secrets(secrets_map: dict | None = None):
    st = types.ModuleType("streamlit")
    st.secrets = secrets_map or {}
    sys.modules["streamlit"] = st


def _sample_context() -> dict:
    return {
        "summary": {"health_score": 93, "top_risks": [{"part_number": "U0"}]},
        "analysis": {"analysis_id": "a-1", "project_name": "Demo BOM", "user_id": "u1", "workspace_id": "w1"},
        "components": [{"part_number": "U0", "manufacturer": "Vendor", "risk_score": 90, "risk_level": "high"}],
        "monitoring": [{"alert_type": "lifecycle", "part_number": "U0"}],
        "alternatives": [],
        "decisions": [],
        "timeline": [],
        "collaboration": {"comment_count": 1},
        "reports": [{"type": "executive"}],
        "coverage": {"score": 72},
    }


class EngineeringAIResponseContractTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name in {"src.services.engineering_ai", "src.secrets"}:
                sys.modules.pop(name, None)
        self._env_patch = patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "sk-live-test-key-value"},
            clear=True,
        )
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def _load_engineering_ai(self):
        _install_streamlit_secrets()
        import importlib

        return importlib.import_module("src.services.engineering_ai")

    def _capture_openai_payload(self, *, question: str):
        ai = self._load_engineering_ai()
        client = ai.EngineeringAI()
        captured: dict = {}

        def _mock_urlopen(req, timeout=45):
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            response_body = json.dumps({"output_text": "Review U0 first."}).encode("utf-8")
            mock_response = MagicMock()
            mock_response.read.return_value = response_body
            mock_response.__enter__.return_value = mock_response
            return mock_response

        with patch("src.services.engineering_ai.request.urlopen", side_effect=_mock_urlopen) as urlopen_mock:
            client.ask(question=question, context=_sample_context())
        self.assertEqual(urlopen_mock.call_count, 1)
        return captured["payload"]

    def test_normal_prompt_requests_concise_copilot_answer(self):
        ai = self._load_engineering_ai()
        instructions = ai._system_instruction(detailed=False)
        self.assertIn("engineering decision copilot, not a report generator", instructions)
        self.assertIn("2–4 sentences", instructions)
        self.assertIn("Maximum 3 concise bullet points", instructions)
        self.assertIn("Maximum 3 concise, actionable next steps", instructions)

    def test_normal_prompt_prevents_report_style_duplication(self):
        ai = self._load_engineering_ai()
        instructions = ai._system_instruction(detailed=False)
        self.assertIn("do NOT reproduce those sections", instructions)
        self.assertIn(
            "Do not include Executive Summary, Rankings, Workflow, Confidence, or Follow-up Questions.",
            instructions,
        )
        self.assertNotIn("Return distinct sections:", instructions)

    def test_normal_payload_uses_reduced_output_token_budget(self):
        payload = self._capture_openai_payload(question="What should I review first in this BOM?")
        self.assertEqual(payload["max_output_tokens"], 500)

    def test_detailed_request_uses_expanded_output_budget(self):
        ai = self._load_engineering_ai()
        self.assertTrue(ai._wants_detailed_response("Give me a detailed report on every component."))
        payload = self._capture_openai_payload(
            question="Give me a comprehensive analysis of this BOM with every component explained."
        )
        self.assertEqual(payload["max_output_tokens"], 900)
        self.assertIn("detailed or comprehensive", payload["instructions"])

    def test_detailed_detection_does_not_trigger_on_normal_questions(self):
        ai = self._load_engineering_ai()
        self.assertFalse(ai._wants_detailed_response("What should I review first in this BOM?"))
        self.assertFalse(ai._wants_detailed_response("Which supplier should we qualify first?"))

    def test_openai_payload_still_trims_context_from_sprint_72_2(self):
        payload = self._capture_openai_payload(question="What should I review first?")
        context_blob = payload["input"][0]["content"][0]["text"]
        self.assertNotIn('"top_risks"', context_blob)
        self.assertNotIn('"collaboration"', context_blob)
        self.assertNotIn('"reports"', context_blob)
        self.assertIn('"components"', context_blob)
        self.assertIn('"monitoring"', context_blob)

    def test_one_submission_still_produces_one_provider_call(self):
        payload = self._capture_openai_payload(question="What should I review first?")
        self.assertIn("instructions", payload)
        self.assertIn("max_output_tokens", payload)

    def test_no_sprint_7143_helpers_reintroduced(self):
        ai = self._load_engineering_ai()
        source = open(ai.__file__, encoding="utf-8").read()
        for helper in (
            "_format_engineering_prose",
            "_inline_engineering_format",
            "_render_structured_answer_sections",
        ):
            self.assertNotIn(f"def {helper}", source)

    def test_renderer_module_unchanged_by_response_contract(self):
        from pathlib import Path

        source = Path("src/components/engineering_assistant.py").read_text(encoding="utf-8")
        self.assertIn("def _render_response(", source)
        self.assertNotIn("def _render_structured_answer_sections(", source)


if __name__ == "__main__":
    unittest.main()

"""Sprint 72.2 — EngineeringAI provider timeout and context reduction tests."""
from __future__ import annotations

import io
import json
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch
from urllib import error


def _install_streamlit_secrets(secrets_map: dict | None = None):
    st = types.ModuleType("streamlit")
    st.secrets = secrets_map or {}
    sys.modules["streamlit"] = st


def _sample_context(*, include_top_risks: bool = True) -> dict:
    components = [
        {
            "part_number": f"U{i}",
            "manufacturer": "Vendor",
            "risk_level": "high",
            "risk_score": 90 - i,
            "risk_reasons": "Lifecycle and supplier exposure",
            "lifecycle_status": "Active",
            "stock_available": 100,
            "supplier_count": 1,
            "lead_time_weeks": 8,
            "best_source": "Authorized distributor",
        }
        for i in range(15)
    ]
    summary = {
        "health_score": 93,
        "total_parts": 15,
        "high_risk_parts": 5,
        "release_posture": "focused_review",
    }
    if include_top_risks:
        summary["top_risks"] = components[:5]
    return {
        "version": "34.3",
        "generated_at": "2026-08-09T00:00:00Z",
        "analysis": {
            "analysis_id": "a-1",
            "project_name": "Demo BOM",
            "user_id": "user-1",
            "workspace_id": "ws-1",
        },
        "summary": summary,
        "components": components,
        "monitoring": [{"alert_type": "lifecycle", "part_number": "U0"}],
        "alternatives": [],
        "decisions": [],
        "timeline": [{"event_type": "review", "summary": "Initial review"}],
        "collaboration": {"comment_count": 2, "follower_count": 1},
        "reports": [{"type": "executive", "available": True}],
        "coverage": {"score": 72},
    }


class EngineeringAIProviderStabilityTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name in {"src.services.engineering_ai", "src.secrets", "src.services.copilot_conversation"}:
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

    def test_prepare_prompt_context_removes_duplicated_and_metadata_fields(self):
        ai = self._load_engineering_ai()
        raw = _sample_context(include_top_risks=True)
        trimmed = ai._prepare_prompt_context(raw)
        self.assertNotIn("top_risks", trimmed.get("summary", {}))
        self.assertNotIn("reports", trimmed)
        self.assertNotIn("collaboration", trimmed)
        self.assertNotIn("version", trimmed)
        self.assertNotIn("generated_at", trimmed)
        self.assertNotIn("user_id", trimmed.get("analysis", {}))
        self.assertNotIn("workspace_id", trimmed.get("analysis", {}))
        self.assertEqual(len(trimmed.get("components") or []), 15)

    def test_payload_size_reduces_without_top_risks_and_metadata(self):
        ai = self._load_engineering_ai()
        raw = _sample_context(include_top_risks=True)
        before = ai._estimate_payload_stats(
            question="What should I review first in this BOM?",
            history=[{"question": "Q1", "answer": "A" * 3000}],
            context=raw,
        )
        trimmed = ai._prepare_prompt_context(raw)
        after = ai._estimate_payload_stats(
            question="What should I review first in this BOM?",
            history=[{"question": "Q1", "answer": "A" * 1200}],
            context=trimmed,
        )
        self.assertLess(after["context_chars"], before["context_chars"])
        self.assertLess(after["payload_chars"], before["payload_chars"])
        self.assertLess(after["estimated_input_tokens"], before["estimated_input_tokens"])

    def test_timeout_produces_single_failed_event_without_retry(self):
        ai = self._load_engineering_ai()
        client = ai.EngineeringAI()

        def _timeout(*args, **kwargs):
            raise error.URLError("timed out")

        buffer = io.StringIO()
        with patch("src.services.engineering_ai.request.urlopen", side_effect=_timeout) as urlopen_mock:
            with redirect_stdout(buffer):
                with self.assertRaises(ai.EngineeringAIError) as ctx:
                    client.ask(
                        question="What should I review first?",
                        context=_sample_context(),
                    )
        self.assertEqual(ctx.exception.code, "timeout")
        self.assertEqual(urlopen_mock.call_count, 1)
        output = buffer.getvalue()
        self.assertEqual(output.count("AI_PROVIDER request_started"), 1)
        self.assertEqual(output.count("AI_PROVIDER request_failed"), 1)
        self.assertIn("code=timeout", output)
        self.assertIn("request_id=", output)
        self.assertNotIn("AI_PROVIDER request_completed", output)

    def test_successful_request_logs_started_and_completed_with_request_id(self):
        ai = self._load_engineering_ai()
        client = ai.EngineeringAI()
        response_body = json.dumps({"output_text": "Review U0 first."}).encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = response_body
        mock_response.__enter__.return_value = mock_response

        buffer = io.StringIO()
        with patch("src.services.engineering_ai.request.urlopen", return_value=mock_response) as urlopen_mock:
            with redirect_stdout(buffer):
                response = client.ask(
                    question="What should I review first?",
                    context=_sample_context(),
                )
        self.assertEqual(urlopen_mock.call_count, 1)
        self.assertEqual(response.provider, "openai")
        output = buffer.getvalue()
        self.assertIn("AI_PROVIDER request_started", output)
        self.assertIn("AI_PROVIDER request_completed", output)
        self.assertIn("estimated_input_tokens=", output)
        started_id = output.split("request_id=", 1)[1].split()[0]
        completed_id = output.split("request_id=", 2)[2].split()[0]
        self.assertEqual(started_id, completed_id)

    def test_unconfigured_fallback_still_skips_provider(self):
        with patch.dict("os.environ", {}, clear=True):
            ai = self._load_engineering_ai()
            client = ai.EngineeringAI()
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                response = client.ask(
                    question="What should I review first?",
                    context=_sample_context(),
                )
        self.assertEqual(response.provider, "cadivor-grounded")
        self.assertIn("AI_PROVIDER request_skipped", buffer.getvalue())

    def test_compact_history_answer_cap_reduced(self):
        import importlib

        copilot = importlib.import_module("src.services.copilot_conversation")
        thread = [{"question": "Why?", "answer": "X" * 5000}]
        compact = copilot.compact_history(thread)
        self.assertEqual(len(compact[0]["answer"]), copilot.PROMPT_HISTORY_ANSWER_MAX)

    def test_no_sprint_7143_helpers_reintroduced(self):
        ai = self._load_engineering_ai()
        source = open(ai.__file__, encoding="utf-8").read()
        for helper in (
            "_format_engineering_prose",
            "_inline_engineering_format",
            "_render_structured_answer_sections",
        ):
            self.assertNotIn(f"def {helper}", source)


if __name__ == "__main__":
    unittest.main()

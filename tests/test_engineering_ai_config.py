"""Sprint 71.5 — EngineeringAI configuration resolution and provider selection tests."""
from __future__ import annotations

import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


def _install_streamlit_secrets(secrets_map: dict | None = None):
    st = types.ModuleType("streamlit")
    st.secrets = secrets_map or {}
    sys.modules["streamlit"] = st


class EngineeringAIConfigTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name in {"src.services.engineering_ai", "src.secrets"}:
                sys.modules.pop(name, None)
        self._env_patch = patch.dict("os.environ", {}, clear=True)
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def _load_engineering_ai(self, secrets_map: dict | None = None):
        _install_streamlit_secrets(secrets_map)
        import importlib

        return importlib.import_module("src.services.engineering_ai")

    def test_env_key_present_configured_true(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-live-test-key-value"}, clear=True):
            ai = self._load_engineering_ai()
            client = ai.EngineeringAI()
            self.assertTrue(client.configured)
            self.assertEqual(client.configuration_state, "connected")

    def test_st_secrets_fallback_when_env_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            ai = self._load_engineering_ai({"OPENAI_API_KEY": "sk-secrets-fallback-key"})
            client = ai.EngineeringAI()
            self.assertTrue(client.configured)

    def test_missing_key_uses_cadivor_grounded_fallback(self):
        ai = self._load_engineering_ai()
        client = ai.EngineeringAI()
        self.assertFalse(client.configured)
        self.assertEqual(client.configuration_state, "missing")

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            response = client.ask(
                question="What should I review first?",
                context={"analysis_id": "a-1", "components": []},
            )
        output = buffer.getvalue()
        self.assertEqual(response.provider, "cadivor-grounded")
        self.assertIn("AI_PROVIDER request_skipped", output)
        self.assertIn("provider=cadivor-grounded", output)

    def test_placeholder_key_treated_as_unconfigured(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "your-api-key-here"}, clear=True):
            ai = self._load_engineering_ai()
            client = ai.EngineeringAI()
            self.assertFalse(client.configured)
            self.assertEqual(client.configuration_state, "placeholder")

    def test_log_ai_config_never_prints_secret(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-secret-value-never-logged"}, clear=True):
            ai = self._load_engineering_ai()
            client = ai.EngineeringAI()
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                ai.log_ai_config(client)
            output = buffer.getvalue()
        self.assertIn("AI_CONFIG", output)
        self.assertIn("key_present=True", output)
        self.assertIn("configured=True", output)
        self.assertNotIn("sk-secret-value-never-logged", output)

    def test_model_and_base_url_defaults(self):
        ai = self._load_engineering_ai()
        client = ai.EngineeringAI()
        self.assertEqual(client.model, "gpt-4.1-mini")
        self.assertEqual(client.base_url, "https://api.openai.com/v1")

    def test_whitespace_trimmed_from_env_key(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "  sk-trimmed-key  "}, clear=True):
            ai = self._load_engineering_ai()
            client = ai.EngineeringAI()
            self.assertTrue(client.configured)
            self.assertEqual(client.api_key, "sk-trimmed-key")


if __name__ == "__main__":
    unittest.main()

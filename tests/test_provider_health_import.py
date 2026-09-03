"""Regression: provider_health must import cleanly without local secret files.

Auth/cookie unit tests often stub ``sys.modules['src.secrets']`` without
``ConfigurationError``.  A later suite that imports
``integrations.provider_health`` must still succeed on a clean GitHub runner
that has no ``.streamlit/secrets.toml``.
"""
from __future__ import annotations

import importlib
import sys
import unittest

from tests.secrets_module_isolation import (
    ensure_real_src_secrets_module,
    install_src_secrets_stub,
)


class ProviderHealthCleanImportTests(unittest.TestCase):
    def setUp(self):
        self._saved = {
            name: module
            for name, module in sys.modules.items()
            if name in {"src.secrets", "src.configuration_errors"}
            or name.startswith("integrations.provider_health")
        }
        for name in list(self._saved):
            sys.modules.pop(name, None)

    def tearDown(self):
        for name in list(sys.modules):
            if name in {"src.secrets", "src.configuration_errors"} or name.startswith(
                "integrations.provider_health"
            ):
                sys.modules.pop(name, None)
        sys.modules.update(self._saved)
        ensure_real_src_secrets_module()

    def test_provider_health_imports_without_secret_resolution(self):
        """provider_health must load without reading env/Streamlit secrets."""
        # Ensure a clean module graph with no preloaded secrets helpers.
        sys.modules.pop("src.secrets", None)
        sys.modules.pop("integrations.provider_health", None)

        module = importlib.import_module("integrations.provider_health")
        from src.configuration_errors import ConfigurationError

        self.assertIs(module.ConfigurationError, ConfigurationError)
        self.assertEqual(
            module.classify_provider_exception(
                ConfigurationError("Missing required configuration variable: EXAMPLE")
            ),
            module.PROVIDER_NOT_CONFIGURED,
        )
        # Importing provider_health must not pull in src.secrets at all.
        self.assertNotIn("src.secrets", sys.modules)

    def test_provider_health_survives_stubbed_src_secrets_module(self):
        """Reproduce the PR #140 CI failure mode and prove the fix.

        Auth tests replace ``src.secrets`` with a helper-only stub.  Provider
        health must not import ``ConfigurationError`` from that stub.
        """
        _stub, restore = install_src_secrets_stub(
            get_secret_bool=lambda *args, **kwargs: False,
            get_secret=lambda *args, **kwargs: None,
        )
        self.addCleanup(restore)
        sys.modules.pop("integrations.provider_health", None)

        module = importlib.import_module("integrations.provider_health")
        from src.configuration_errors import ConfigurationError

        self.assertIs(module.ConfigurationError, ConfigurationError)
        self.assertFalse(hasattr(_stub, "ConfigurationError"))


if __name__ == "__main__":
    unittest.main()

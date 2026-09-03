"""Regression: auth-cookie secrets stubs must not leak into AF imports.

PR #140 CI failed with::

    ImportError: cannot import name 'get_secret' from 'src.secrets'

because auth/cookie tests replaced ``sys.modules['src.secrets']`` with a reduced
stub that persisted for the rest of the unittest process.  This module proves
that after the auth-cookie suite runs, Alternative Finder imports still succeed
in the same interpreter — without clearing ``src.secrets`` first.
"""
from __future__ import annotations

import importlib
import sys
import unittest


class SecretsStubIsolationRegressionTests(unittest.TestCase):
    def test_mouser_and_alternative_engine_import_after_auth_cookie_suite(self):
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromName("tests.test_auth_cookie_read_bridge")
        result = unittest.TestResult()
        suite.run(result)
        self.assertTrue(
            result.wasSuccessful(),
            "auth-cookie suite must pass before isolation check; "
            f"errors={result.errors!r} failures={result.failures!r}",
        )

        # Do not pop or "fix" src.secrets here — that would hide a leaked stub.
        # Only drop downstream modules so this check re-exercises their imports.
        for name in list(sys.modules):
            if (
                name.startswith("integrations.mouser")
                or name.startswith("integrations.supplier_aggregator")
                or name.startswith("src.alternative_engine")
            ):
                sys.modules.pop(name, None)

        mouser = importlib.import_module("integrations.mouser_client")
        engine = importlib.import_module("src.alternative_engine")
        from src.secrets import get_secret

        secrets_mod = sys.modules["src.secrets"]
        self.assertIsNotNone(
            getattr(secrets_mod, "__file__", None),
            "src.secrets must be the real module after auth-cookie tests, not a stub",
        )
        self.assertTrue(callable(get_secret))
        self.assertTrue(hasattr(mouser, "__file__"))
        self.assertTrue(
            hasattr(engine, "find_alternatives")
            or hasattr(engine, "get_alternative_discovery_metadata")
        )


if __name__ == "__main__":
    unittest.main()

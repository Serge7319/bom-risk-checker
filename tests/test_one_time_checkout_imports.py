"""Guard the authenticated one-time report checkout from unresolved imports."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


RUNTIME_PATH = Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py"


class OneTimeCheckoutImportTests(unittest.TestCase):
    def test_bom_analyzer_calls_the_imported_checkout_helpers(self) -> None:
        tree = ast.parse(RUNTIME_PATH.read_text(encoding="utf-8"))
        run_app = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_authenticated_app"
        )
        aliases = {
            alias.name: alias.asname or alias.name
            for node in ast.walk(run_app)
            if isinstance(node, ast.ImportFrom) and node.module == "src.one_time_bom"
            for alias in node.names
        }
        calls = {
            node.func.id
            for node in ast.walk(run_app)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        for helper in ("pending_checkout", "price_label"):
            self.assertIn(aliases[helper], calls)

        self.assertNotIn("one_time_pending_checkout", calls)
        self.assertNotIn("one_time_price_label", calls)


if __name__ == "__main__":
    unittest.main()

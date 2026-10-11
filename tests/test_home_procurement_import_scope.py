from __future__ import annotations

import symtable
import unittest
from pathlib import Path


class HomeProcurementImportScopeTests(unittest.TestCase):
    def test_home_callable_is_not_shadowed_by_page_local_import(self):
        source_path = Path(__file__).resolve().parents[1] / "src/authenticated_runtime.py"
        source = source_path.read_text()
        module_scope = symtable.symtable(source, str(source_path), "exec")
        function_scope = next(
            child for child in module_scope.get_children()
            if child.get_name() == "run_authenticated_app"
        )
        self.assertNotIn("build_procurement_advisor", function_scope.get_locals())


if __name__ == "__main__":
    unittest.main()

"""Compilation and layout regressions for the authenticated Cadivor runtime."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AuthenticatedRuntimeSyntaxTests(unittest.TestCase):
    def test_authenticated_runtime_compiles(self) -> None:
        source_path = ROOT / "src" / "authenticated_runtime.py"
        compile(source_path.read_text(encoding="utf-8"), str(source_path), "exec")

    def test_bom_workspace_keeps_only_primary_analysis_and_saved_manager(self) -> None:
        source = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")

        self.assertIn('input_col = st.container()', source)
        self.assertIn('def _render_saved_bom_manager()', source)
        self.assertIn('_render_saved_bom_manager()\n\n        sample_mode', source)
        self.assertNotIn('guidance_col, saved_manager_col = st.columns', source)


if __name__ == "__main__":
    unittest.main()

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

        self.assertIn('input_col, saved_manager_col = st.columns([0.46, 0.54], gap="large")', source)
        self.assertIn('def _render_saved_bom_manager()', source)
        self.assertIn('with saved_manager_col:\n            _render_saved_bom_manager()', source)
        self.assertIn('bom8-primary-card bom8-upload-card', source)
        self.assertIn('bom8-primary-card bom8-saved-card', source)
        self.assertNotIn('workflow_steps(["Prepare", "Upload", "Analyze", "Review"], active=1)', source)
        self.assertIn('if app_mode in {"BOM Analyzer", "High Risk Review"}:', source)
        self.assertIn('"High Risk Review",', source)
        self.assertIn('if st.session_state.get("bom81_high_risk_review"):', source)
        self.assertIn('and not _incoming_high_risk_review:', source)
        self.assertIn('card_columns = st.columns(2, gap="large")', source)
        self.assertIn('open_saved_bom(\n                                        analysis_id_value,', source)
        self.assertNotIn('guidance_col, saved_manager_col = st.columns', source)


if __name__ == "__main__":
    unittest.main()

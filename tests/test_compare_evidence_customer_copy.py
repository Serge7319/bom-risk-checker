"""Customer-facing evidence copy stays clear of implementation diagnostics."""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path
from typing import Any

from src.safe_diagnostics import safe_exception_frames


ROOT = Path(__file__).resolve().parents[1]
DATASHEET_SOURCE = (ROOT / "src" / "datasheet_comparison.py").read_text(
    encoding="utf-8"
)
APPROVED_PAGES_SOURCE = (ROOT / "src" / "ui" / "approved_pages.py").read_text(
    encoding="utf-8"
)
BROWSER_BRIDGE_SOURCE = (ROOT / "src" / "components" / "browser_navigation" / "index.html").read_text(
    encoding="utf-8"
)
TRANSITION_SOURCE = (ROOT / "src" / "ui" / "main_transition.py").read_text(
    encoding="utf-8"
)
MONITORING_CSS_SOURCE = (ROOT / "src" / "assets" / "css" / "monitoring_home_alignment.css").read_text(
    encoding="utf-8"
)


def _load_customer_copy():
    tree = ast.parse(DATASHEET_SOURCE)
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "customer_facing_evidence_text"
    )
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {"Any": Any, "re": re}
    exec(compile(ast.fix_missing_locations(module), "<customer-evidence>", "exec"), namespace)
    return namespace["customer_facing_evidence_text"]


class CompareEvidenceCustomerCopyTests(unittest.TestCase):
    def test_navigation_uses_one_loader_without_outgoing_dom_clones(self):
        self.assertNotIn("captureTransitionSnapshot", BROWSER_BRIDGE_SOURCE)
        self.assertNotIn("source.cloneNode(true)", BROWSER_BRIDGE_SOURCE)
        self.assertIn("if (pythonCover)", BROWSER_BRIDGE_SOURCE)
        self.assertIn('class="cv-main-transition-skeleton"', TRANSITION_SOURCE)
        self.assertIn('class="cv-transition-table"', TRANSITION_SOURCE)

    def test_monitoring_kpi_wrapper_stretches_to_the_shared_canvas(self):
        self.assertIn(
            'section[data-testid="stMain"]:has(.st-key-monitoring_home_width_marker)',
            MONITORING_CSS_SOURCE,
        )
        self.assertIn("flex: 1 1 100% !important;", MONITORING_CSS_SOURCE)
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr)) !important;", MONITORING_CSS_SOURCE)

    def test_supplier_diagnostics_are_rewritten_but_source_citations_remain(self):
        sanitize = _load_customer_copy()
        raw = (
            "Part A DigiKey authorized API does not state this field. "
            "Part A value is from the supplier catalog. "
            "Source URL: https://example.com/item?token=private "
            "Source field label: Mounting style. Extraction method: native PDF text."
        )
        shown = sanitize(raw)
        self.assertNotIn("API", shown)
        self.assertNotIn("catalog", shown.casefold())
        self.assertNotIn("Source URL", shown)
        self.assertNotIn("token=private", shown)
        self.assertIn("DigiKey listing", shown)
        self.assertIn("Source label: Mounting style", shown)

    def test_live_compare_renderer_uses_customer_copy_before_display(self):
        compare = APPROVED_PAGES_SOURCE.split("def render_compare_live", 1)[1].split(
            "def render_datasheet_live", 1
        )[0]
        self.assertIn("customer_facing_evidence_text", compare)
        self.assertIn('row.get("Evidence") or row.get("evidence") or ""', compare)

    def test_failure_hint_identifies_code_location_without_exception_payload(self):
        def fail_with_private_value():
            raise ValueError("PRIVATE-MPN-DO-NOT-LOG")

        try:
            fail_with_private_value()
        except ValueError as exc:
            hint = safe_exception_frames(exc)
        self.assertIn("fail_with_private_value", hint)
        self.assertIn("test_compare_evidence_customer_copy.py", hint)
        self.assertNotIn("PRIVATE-MPN-DO-NOT-LOG", hint)


if __name__ == "__main__":
    unittest.main()

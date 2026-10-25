"""Route-state marker used to recover a missed browser Back/Forward rerun."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

from src.browser_navigation import serialize_browser_route_state
from src.bom_upload_flow import fail_approved_bom_summary_save


ROOT = Path(__file__).resolve().parents[1]


class BrowserRouteStateTests(unittest.TestCase):
    def test_route_state_serialization_matches_normalized_browser_query(self):
        serialized = serialize_browser_route_state(
            {
                "return_analysis_id": "synthetic-analysis-1",
                "auth": "discard-me",
                "analysis_tab": "Engineering Decisions",
                "page": "Compare Parts",
                "source": "discard-me-too",
                "empty": " ",
            },
            route="Analysis Details",
        )

        self.assertEqual(
            json.loads(serialized),
            [
                ["analysis_tab", "Engineering Decisions"],
                ["page", "Analysis Details"],
                ["return_analysis_id", "synthetic-analysis-1"],
            ],
        )

    def test_unarmed_route_change_uses_compact_navigation_cover(self):
        source = (ROOT / "src" / "ui" / "main_transition.py").read_text(encoding="utf-8")
        helper = next(
            node for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_infer_unarmed_transition_kind"
        )
        module = ast.Module(body=[helper], type_ignores=[])
        namespace = {}
        exec(compile(ast.fix_missing_locations(module), "<transition-kind>", "exec"), namespace)
        infer_kind = namespace["_infer_unarmed_transition_kind"]
        self.assertEqual(infer_kind("Monitoring", "Analysis Details"), "navigation")
        self.assertEqual(infer_kind("BOM Analyzer", ""), "")

        prepare = source.split("def prepare_main_transition", 1)[1].split(
            "def _paint_main_transition_markup", 1
        )[0]
        self.assertIn("if not state.get(MAIN_TRANSITION_ACTIVE_KEY):", prepare)
        self.assertIn("_infer_unarmed_transition_kind(route, previous_route)", prepare)

    def test_analysis_summary_save_failure_clears_stale_progress_and_shows_recovery(self):
        upload = object()
        message = "Workspace denied the analysis summary save (42501)."
        state = {
            "cadivor_bom_pipeline_active": True,
            "bom8_analysis_upload_file": upload,
            "bom8_analysis_pending": True,
            "bom8_analysis_in_progress": True,
            "bom8_analysis_future": object(),
            "results_df": object(),
            "analysis_saved": False,
            "analysis_id": "unsaved-analysis",
            "health_score": 12,
            "health_status": "Critical",
            "show_analysis_success_29b": True,
            "cadivor_active_analysis_id": "unsaved-analysis",
            "cadivor_active_analysis_tab": "Engineering Intelligence",
            "cadivor_saved_bom_rerun_active": True,
            "cadivor_one_time_pending_source_filename": "synthetic.csv",
            "cadivor_one_time_pending_component_count": 5,
            "bom_file_uploader": upload,
        }

        fail_approved_bom_summary_save(state, message=message)

        self.assertTrue(state["cadivor_bom_upload_open"])
        self.assertEqual(state["cadivor_bom_analysis_error"], message)
        self.assertIs(state["bom_file_uploader"], upload)
        for key in (
            "cadivor_bom_pipeline_active",
            "bom8_analysis_upload_file",
            "bom8_analysis_pending",
            "bom8_analysis_in_progress",
            "bom8_analysis_future",
            "results_df",
            "analysis_id",
            "cadivor_active_analysis_id",
            "cadivor_saved_bom_rerun_active",
            "cadivor_one_time_pending_source_filename",
            "cadivor_one_time_pending_component_count",
        ):
            self.assertNotIn(key, state)

        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        save_block = runtime.split(
            'analysis_response = supabase.table("analyses").insert', 1
        )[1].split("from src.part_images import normalize_supplier_image_url", 1)[0]
        self.assertIn("fail_approved_bom_summary_save(", save_block)
        self.assertIn("st.rerun()", save_block)

        approved_pages = (ROOT / "src" / "ui" / "approved_pages.py").read_text(encoding="utf-8")
        catalog = approved_pages.split("def render_bom_catalog(", 1)[1].split(
            "\ndef ", 1
        )[0]
        self.assertIn("st.error(analysis_error)", catalog)


    def test_page_marker_and_popstate_watchdog_share_route_state(self):
        auth_gate = (ROOT / "src" / "auth_gate.py").read_text(encoding="utf-8")
        bridge = (
            ROOT / "src" / "components" / "browser_navigation" / "index.html"
        ).read_text(encoding="utf-8")

        self.assertIn('data-cadivor-route-state="{route_state}"', auth_gate)
        self.assertIn('if (reason === "popstate") {', bridge)
        self.assertIn("showHistoryTransition(href);", bridge)
        self.assertIn("scheduleRouteRecovery(href);", bridge)
        self.assertIn('marker.getAttribute("data-cadivor-route-state")', bridge)
        self.assertIn('w.history.scrollRestoration = "manual"', bridge)
        manual_setting = bridge.index('try { w.history.scrollRestoration = "manual"; } catch (_) {}')
        popstate_listener = bridge.index('w.addEventListener("popstate"')
        self.assertLess(manual_setting, popstate_listener)
        self.assertIn('doc.querySelector(\'[data-testid="stMain"]\')', bridge)
        self.assertIn('main.querySelectorAll("*")', bridge)
        self.assertIn("stableTopChecks >= 2", bridge)
        self.assertIn('w.addEventListener("pageshow"', bridge)
        self.assertIn('data-cadivor-history-transition', bridge)
        self.assertIn("finishHistoryTransition();", bridge)
        self.assertIn("w.location.reload()", bridge)

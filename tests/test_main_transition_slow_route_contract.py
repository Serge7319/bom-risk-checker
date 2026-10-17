"""Regression contract for slow-route transition ownership."""
from __future__ import annotations

import ast
import html
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, MutableMapping


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "ui" / "main_transition.py").read_text(encoding="utf-8")


class MainTransitionSlowRouteContractTests(unittest.TestCase):
    def test_opening_clips_the_complete_main_viewport(self):
        self.assertIn(
            "width:calc(100vw - var(--cv-foundation-rail,228px))!important",
            SOURCE,
        )
        self.assertIn("clip-path:inset(0)!important", SOURCE)
        self.assertIn("z-index:2147483000!important", SOURCE)
        self.assertIn("pointer-events:auto!important", SOURCE)
        self.assertIn(
            '> [data-testid="stElementContainer"][data-stale="true"]:not(',
            SOURCE,
        )

    def test_route_cover_is_painted_before_shell_role_lookup(self):
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        cover = runtime.index(
            'mount_main_transition_loading(_shell_route, paint_markup=True)'
        )
        role_lookup = runtime.index("def _read_users_role_for_shell")
        self.assertLess(cover, role_lookup)

    def test_transition_content_is_portaled_out_of_streamlit_column_wrappers(self):
        paint = SOURCE.split("def _paint_main_transition_markup", 1)[1].split(
            "def _remove_transition_portal", 1
        )[0]
        self.assertIn("window.parent", paint)
        self.assertIn('portalId = "cadivor-main-transition-portal"', paint)
        self.assertIn("components.html(portal_script, height=0, width=0)", paint)
        self.assertIn("new parentWindow.MutationObserver", paint)
        self.assertNotIn("with container(key=owner_key)", paint)

    def test_revealed_route_removes_its_transition_portal(self):
        reveal = SOURCE.split("def reveal_main_transition", 1)[1]
        self.assertIn("_remove_transition_portal(gen)", reveal)

    def test_dashboard_cover_is_released_after_dashboard_render(self):
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        start = runtime.index("# ---------- Dashboard ----------")
        end = runtime.index('if app_mode == "Analysis Details":', start)
        dashboard = runtime[start:end]
        self.assertNotIn('reveal_authenticated_page_body("Dashboard")', dashboard)
        self.assertIn("render_home(", dashboard)
        self.assertIn("stop_authenticated_page()", dashboard)

    def test_every_real_route_change_keeps_opening_owner_even_with_warm_cache(self):
        tree = ast.parse(SOURCE)
        helper = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "should_paint_opening_overlay"
        )
        module = ast.Module(
            body=[
                ast.ImportFrom(
                    module="__future__",
                    names=[ast.alias(name="annotations")],
                    level=0,
                ),
                helper,
            ],
            type_ignores=[],
        )
        namespace = {
            "Any": Any,
            "MutableMapping": MutableMapping,
            "st": SimpleNamespace(session_state={}),
            "MAIN_TRANSITION_ROUTE_KEY": "cadivor_main_transition_route",
            "MAIN_TRANSITION_ACTIVE_KEY": "cadivor_main_transition_active",
            "PRESENTED_ROUTE_KEY": "cadivor_presented_route",
            "BOM_ANALYSIS_TRANSITION_KEY": "cadivor_bom_analysis_transition",
        }
        exec(compile(ast.fix_missing_locations(module), "<transition>", "exec"), namespace)
        should_paint = namespace["should_paint_opening_overlay"]
        state = {
            "cadivor_foundation_shell_mounted": True,
            "cadivor_main_transition_active": True,
            "cadivor_presented_route": "Reports",
        }

        self.assertTrue(
            should_paint(
                needs_transition=True,
                target_route="Dashboard",
                session_state=state,
            )
        )
        self.assertTrue(
            should_paint(
                needs_transition=True,
                target_route="Analysis Details",
                session_state=state,
            )
        )
        self.assertTrue(
            should_paint(
                needs_transition=True,
                target_route="Engineering Decisions",
                session_state=state,
            )
        )
        self.assertTrue(
            should_paint(
                needs_transition=True,
                target_route="BOM Settings",
                session_state=state,
            )
        )

        self.assertTrue(
            should_paint(
                needs_transition=True,
                target_route="Dashboard",
                session_state={"cadivor_foundation_shell_mounted": True},
            )
        )

        analysis_state = {
            "cadivor_foundation_shell_mounted": True,
            "cadivor_bom_analysis_transition": "start",
        }
        self.assertTrue(
            should_paint(
                needs_transition=True,
                target_route="BOM Analyzer",
                session_state=analysis_state,
            )
        )
        self.assertFalse(
            should_paint(
                needs_transition=False,
                target_route="Dashboard",
                session_state=state,
            )
        )

    def test_analysis_start_and_rerun_have_specific_loading_copy(self):
        tree = ast.parse(SOURCE)
        helper = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "route_loading_markup"
        )
        module = ast.Module(
            body=[
                ast.ImportFrom(
                    module="__future__",
                    names=[ast.alias(name="annotations")],
                    level=0,
                ),
                helper,
            ],
            type_ignores=[],
        )
        namespace = {
            "html": html,
            "BOM_ANALYSIS_TRANSITION_KEY": "cadivor_bom_analysis_transition",
            "st": SimpleNamespace(session_state={}),
        }
        exec(compile(ast.fix_missing_locations(module), "<transition-copy>", "exec"), namespace)
        render = namespace["route_loading_markup"]

        namespace["st"].session_state["cadivor_bom_analysis_transition"] = "start"
        start = render("BOM Analyzer", 1)
        self.assertIn("Starting BOM analysis…", start)

        namespace["st"].session_state["cadivor_bom_analysis_transition"] = "rerun"
        rerun = render("BOM Analyzer", 2)
        self.assertIn("Rerunning BOM analysis…", rerun)
        self.assertIn("Refreshing supplier, lifecycle, lead-time, and pricing evidence", rerun)


if __name__ == "__main__":
    unittest.main()

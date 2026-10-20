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
        self.assertIn('[data-stale="true"]:not(', SOURCE)

    def test_route_cover_is_painted_before_shell_role_lookup(self):
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        cover = runtime.index(
            'mount_main_transition_loading(_shell_route, paint_markup=True)'
        )
        role_lookup = runtime.index("def _read_users_role_for_shell")
        self.assertLess(cover, role_lookup)

    def test_transition_cover_uses_synchronous_non_iframe_html(self):
        paint = SOURCE.split("def _paint_main_transition_markup", 1)[1].split(
            "def paint_prepared_main_transition", 1
        )[0]
        self.assertIn("st.html(route_loading_markup(route, gen))", paint)
        self.assertNotIn("components.html(", paint)
        self.assertNotIn("window.parent", paint)
        self.assertNotIn("with container(key=owner_key)", paint)

    def test_regular_navigation_holds_ready_page_until_destination_is_complete(self):
        namespace = {
            "html": html,
            "BOM_ANALYSIS_TRANSITION_KEY": "cadivor_bom_analysis_transition",
            "MAIN_TRANSITION_KIND_KEY": "cadivor_main_transition_kind",
            "MAIN_TRANSITION_PREVIOUS_ROUTE_KEY": "cadivor_main_transition_previous_route",
            "st": SimpleNamespace(session_state={
                "cadivor_main_transition_kind": "navigation",
                "cadivor_main_transition_previous_route": "Engineering Decisions",
            }),
        }
        helper = next(
            node for node in ast.parse(SOURCE).body
            if isinstance(node, ast.FunctionDef) and node.name == "route_loading_markup"
        )
        module = ast.Module(body=[helper], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), "<route-loading>", "exec"), namespace)
        markup = namespace["route_loading_markup"]("Portfolio Intelligence", 21)
        self.assertIn('data-cadivor-transition-kind="navigation"', markup)
        self.assertIn("cv-main-transition-progress", markup)
        self.assertNotIn("Opening Portfolio Intelligence", markup)
        nav_css = SOURCE.split(
            '.cv-main-transition.cv-route-loading[data-cadivor-transition-kind="navigation"]{{',
            1,
        )[1].split("}}", 1)[0]
        self.assertIn("height:calc(100dvh - var(--cv-foundation-top,64px))!important", nav_css)
        self.assertIn("background:transparent!important", nav_css)
        self.assertIn("pointer-events:none!important", nav_css)
        self.assertIn("st-key-cadivor_authenticated_route_body", SOURCE)
        self.assertIn(
            '[data-testid="stElementContainer"]:not([data-stale="true"])',
            SOURCE,
        )
        self.assertIn(
            "visibility:hidden!important;opacity:0!important;pointer-events:none!important",
            SOURCE,
        )
        self.assertIn("the last ready page visible", SOURCE)
        self.assertIn(
            ':not([data-cadivor-transition-kind="navigation"]) {{\n          pointer-events:auto!important',
            SOURCE,
        )

    def test_reveal_marker_hides_the_matching_transition_generation(self):
        reveal = SOURCE.split("def reveal_main_transition", 1)[1]
        self.assertIn("data-cadivor-page-body", reveal)
        self.assertNotIn("_remove_transition_portal", reveal)

    def test_alternative_finder_is_visible_before_synchronous_supplier_lookup(self):
        approved_pages = (ROOT / "src" / "ui" / "approved_pages.py").read_text(
            encoding="utf-8"
        )
        finder = approved_pages.split("def render_replacement_search()", 1)[1].split(
            "\ndef ", 1
        )[0]
        reveal_at = finder.index('reveal_authenticated_page_body("Alternative Finder")')
        supplier_lookup_at = finder.index(
            "run_alternative_finder_search(st.session_state, query)"
        )
        self.assertLess(reveal_at, supplier_lookup_at)

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
            "MAIN_TRANSITION_KIND_KEY": "cadivor_main_transition_kind",
            "MAIN_TRANSITION_PREVIOUS_ROUTE_KEY": "cadivor_main_transition_previous_route",
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
        self.assertIn("position:fixed;left:var(--cv-foundation-rail,0px)", rerun)
        self.assertIn("display:flex;align-items:center;justify-content:center", rerun)
        self.assertIn("width:min(420px,calc(100% - 48px))", rerun)


if __name__ == "__main__":
    unittest.main()

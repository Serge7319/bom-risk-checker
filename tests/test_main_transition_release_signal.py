from __future__ import annotations

import unittest
from unittest.mock import patch

from src.ui.navigation import (
    NAV_SCROLL_RESET_PENDING_KEY,
    NAV_SCROLL_RESET_TOKEN_KEY,
    inject_nav_scroll_reset_if_needed,
)

from src.ui.main_transition import (
    DELAY_ROUTE_BODY_REVEAL_KEY,
    MAIN_TRANSITION_ACTIVE_KEY,
    MAIN_TRANSITION_GEN_KEY,
    MAIN_TRANSITION_KIND_KEY,
    MAIN_TRANSITION_ROUTE_KEY,
    inject_main_transition_css,
    reveal_main_transition,
)


class MainTransitionReleaseSignalTests(unittest.TestCase):
    def test_reveal_publishes_generation_as_direct_document_marker(self):
        state = {
            MAIN_TRANSITION_GEN_KEY: 812,
            MAIN_TRANSITION_ROUTE_KEY: "Dashboard",
            MAIN_TRANSITION_ACTIVE_KEY: True,
            MAIN_TRANSITION_KIND_KEY: "blocking",
            DELAY_ROUTE_BODY_REVEAL_KEY: True,
        }
        markdown = []
        html = []

        with (
            patch("src.ui.main_transition.st.session_state", state),
            patch(
                "src.ui.main_transition.st.markdown",
                side_effect=lambda value, **kwargs: markdown.append((value, kwargs)),
            ),
            patch(
                "src.ui.main_transition.st.html",
                side_effect=lambda value, **kwargs: html.append((value, kwargs)),
            ),
        ):
            reveal_main_transition("Dashboard")

        self.assertFalse(state[MAIN_TRANSITION_ACTIVE_KEY])
        self.assertNotIn(DELAY_ROUTE_BODY_REVEAL_KEY, state)
        self.assertEqual(markdown, [])
        self.assertEqual(len(html), 1)
        self.assertIn('data-cadivor-page-body-gen="812"', html[0][0])
        self.assertIn('data-cadivor-page-body-release-gen="812"', html[0][0])
        self.assertNotIn("<script", html[0][0])
        self.assertEqual(html[0][1], {})

    def test_navigation_reveal_publishes_release_gen_with_body_marker(self):
        """Final navigation reveals must release Opening immediately.

        Mid-route early reveals stay deferred via should_defer_navigation_reveal.
        Once reveal_main_transition runs, publish release-gen so the cover does
        not wait on flaky scroll settle.
        """
        state = {
            MAIN_TRANSITION_GEN_KEY: 814,
            MAIN_TRANSITION_ROUTE_KEY: "Monitoring",
            MAIN_TRANSITION_ACTIVE_KEY: True,
            MAIN_TRANSITION_KIND_KEY: "navigation",
            DELAY_ROUTE_BODY_REVEAL_KEY: True,
        }
        html = []

        with (
            patch("src.ui.main_transition.st.session_state", state),
            patch("src.ui.main_transition.st.markdown"),
            patch(
                "src.ui.main_transition.st.html",
                side_effect=lambda value, **kwargs: html.append((value, kwargs)),
            ),
        ):
            reveal_main_transition("Monitoring")

        self.assertIn('data-cadivor-page-body-gen="814"', html[0][0])
        self.assertIn('data-cadivor-page-body-release-gen="814"', html[0][0])

    def test_transition_css_uses_direct_document_marker_generation(self):
        state = {}
        markdown = []
        html = []

        with (
            patch("src.ui.main_transition.st.session_state", state),
            patch(
                "src.ui.main_transition.st.markdown",
                side_effect=lambda value, **kwargs: markdown.append(value),
            ),
            patch(
                "src.ui.main_transition.st.html",
                side_effect=lambda value, **kwargs: html.append((value, kwargs)),
            ),
        ):
            inject_main_transition_css(813)

        css = markdown[0]
        self.assertIn(
            'body:has([data-cadivor-page-body-gen="813"][data-cadivor-page-body-release-gen="813"])',
            css,
        )
        self.assertIn('body:not(:has([data-cadivor-page-body-gen="813"]))', css)
        self.assertNotIn('body[data-cadivor-page-body-gen="813"]', css)
        self.assertEqual(html, [])


    def test_active_navigation_requeues_a_missing_scroll_reset(self):
        state = {
            MAIN_TRANSITION_GEN_KEY: 815,
            MAIN_TRANSITION_ROUTE_KEY: "Dashboard",
            MAIN_TRANSITION_ACTIVE_KEY: True,
            MAIN_TRANSITION_KIND_KEY: "navigation",
            "cadivor_route": "Dashboard",
        }
        rendered = []

        with (
            patch("src.ui.navigation.st.session_state", state),
            patch(
                "src.ui.navigation.st.html",
                side_effect=lambda value, **kwargs: rendered.append((value, kwargs)),
            ),
        ):
            self.assertTrue(inject_nav_scroll_reset_if_needed())

        self.assertEqual(state[NAV_SCROLL_RESET_TOKEN_KEY], 1)
        self.assertNotIn(NAV_SCROLL_RESET_PENDING_KEY, state)
        self.assertEqual(len(rendered), 1)
        script, kwargs = rendered[0]
        self.assertIn('const transitionGen = "815";', script)
        self.assertNotIn("const transitionGen = 815;", script)
        self.assertIn("body.getAttribute(\n                  'data-cadivor-page-body-gen'\n                )", script)
        self.assertIn('data-cadivor-nav-scroll-token="1"', script)
        self.assertEqual(kwargs.get("unsafe_allow_javascript"), True)

    def test_navigation_release_keeps_a_generation_past_the_js_safe_integer(self):
        huge = 1_761_560_000_000_000_019
        state = {
            MAIN_TRANSITION_GEN_KEY: huge,
            MAIN_TRANSITION_ROUTE_KEY: "Compare Parts",
            MAIN_TRANSITION_ACTIVE_KEY: True,
            MAIN_TRANSITION_KIND_KEY: "navigation",
            "cadivor_route": "Compare Parts",
        }
        rendered = []

        with (
            patch("src.ui.navigation.st.session_state", state),
            patch(
                "src.ui.navigation.st.html",
                side_effect=lambda value, **kwargs: rendered.append(value),
            ),
        ):
            self.assertTrue(inject_nav_scroll_reset_if_needed())

        script = rendered[0]
        self.assertIn(f'const transitionGen = "{huge}";', script)
        self.assertNotIn(f"const transitionGen = {huge};", script)
        self.assertNotIn("String(state.transitionGen)", script)


if __name__ == "__main__":
    unittest.main()

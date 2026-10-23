from __future__ import annotations

import unittest
from unittest.mock import patch

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
        self.assertNotIn("<script", html[0][0])
        self.assertEqual(html[0][1], {})

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
        self.assertIn('body:has([data-cadivor-page-body-gen="813"])', css)
        self.assertIn('body:not(:has([data-cadivor-page-body-gen="813"]))', css)
        self.assertNotIn('body[data-cadivor-page-body-gen="813"]', css)
        self.assertEqual(html, [])


if __name__ == "__main__":
    unittest.main()

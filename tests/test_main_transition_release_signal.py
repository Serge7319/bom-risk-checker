from __future__ import annotations

from src.ui.main_transition import (
    MAIN_TRANSITION_ACTIVE_KEY,
    MAIN_TRANSITION_GEN_KEY,
    MAIN_TRANSITION_KIND_KEY,
    MAIN_TRANSITION_ROUTE_KEY,
    DELAY_ROUTE_BODY_REVEAL_KEY,
    inject_main_transition_css,
    reveal_main_transition,
)


def test_reveal_publishes_generation_on_document_body(monkeypatch):
    state = {
        MAIN_TRANSITION_GEN_KEY: 812,
        MAIN_TRANSITION_ROUTE_KEY: "Dashboard",
        MAIN_TRANSITION_ACTIVE_KEY: True,
        MAIN_TRANSITION_KIND_KEY: "blocking",
        DELAY_ROUTE_BODY_REVEAL_KEY: True,
    }
    markdown = []
    html = []
    monkeypatch.setattr("src.ui.main_transition.st.session_state", state)
    monkeypatch.setattr(
        "src.ui.main_transition.st.markdown",
        lambda value, **kwargs: markdown.append((value, kwargs)),
    )
    monkeypatch.setattr(
        "src.ui.main_transition.st.html",
        lambda value, **kwargs: html.append((value, kwargs)),
    )

    reveal_main_transition("Dashboard")

    assert state[MAIN_TRANSITION_ACTIVE_KEY] is False
    assert DELAY_ROUTE_BODY_REVEAL_KEY not in state
    assert len(markdown) == 1
    assert 'data-cadivor-transition-gen="812"' in markdown[0][0]
    assert len(html) == 1
    assert 'data-cadivor-page-body-gen", "812"' in html[0][0]
    assert html[0][1]["unsafe_allow_javascript"] is True


def test_transition_css_uses_document_ready_generation(monkeypatch):
    state = {}
    markdown = []
    monkeypatch.setattr("src.ui.main_transition.st.session_state", state)
    monkeypatch.setattr(
        "src.ui.main_transition.st.markdown",
        lambda value, **kwargs: markdown.append(value),
    )
    monkeypatch.setattr("src.ui.main_transition.st.html", lambda *_args, **_kwargs: None)

    inject_main_transition_css(813)

    css = markdown[0]
    assert 'body[data-cadivor-page-body-gen="813"]' in css
    assert 'body:not([data-cadivor-page-body-gen="813"])' in css
    assert 'body:has([data-cadivor-page-body][data-cadivor-transition-gen="813"])' not in css

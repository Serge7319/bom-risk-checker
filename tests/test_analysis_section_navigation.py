"""Sprint 71.9.1 — deterministic analysis section navigation tests."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from contextlib import contextmanager


def _install_streamlit_stub(session_state: dict | None = None, query_params: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    st.query_params = query_params if query_params is not None else {}
    st.markdown = lambda *args, **kwargs: None

    @contextmanager
    def _container(**kwargs):
        yield None

    st.container = _container
    st.radio = lambda label, options, horizontal=False, key=None, label_visibility=None: st.session_state.get(
        key, options[0]
    )
    sys.modules["streamlit"] = st
    sys.modules.setdefault("streamlit.components", types.ModuleType("streamlit.components"))
    sys.modules.setdefault("streamlit.components.v1", types.ModuleType("streamlit.components.v1"))
    return st


class _LazyStubModule(types.ModuleType):
    def __getattr__(self, attr: str):
        if attr.isupper():
            return attr
        return lambda *args, **kwargs: None


def _make_lazy_stub(name: str) -> types.ModuleType:
    return _LazyStubModule(name)


def _install_analysis_detail_import_stubs() -> None:
    sys.modules.setdefault("pandas", types.ModuleType("pandas"))

    navigation = types.ModuleType("src.ui.navigation")
    navigation.ALTERNATIVE_FINDER_PAGE = "Alternative Finder"
    navigation.internal_nav_button = lambda *args, **kwargs: None
    navigation.navigate_to = lambda *args, **kwargs: None
    navigation.alternative_finder_href = lambda *args, **kwargs: "?"
    sys.modules["src.ui.navigation"] = navigation

    urls = types.ModuleType("src.urls")
    urls.internal_app_href = lambda *args, **kwargs: "?"
    sys.modules["src.urls"] = urls

    decision_engine = types.ModuleType("src.engineering_decision_engine")
    decision_engine.WORKSPACE_CATEGORIES = ["Decision Overview"]
    for attr in (
        "build_engineering_decision_brief",
        "render_engineering_workspace_strip",
        "render_engineering_workspace_overview",
        "render_engineering_workspace_findings",
        "render_engineering_workspace_actions",
        "render_engineering_workspace_impact",
        "render_engineering_workspace_evidence",
        "get_cached_decision_brief",
        "cache_decision_brief",
        "decision_brief_cache_key",
        "parts_to_results_df",
    ):
        setattr(decision_engine, attr, lambda *args, **kwargs: None)
    sys.modules["src.engineering_decision_engine"] = decision_engine

    assistant = types.ModuleType("src.components.engineering_assistant")
    assistant.render_engineering_assistant = lambda **kwargs: None
    sys.modules["src.components.engineering_assistant"] = assistant

    for name in (
        "src.ai_advisor",
        "src.ui.performance_cache",
        "src.services.engineering_context",
        "src.services.knowledge_graph",
        "src.components.review",
        "src.engineering_review_service",
        "src.discussion_service",
    ):
        sys.modules.setdefault(name, _make_lazy_stub(name))


class AnalysisSectionNavigationTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("src.pages.analysis_detail", None)

    def _load(self, session_state=None, query_params=None):
        st = _install_streamlit_stub(session_state, query_params)
        _install_analysis_detail_import_stubs()
        detail = importlib.import_module("src.pages.analysis_detail")
        return st, detail

    def test_widget_selection_overrides_stale_url(self):
        st, detail = self._load(
            session_state={
                "cadivor_active_analysis_tab": "Engineering Intelligence",
                "cadivor_analysis_section_a-1": "Overview",
            },
            query_params={"analysis_tab": "Engineering Intelligence"},
        )
        detail._sync_cadivor_active_analysis_tab(analysis_id="a-1")
        active = detail._render_analysis_section_navigation(analysis_id="a-1")
        self.assertEqual(active, "Overview")
        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Overview")
        self.assertEqual(st.query_params["analysis_tab"], "Overview")

    def test_components_selection_commits_state_and_url(self):
        st, detail = self._load(
            session_state={"cadivor_analysis_section_a-2": "Components"},
            query_params={"analysis_tab": "Engineering Intelligence"},
        )
        detail._sync_cadivor_active_analysis_tab(analysis_id="a-2")
        active = detail._render_analysis_section_navigation(analysis_id="a-2")
        self.assertEqual(active, "Components")
        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Components")
        self.assertEqual(st.query_params["analysis_tab"], "Components")

    def test_deep_link_url_initializes_when_widget_unbound(self):
        st, detail = self._load(
            session_state={},
            query_params={"analysis_tab": "Ask+Cadivor"},
        )
        detail._sync_cadivor_active_analysis_tab(analysis_id="a-3")
        active = detail._render_analysis_section_navigation(analysis_id="a-3")
        self.assertEqual(active, "Ask Cadivor")
        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Ask Cadivor")
        self.assertEqual(st.query_params["analysis_tab"], "Ask Cadivor")

    def test_all_nine_sections_map_to_render_branches(self):
        _, detail = self._load()
        source_path = detail.__file__
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()
        for section in detail.ANALYSIS_SECTIONS:
            self.assertIn(f'if active_tab == "{section}":', source)

    def test_pending_section_consumed_before_widget_render(self):
        st, detail = self._load(
            session_state={
                "cadivor_analysis_section_a-pending": "Overview",
                "cadivor_pending_analysis_section": "Ask Cadivor",
                "cadivor_pending_analysis_section_id": "a-pending",
                "cadivor_active_analysis_tab": "Ask Cadivor",
            },
        )
        active = detail._render_analysis_section_navigation(analysis_id="a-pending")
        self.assertEqual(active, "Ask Cadivor")
        self.assertEqual(st.session_state["cadivor_analysis_section_a-pending"], "Ask Cadivor")
        self.assertNotIn("cadivor_pending_analysis_section", st.session_state)

    def test_pending_section_ignored_for_other_analysis(self):
        st, detail = self._load(
            session_state={
                "cadivor_analysis_section_a-other": "Timeline",
                "cadivor_pending_analysis_section": "Ask Cadivor",
                "cadivor_pending_analysis_section_id": "a-target",
            },
        )
        active = detail._render_analysis_section_navigation(analysis_id="a-other")
        self.assertEqual(active, "Timeline")
        self.assertEqual(st.session_state["cadivor_pending_analysis_section"], "Ask Cadivor")

    def test_pinned_ask_cadivor_overrides_stale_url_when_widget_unbound(self):
        st, detail = self._load(
            session_state={"cadivor_active_analysis_tab": "Ask Cadivor"},
            query_params={"analysis_tab": "Engineering Intelligence"},
        )
        detail._sync_cadivor_active_analysis_tab(analysis_id="a-copilot")
        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Ask Cadivor")
        self.assertEqual(st.session_state["cadivor_analysis_section_a-copilot"], "Ask Cadivor")

    def test_analysis_change_resets_widget_and_hydrates_from_url(self):
        st, detail = self._load(
            session_state={
                "cadivor_analysis_section_sync_id": "old-id",
                "cadivor_analysis_section_old-id": "Timeline",
                "cadivor_active_analysis_tab": "Timeline",
            },
            query_params={"analysis_tab": "Reports"},
        )
        detail._sync_cadivor_active_analysis_tab(analysis_id="new-id")
        self.assertEqual(st.session_state["cadivor_active_analysis_tab"], "Reports")
        self.assertEqual(st.session_state["cadivor_analysis_section_new-id"], "Reports")
        self.assertEqual(st.session_state["cadivor_analysis_section_sync_id"], "new-id")


if __name__ == "__main__":
    unittest.main()

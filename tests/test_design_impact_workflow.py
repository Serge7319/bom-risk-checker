"""Functional checks for the Design Impact selection and review workflow."""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from src import design_impact_analyzer as impact


ROOT = Path(__file__).resolve().parents[1]


def _impact_data(selected_mpn: str = "IC-100"):
    analyses = [
        {"id": "bom-1", "project_name": "Gateway", "health_score": 72},
        {"id": "bom-2", "project_name": "Sensor", "health_score": 88},
    ]
    parts = [
        {
            "analysis_id": "bom-1",
            "mpn": "IC-100",
            "manufacturer": "Acme",
            "risk_score": 62,
            "risk_level": "High",
            "lifecycle_status": "Active",
            "package": "QFN",
            "pin_count": 32,
            "supplier_count": 2,
            "stock_available": 120,
        },
        {
            "analysis_id": "bom-2",
            "mpn": "IC-100",
            "manufacturer": "Acme",
            "risk_score": 38,
            "risk_level": "Medium",
            "lifecycle_status": "Active",
            "package": "QFN",
            "pin_count": 32,
            "supplier_count": 3,
            "stock_available": 80,
        },
        {
            "analysis_id": "bom-2",
            "mpn": "CAP-220",
            "manufacturer": "Parts Co",
            "risk_score": 10,
            "risk_level": "Low",
            "lifecycle_status": "Active",
            "package": "0603",
            "supplier_count": 4,
            "stock_available": 900,
        },
    ]
    return impact.build_design_impact(analyses, parts, selected_mpn)


def test_selected_part_shows_only_its_affected_saved_projects():
    result = _impact_data("IC-100")

    assert result["selected_mpn"] == "IC-100"
    assert result["available_mpns"] == ["CAP-220", "IC-100"]
    assert result["project_count"] == 2
    assert {row["Project"] for row in result["affected_projects"]} == {"Gateway", "Sensor"}


class _Rerun(Exception):
    pass


class _FakeStreamlit:
    def __init__(self, *, selected: str, submit: bool):
        self.session_state = {}
        self.selected = selected
        self.submit = submit
        self.button_label = ""
        self.messages = []

    def markdown(self, *args, **kwargs):
        return None

    def form(self, *args, **kwargs):
        return nullcontext()

    def selectbox(self, *args, **kwargs):
        return self.selected

    def form_submit_button(self, label, **kwargs):
        self.button_label = label
        return self.submit

    def caption(self, message):
        self.messages.append(message)

    def info(self, message):
        self.messages.append(message)

    def rerun(self):
        raise _Rerun


def test_start_impact_review_saves_the_selected_part_and_reruns(monkeypatch):
    fake_st = _FakeStreamlit(selected="CAP-220", submit=True)
    monkeypatch.setattr(impact, "st", fake_st)
    monkeypatch.setattr(impact, "_css", lambda: None)
    monkeypatch.setattr(impact, "cadivor_section_header", lambda *args, **kwargs: None)

    with pytest.raises(_Rerun):
        impact.render_design_impact(
            intelligence={
                "available_mpns": ["CAP-220", "IC-100"],
                "selected_mpn": "IC-100",
            },
            internal_nav_button=lambda *args, **kwargs: None,
            review_started=False,
        )

    assert fake_st.button_label == "Start impact review"
    assert fake_st.session_state["design_impact_mpn"] == "CAP-220"


def test_review_prompt_waits_for_start_before_rendering_assessment(monkeypatch):
    fake_st = _FakeStreamlit(selected="IC-100", submit=False)
    monkeypatch.setattr(impact, "st", fake_st)
    monkeypatch.setattr(impact, "_css", lambda: None)
    monkeypatch.setattr(impact, "cadivor_section_header", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        impact,
        "render_kpi_row_safe",
        lambda *args, **kwargs: pytest.fail("impact results should wait for review submission"),
    )

    impact.render_design_impact(
        intelligence={
            "available_mpns": ["CAP-220", "IC-100"],
            "selected_mpn": "IC-100",
        },
        internal_nav_button=lambda *args, **kwargs: None,
        review_started=False,
    )

    assert fake_st.button_label == "Start impact review"
    assert any("start the review" in message for message in fake_st.messages)


def test_runtime_uses_a_single_design_impact_page_with_start_context():
    runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
    section = runtime.split('if app_mode == "Design Impact Analyzer":', 1)[1].split(
        "# ---------- Portfolio Intelligence ----------", 1
    )[0]

    assert "render_simple_workspace(" not in section
    assert 'legacy_label="Start impact review"' not in section
    assert "review_started=bool(" in section

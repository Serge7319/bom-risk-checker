"""Functional checks for the Design Impact selection and review workflow."""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import design_impact_analyzer as impact


ROOT = Path(__file__).resolve().parents[1]


def _impact_data(selected_mpn: str = "IC-100"):
    analyses = [
        {"id": "bom-1", "project_name": "Gateway", "filename": "gateway.csv", "health_score": 72, "updated_at": "2026-10-01"},
        {"id": "bom-2", "project_name": "Sensor", "filename": "sensor.csv", "health_score": 88, "updated_at": "2026-10-02"},
        {"id": "bom-3", "project_name": "Gateway", "filename": "gateway.csv", "health_score": 65, "updated_at": "2026-10-03"},
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
            "quantity": 2,
        },
        {
            "analysis_id": "bom-3",
            "mpn": "IC-100",
            "manufacturer": "Acme",
            "risk_score": 50,
            "risk_level": "Medium",
            "lifecycle_status": "Active",
            "package": "QFN",
            "pin_count": 32,
            "supplier_count": 2,
            "stock_available": 95,
            "quantity": 4,
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


def test_catalog_aggregates_parts_across_saved_boms():
    result = _impact_data("IC-100")
    catalog_row = next(row for row in result["component_catalog"] if row["Part Number"] == "IC-100")

    assert result["selected_mpn"] == "IC-100"
    assert result["project_count"] == 2
    assert result["affected_bom_count"] == 3
    assert len(result["affected_projects"]) == 2
    assert catalog_row["Saved BOMs"] == 3
    assert catalog_row["Projects"] == 2
    assert {"Gateway", "Sensor"}.issubset(set(catalog_row["Project Names"]))

    gateway = next(row for row in result["affected_projects"] if row["Project"] == "Gateway")
    assert gateway["Saved BOMs"] == 2
    assert gateway["Quantity"] == 7


def test_component_list_is_limited_to_ten_rows(monkeypatch):
    fake_st = _FakeStreamlit(selected_rows=[], submit=False)
    monkeypatch.setattr(impact, "st", fake_st)
    monkeypatch.setattr(impact, "_css", lambda: None)
    monkeypatch.setattr(impact, "cadivor_section_header", lambda *args, **kwargs: None)

    from src import part_images

    monkeypatch.setattr(part_images, "part_image_source", lambda *args, **kwargs: "data:image/svg+xml,test")
    intelligence = _component_intelligence()
    catalog = intelligence["component_catalog"]
    for number in range(2, 12):
        catalog.append(
            {
                **catalog[0],
                "Part Number": f"PART-{number:02d}",
                "Search Text": f"part-{number:02d}",
            }
        )
    intelligence["available_mpns"] = [row["Part Number"] for row in catalog]

    impact.render_design_impact(
        intelligence=intelligence,
        internal_nav_button=lambda *args, **kwargs: None,
        review_started=False,
        impact_map_markup="<section>Impact map</section>",
    )

    assert len(fake_st.displayed_df) == 10
    assert "PART-11" not in set(fake_st.displayed_df["Part Number"])


class _Rerun(Exception):
    pass


class _FakeStreamlit:
    def __init__(self, *, selected_rows, submit: bool, query: str = ""):
        self.session_state = {}
        self.selected_rows = selected_rows
        self.submit = submit
        self.query = query
        self.button_label = ""
        self.messages = []
        self.displayed_df = None
        self.column_config = SimpleNamespace(
            ImageColumn=lambda *args, **kwargs: object(),
            TextColumn=lambda *args, **kwargs: object(),
            NumberColumn=lambda *args, **kwargs: object(),
        )

    def markdown(self, *args, **kwargs):
        return None

    def container(self, *args, **kwargs):
        return nullcontext()

    def text_input(self, *args, **kwargs):
        return self.query

    def dataframe(self, frame, **kwargs):
        self.displayed_df = frame
        return SimpleNamespace(selection=SimpleNamespace(rows=self.selected_rows))

    def columns(self, *args, **kwargs):
        return [nullcontext(), nullcontext()]

    def button(self, label, **kwargs):
        self.button_label = label
        return self.submit

    def caption(self, message):
        self.messages.append(message)

    def info(self, message):
        self.messages.append(message)

    def rerun(self):
        raise _Rerun


def _component_intelligence():
    return {
        "available_mpns": ["CAP-220", "IC-100"],
        "selected_mpn": "CAP-220",
        "component_catalog": [
            {
                "Part Number": "CAP-220",
                "Image URL": "",
                "Manufacturer": "Parts Co",
                "Saved BOMs": 1,
                "Projects": 1,
                "Project Names": ["Sensor"],
                "BOM Names": ["sensor.csv"],
                "Risk Score": 10,
                "Risk Level": "Low",
                "Lifecycle": "Active",
                "Description": "Capacitor",
                "Category": "Capacitor",
                "Search Text": "cap-220 parts co active sensor sensor.csv capacitor",
            },
            {
                "Part Number": "IC-100",
                "Image URL": "",
                "Manufacturer": "Acme",
                "Saved BOMs": 2,
                "Projects": 2,
                "Project Names": ["Gateway", "Sensor"],
                "BOM Names": ["gateway.csv", "sensor.csv"],
                "Risk Score": 62,
                "Risk Level": "Moderate",
                "Lifecycle": "Active",
                "Description": "Controller",
                "Category": "IC",
                "Search Text": "ic-100 acme active gateway sensor gateway.csv sensor.csv controller ic",
            },
        ],
    }


def test_search_filters_catalog_and_start_uses_selected_table_row(monkeypatch):
    fake_st = _FakeStreamlit(selected_rows=[1], submit=True, query="sensor")
    monkeypatch.setattr(impact, "st", fake_st)
    monkeypatch.setattr(impact, "_css", lambda: None)
    monkeypatch.setattr(impact, "cadivor_section_header", lambda *args, **kwargs: None)

    from src import part_images

    monkeypatch.setattr(part_images, "part_image_source", lambda *args, **kwargs: "data:image/svg+xml,test")

    with pytest.raises(_Rerun):
        impact.render_design_impact(
            intelligence=_component_intelligence(),
            internal_nav_button=lambda *args, **kwargs: None,
            review_started=False,
            impact_map_markup="<section>Impact map</section>",
        )

    assert list(fake_st.displayed_df["Part Number"]) == ["CAP-220", "IC-100"]
    assert fake_st.button_label == "Start impact review"
    assert fake_st.session_state["design_impact_pending_mpn"] == "IC-100"
    assert fake_st.session_state["design_impact_mpn"] == "IC-100"


def test_map_and_component_table_remain_visible_before_review(monkeypatch):
    fake_st = _FakeStreamlit(selected_rows=[], submit=False)
    monkeypatch.setattr(impact, "st", fake_st)
    monkeypatch.setattr(impact, "_css", lambda: None)
    monkeypatch.setattr(impact, "cadivor_section_header", lambda *args, **kwargs: None)

    from src import part_images

    monkeypatch.setattr(part_images, "part_image_source", lambda *args, **kwargs: "data:image/svg+xml,test")
    monkeypatch.setattr(
        impact,
        "render_kpi_row_safe",
        lambda *args, **kwargs: pytest.fail("detailed assessment should wait for review submission"),
    )

    impact.render_design_impact(
        intelligence=_component_intelligence(),
        internal_nav_button=lambda *args, **kwargs: None,
        review_started=False,
        impact_map_markup="<section>Impact map</section>",
    )

    assert fake_st.displayed_df is not None
    assert fake_st.button_label == "Start impact review"
    assert any("does not inspect PCB layouts" in message for message in fake_st.messages)


def test_runtime_restores_the_component_specific_map_for_the_selected_bom_rows():
    runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
    section = runtime.split('if app_mode == "Design Impact Analyzer":', 1)[1].split(
        "# ---------- Portfolio Intelligence ----------", 1
    )[0]

    assert "impact_map_html(" in section
    assert "impact_map_markup=impact_map_markup" in section
    assert "review_started=bool(" in section
    assert "render_simple_workspace(" not in section

    renderer = (ROOT / "src" / "design_impact_analyzer.py").read_text(encoding="utf-8")
    assert 'st.container(key="approved_home_page")' in renderer
    assert "max-width:1440px!important" in renderer
    assert "columns=4" in renderer
    assert "Estimated Review" not in renderer

"""Functional checks for the Design Impact selection and review workflow."""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

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


def test_missing_supply_fields_remain_unrecorded_instead_of_becoming_zero():
    result = impact.build_design_impact(
        [{"id": "bom-1", "project_name": "Gateway", "filename": "gateway.csv"}],
        [{"analysis_id": "bom-1", "mpn": "IC-100", "risk_score": 20}],
    )

    assert result["minimum_stock"] is None
    assert result["minimum_sources"] is None
    assert any("Inventory data" == item["Area"] for item in result["impact_categories"])
    assert any("Supplier data" == item["Area"] for item in result["impact_categories"])
    assert result["impact_score"] == 20


def test_recorded_zero_stock_and_sources_are_scored_as_real_values():
    result = impact.build_design_impact(
        [{"id": "bom-1", "project_name": "Gateway", "filename": "gateway.csv"}],
        [{"analysis_id": "bom-1", "mpn": "IC-100", "risk_score": 20, "stock_available": 0, "supplier_count": 0}],
    )

    assert result["minimum_stock"] == 0
    assert result["minimum_sources"] == 0
    assert result["impact_score"] == 55


def test_component_list_is_limited_to_ten_rows(monkeypatch):
    fake_st = _FakeStreamlit(submit=False)
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

    assert len(fake_st.row_button_keys) == 10
    rendered = "\n".join(str(event[1]) for event in fake_st.events if event[0] == "markdown")
    assert "PART-09" in rendered
    assert "PART-10" not in rendered
    assert "PART-11" not in rendered


class _Rerun(Exception):
    pass


class _FakeStreamlit:
    def __init__(self, *, submit: bool, query: str = "", submit_label: str = "Start impact review", clicked_key: str = "", filters=None):
        self.session_state = {}
        self.submit = submit
        self.submit_label = submit_label
        self.query = query
        self.clicked_key = clicked_key
        self.filters = filters or {}
        self.button_label = ""
        self.messages = []
        self.events = []
        self.row_button_keys = []
        self.selectbox_options = {}
        self.expander_calls = []

    def markdown(self, *args, **kwargs):
        self.events.append(("markdown", args[0] if args else ""))

    def container(self, *args, **kwargs):
        return nullcontext()

    def text_input(self, *args, **kwargs):
        return self.query

    def selectbox(self, label, options, **kwargs):
        key = kwargs.get("key", label)
        self.selectbox_options[key] = list(options)
        return self.filters.get(key, options[0])

    def dataframe(self, *args, **kwargs):
        self.events.append(("dataframe", kwargs.get("key", "")))

    def columns(self, *args, **kwargs):
        count = args[0] if args and isinstance(args[0], int) else len(args[0]) if args else 2
        return [nullcontext() for _ in range(count)]

    def expander(self, label, expanded=False):
        self.expander_calls.append((label, expanded))
        self.events.append(("expander", label))
        return nullcontext()

    def button(self, label, **kwargs):
        self.button_label = label
        key = kwargs.get("key", "")
        self.events.append(("button", label, key))
        if key.startswith("design_impact_select_row_"):
            self.row_button_keys.append(key)
        return (self.submit and label == self.submit_label) or bool(key and key == self.clicked_key)

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


def test_search_selects_a_component_before_starting_review(monkeypatch):
    fake_st = _FakeStreamlit(submit=False, query="sensor", clicked_key="design_impact_select_row_1")
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

    assert len(fake_st.row_button_keys) == 2
    assert "Start impact review" in [event[1] for event in fake_st.events if event[0] == "button"]
    assert fake_st.session_state["design_impact_pending_mpn"] == "IC-100"
    assert fake_st.session_state["design_impact_mpn"] == "IC-100"
    assert "design_impact_review_started_mpn" not in fake_st.session_state


def test_start_impact_review_sets_the_selected_part_and_explicit_state(monkeypatch):
    fake_st = _FakeStreamlit(submit=True, submit_label="Start impact review")
    monkeypatch.setattr(impact, "st", fake_st)
    monkeypatch.setattr(impact, "_css", lambda: None)
    monkeypatch.setattr(impact, "cadivor_section_header", lambda *args, **kwargs: None)

    from src import part_images

    monkeypatch.setattr(part_images, "part_image_markup", lambda *args, **kwargs: "<span>part</span>")
    monkeypatch.setattr(part_images, "part_image_source", lambda *args, **kwargs: "data:image/svg+xml,test")

    with pytest.raises(_Rerun):
        impact.render_design_impact(
            intelligence=_component_intelligence(),
            internal_nav_button=lambda *args, **kwargs: None,
            review_started=False,
            impact_map_markup="<section>Impact map</section>",
        )

    assert fake_st.session_state["design_impact_mpn"] == "CAP-220"
    assert fake_st.session_state["design_impact_review_started_mpn"] == "CAP-220"


def test_component_list_is_the_first_step_and_details_wait_for_review(monkeypatch):
    fake_st = _FakeStreamlit(submit=False)
    monkeypatch.setattr(impact, "st", fake_st)
    monkeypatch.setattr(impact, "_css", lambda: None)
    monkeypatch.setattr(impact, "cadivor_section_header", lambda *args, **kwargs: None)

    from src import part_images

    monkeypatch.setattr(part_images, "part_image_source", lambda *args, **kwargs: "data:image/svg+xml,test")
    monkeypatch.setattr(
        impact,
        "_design_impact_kpi_markup",
        lambda *args, **kwargs: pytest.fail("detailed assessment should wait for review submission"),
    )

    impact.render_design_impact(
        intelligence=_component_intelligence(),
        internal_nav_button=lambda *args, **kwargs: None,
        review_started=False,
        impact_map_markup="<section>Impact map</section>",
    )

    assert len(fake_st.row_button_keys) == 2
    assert "Start impact review" in [event[1] for event in fake_st.events if event[0] == "button"]
    markup = "\n".join(str(event[1]) for event in fake_st.events if event[0] == "markdown")
    assert "Components across saved BOMs" in markup
    assert "Choose a component" in markup
    assert "Record decision" in markup
    assert "Impact map" not in markup
    assert "cv20-selected-part" not in markup
    assert any("does not inspect PCB layouts" in message for message in fake_st.messages)
    assert "design_impact_select_row_0" in [event[2] for event in fake_st.events if event[0] == "button"]


def test_lifecycle_impact_and_project_filters_narrow_the_component_list(monkeypatch):
    fake_st = _FakeStreamlit(
        submit=False,
        filters={
            "design_impact_lifecycle_filter": "Active",
            "design_impact_risk_filter": "Low",
            "design_impact_project_filter": "Sensor",
        },
    )
    monkeypatch.setattr(impact, "st", fake_st)
    monkeypatch.setattr(impact, "_css", lambda: None)
    monkeypatch.setattr(impact, "cadivor_section_header", lambda *args, **kwargs: None)

    from src import part_images

    monkeypatch.setattr(part_images, "part_image_source", lambda *args, **kwargs: "data:image/svg+xml,test")

    impact.render_design_impact(
        intelligence=_component_intelligence(),
        internal_nav_button=lambda *args, **kwargs: None,
        review_started=False,
    )

    assert fake_st.row_button_keys == ["design_impact_select_row_0"]
    assert fake_st.selectbox_options["design_impact_lifecycle_filter"][0] == "All lifecycle"
    assert fake_st.selectbox_options["design_impact_risk_filter"][0] == "All impact levels"
    assert fake_st.selectbox_options["design_impact_project_filter"][0] == "All projects"


def test_initial_design_impact_has_no_implicit_component_selection():
    result = impact.build_design_impact(
        [{"id": "bom-1", "project_name": "Gateway", "filename": "gateway.csv"}],
        [{"analysis_id": "bom-1", "mpn": "IC-100", "risk_score": 72}],
        select_recommended_when_empty=False,
    )

    assert result["selected_mpn"] == ""
    assert result["available_mpns"] == ["IC-100"]
    assert result["component_catalog"][0]["Part Number"] == "IC-100"


def test_component_evidence_carries_document_and_lead_time_fields():
    result = impact.build_design_impact(
        [{"id": "bom-1", "project_name": "Gateway", "filename": "gateway.csv"}],
        [{
            "analysis_id": "bom-1", "mpn": "IC-100", "risk_score": 72,
            "device_type": "MCU", "design_phase": "Production", "lead_time_weeks": 18,
            "datasheet_url": "https://vendor.example/ds.pdf",
            "source_url": "https://vendor.example/item/IC-100",
        }],
        "IC-100",
    )

    assert result["device_subtype"] == "MCU"
    assert result["design_phase"] == "Production"
    assert result["maximum_lead_time_weeks"] == 18
    assert result["risk_level"] == "High"
    assert result["datasheet_url"] == "https://vendor.example/ds.pdf"
    assert result["source_url"] == "https://vendor.example/item/IC-100"


def test_review_details_are_collapsed_and_validation_scope_is_clear(monkeypatch):
    fake_st = _FakeStreamlit(submit=False)
    navigation_calls = []
    monkeypatch.setattr(impact, "st", fake_st)
    monkeypatch.setattr(impact, "_css", lambda: None)
    monkeypatch.setattr(impact, "cadivor_section_header", lambda *args, **kwargs: None)

    from src import part_images

    monkeypatch.setattr(part_images, "part_image_markup", lambda *args, **kwargs: "<span>part</span>")
    monkeypatch.setattr(part_images, "part_image_source", lambda *args, **kwargs: "data:image/svg+xml,test")

    impact.render_design_impact(
        intelligence=_impact_data("IC-100"),
        internal_nav_button=lambda *args, **kwargs: navigation_calls.append((args, kwargs)),
        review_started=True,
        impact_map_markup="<section>Impact map</section>",
    )

    assert ("Recommendations and score details", False) in fake_st.expander_calls
    page_markup = "\n".join(
        str(event[1]) for event in fake_st.events if event[0] == "markdown"
    )
    assert "Confirm electrical function, package, footprint, pinout, and design constraints" in " ".join(fake_st.messages) + page_markup
    assert "Price trend" in page_markup
    assert "Alternatives" in page_markup
    assert "cv20-selected-part__facts" in page_markup
    assert "cv20-kpi-grid" in page_markup
    assert "cv20-project-table" in page_markup
    assert "Gateway" in page_markup and "Sensor" in page_markup
    assert "Package dimensions: Not recorded" in page_markup
    assert any(args[0] == "Open replacement comparison" for args, _ in navigation_calls)


def test_design_impact_detail_sections_stay_under_their_related_columns():
    source = (ROOT / "src" / "design_impact_analyzer.py").read_text(encoding="utf-8")
    render = source.split("left, right = st.columns([1.3, 1]", 1)[1].split(
        "st.markdown(\"</div>\"", 1
    )[0]

    left_block = render.split("with left:", 1)[1].split("with right:", 1)[0]
    right_block = render.split("with right:", 1)[1]
    assert left_block.index('with st.expander("Recommendations and score details"') >= 0
    assert left_block.index('with st.expander("Continue the engineering workflow"') >= 0
    assert 'with st.expander("Open an affected BOM"' in right_block
    assert ".cv20-map-card{height:auto;min-height:0" in source
    assert ".cv20-factors-card{height:auto;min-height:0" in source
    assert ".cv20-project-card{height:auto;min-height:0" in source


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
    assert "review_started=bool(" in section
    assert "design_impact_review_started_mpn" in section
    assert "columns=5" in renderer
    assert "Estimated review" in renderer
    assert "select_recommended_when_empty=False" in section


def test_authenticated_route_canvases_share_one_top_start_line():
    source = (ROOT / "src" / "ui" / "core_premium_ui.py").read_text(encoding="utf-8")
    rule = source.split('id="cadivor-route-start-alignment"', 1)[1].split("</style>", 1)[0]

    assert "st-key-approved_page_canvas_standard_" in rule
    assert "st-key-approved_page_canvas_wide_" in rule
    assert "st-key-cadivor_decision_packet_shell" in rule
    assert "padding-top: 0 !important" in rule

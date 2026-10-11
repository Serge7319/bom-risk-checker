"""Interactions for portfolio KPI drilldowns and risk disclosures."""
from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace


from src import portfolio_intelligence
from src.ui import approved_pages


def test_portfolio_kpis_expose_the_records_behind_each_count():
    analyses = [
        {
            "id": "bom-gateway",
            "project_name": "Gateway",
            "filename": "gateway.csv",
            "health_score": 71,
            "high_risk_count": 1,
            "total_parts": 2,
            "created_at": "2026-10-10",
        },
        {
            "id": "bom-sensor",
            "project_name": "Sensor",
            "filename": "sensor.csv",
            "health_score": 88,
            "high_risk_count": 1,
            "total_parts": 1,
            "created_at": "2026-10-11",
        },
    ]
    parts = [
        {
            "analysis_id": "bom-gateway",
            "mpn": "SHARED-1",
            "manufacturer": "Acme",
            "risk_score": 82,
            "risk_level": "High",
            "supplier_count": 1,
            "stock_available": 0,
            "quantity": 4,
            "lifecycle_status": "Active",
        },
        {
            "analysis_id": "bom-gateway",
            "mpn": "CAP-10",
            "manufacturer": "Parts Co",
            "risk_score": 15,
            "risk_level": "Low",
            "stock_available": 500,
            "lifecycle_status": "Active",
        },
        {
            "analysis_id": "bom-sensor",
            "mpn": "SHARED-1",
            "manufacturer": "Acme",
            "risk_score": 65,
            "risk_level": "Medium",
            "supplier_count": 3,
            "stock_available": 20,
            "quantity": 2,
            "lifecycle_status": "Active",
        },
    ]

    result = portfolio_intelligence.build_portfolio_intelligence(analyses, parts, [])
    details = result["kpi_details"]

    assert len(details["Saved Projects"]["rows"]) == 2
    assert len(details["Component Records"]["rows"]) == 3
    assert details["Shared Components"]["rows"][0]["Part Number"] == "SHARED-1"
    assert len(details["Single-Source Records"]["rows"]) == 1
    assert len(details["High-risk component records"]["rows"]) == 2
    assert [
        row["Part Number"] for row in result["high_risk_by_analysis"]["bom-gateway"]
    ] == ["SHARED-1"]
    assert [
        row["Part Number"] for row in result["high_risk_by_analysis"]["bom-sensor"]
    ] == ["SHARED-1"]
    assert result["supplier_data_recorded"] is True


def test_at_risk_count_opens_an_escaped_component_list():
    markup = portfolio_intelligence.high_risk_components_disclosure(
        1,
        [
            {
                "Part Number": "<U1>",
                "Manufacturer": "Acme",
                "Risk Level": "High",
                "Risk Score": 82,
                "Quantity": 4,
            }
        ],
    )

    assert "<details" in markup
    assert "View components" in markup
    assert "&lt;U1&gt;" in markup
    assert "<U1>" not in markup
    assert "Qty 4" in markup


class _FakeStreamlit:
    def __init__(self, clicked_key: str):
        self.clicked_key = clicked_key
        self.session_state = {}
        self.button_keys = []
        self.displayed_df = None

    def markdown(self, *args, **kwargs):
        return None

    def container(self, *args, **kwargs):
        return nullcontext()

    def columns(self, *args, **kwargs):
        spec = args[0] if args else 2
        count = spec if isinstance(spec, int) else len(spec)
        return [nullcontext() for _ in range(count)]

    def button(self, label, *, key=None, **kwargs):
        self.button_keys.append(key)
        return key == self.clicked_key

    def dataframe(self, frame, **kwargs):
        self.displayed_df = frame

    def info(self, *args, **kwargs):
        return None

    def caption(self, *args, **kwargs):
        return None


def test_clicking_a_portfolio_kpi_shows_its_detail_table(monkeypatch):
    fake_st = _FakeStreamlit("approved_simple_workspace_kpi_4")
    monkeypatch.setattr(approved_pages, "st", fake_st)
    monkeypatch.setattr(approved_pages, "begin_approved_page", lambda: None)
    monkeypatch.setattr(approved_pages, "end_approved_page", lambda: None)

    details = {
        "High-risk component records": {
            "description": "Parts needing review.",
            "headers": ["Project", "Part Number", "Risk Score"],
            "rows": [{"Project": "Gateway", "Part Number": "U1", "Risk Score": 82}],
        }
    }
    approved_pages.render_simple_workspace(
        kicker="PORTFOLIO",
        title="Portfolio intelligence",
        subtitle="Portfolio summary.",
        kpis=[
            ("Saved Projects", "2"),
            ("Component Records", "3"),
            ("Shared Components", "1"),
            ("Single-Source Records", "1"),
            ("High-risk component records", "2"),
        ],
        headers=["Project"],
        table_rows=[["Gateway"]],
        kpi_details=details,
    )

    assert len(fake_st.button_keys) == 5
    assert fake_st.session_state["approved_workspace_kpi_detail_selection"] == "High-risk component records"
    assert list(fake_st.displayed_df["Part Number"]) == ["U1"]

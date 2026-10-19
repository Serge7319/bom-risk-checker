"""Dynamic dashboard models must preserve unknowns and use recorded evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.portfolio_intelligence import (
    build_portfolio_intelligence,
    filter_portfolio_window,
    filter_previous_portfolio_window,
    _shared_component_evidence_labels,
)
from src.supply_risk_scenario import build_supply_scenario


def test_supply_scenario_does_not_treat_missing_stock_or_sources_as_zero():
    result = build_supply_scenario(
        [{"id": "analysis-1", "project_name": "Controller BOM"}],
        [{"analysis_id": "analysis-1", "mpn": "U1", "quantity": 2}],
        build_quantity=10,
        supplier_loss=1,
    )

    row = result["rows"][0]
    assert row["Stock Recorded"] is False
    assert row["Sources Recorded"] is False
    assert row["Original Stock"] is None
    assert row["Scenario Sources"] is None
    assert row["Shortage Units"] is None
    assert row["Estimated Shortage Value"] is None
    assert result["exposed_components"] == 0
    assert result["shortage_components"] == 0
    assert result["single_source_components"] == 0


def test_supply_scenario_treats_unknown_text_fields_as_unrecorded_not_zero():
    result = build_supply_scenario(
        [{"id": "analysis-1"}],
        [{
            "analysis_id": "analysis-1",
            "mpn": "U-UNKNOWN",
            "stock_available": "Unknown",
            "supplier_count": "N/A",
            "unit_price": "—",
            "risk_score": "not recorded",
        }],
    )

    row = result["rows"][0]
    assert row["Stock Recorded"] is False
    assert row["Sources Recorded"] is False
    assert row["Price Recorded"] is False
    assert row["Risk Score Recorded"] is False
    assert row["Original Stock"] is None
    assert row["Scenario Sources"] is None
    assert row["Estimated Shortage Value"] is None


def test_supply_scenario_uses_recorded_stock_and_lead_time_delta():
    result = build_supply_scenario(
        [{"id": "analysis-1", "project_name": "Controller BOM"}],
        [{
            "analysis_id": "analysis-1",
            "mpn": "U2",
            "quantity": 2,
            "stock_available": 10,
            "supplier_count": 2,
            "lead_time_increase_weeks": 3,
        }],
        build_quantity=10,
        supplier_loss=1,
    )

    assert result["rows"][0]["Scenario Stock"] == 5
    assert result["rows"][0]["Shortage Units"] == 15
    assert result["projected_stock_gap"] == 15
    assert result["lead_time_increase_weeks"] == 3
    assert result["lead_time_evidence_count"] == 1


def test_supply_chart_demand_total_uses_only_rows_with_stock_evidence():
    result = build_supply_scenario(
        [{"id": "analysis-1", "project_name": "Controller BOM"}],
        [
            {"analysis_id": "analysis-1", "mpn": "KNOWN", "quantity": 2, "stock_available": 100},
            {"analysis_id": "analysis-1", "mpn": "UNKNOWN", "quantity": 4},
        ],
        build_quantity=5,
    )

    assert result["required_units_total"] == 30
    assert result["required_units_known_stock_total"] == 10
    assert result["unknown_stock_components"] == 1
    assert result["known_stock_components"] == 1


def test_supply_scenario_counts_a_shared_supplier_stock_pool_once():
    result = build_supply_scenario(
        [
            {"id": "analysis-1", "project_name": "Controller"},
            {"id": "analysis-2", "project_name": "Sensor"},
        ],
        [
            {"analysis_id": "analysis-1", "mpn": "SHARED-1", "quantity": 60, "stock_available": 100},
            {"analysis_id": "analysis-2", "mpn": "SHARED-1", "quantity": 60, "stock_available": 100},
        ],
        build_quantity=1,
    )

    assert result["component_count"] == 1
    assert result["required_units_total"] == 120
    assert result["recorded_stock_total"] == 100
    assert result["projected_stock_gap"] == 20
    assert result["affected_projects"] == 2


def test_supply_scenario_does_not_merge_rows_without_a_part_number():
    result = build_supply_scenario(
        [
            {"id": "analysis-1", "project_name": "Controller"},
            {"id": "analysis-2", "project_name": "Sensor"},
        ],
        [
            {"analysis_id": "analysis-1", "quantity": 2, "stock_available": 10},
            {"analysis_id": "analysis-2", "quantity": 3, "stock_available": 12},
        ],
    )

    assert result["component_count"] == 2
    assert result["recorded_stock_total"] == 22


def test_portfolio_risk_distribution_keeps_unassessed_parts_unassessed():
    result = build_portfolio_intelligence(
        [{
            "id": "analysis-1",
            "project_name": "Controller BOM",
            "filename": "controller.csv",
            "created_at": "2026-10-01T12:00:00Z",
            "total_parts": 2,
        }],
        [
            {"analysis_id": "analysis-1", "mpn": "U1", "risk_level": "Unknown"},
            {
                "analysis_id": "analysis-1",
                "mpn": "U2",
                "risk_level": "High",
                "risk_score": 72,
                "supplier_count": 1,
                "stock_available": 0,
            },
        ],
        [],
    )

    assert result["risk_distribution"] == {
        "High risk": 1,
        "Medium risk": 0,
        "Low risk": 0,
        "Unassessed": 1,
    }
    assert result["single_source_count"] == 1
    assert len(result["no_stock"]) == 1
    assert result["at_risk_boms"][0]["At-Risk Components"] == 1


def test_portfolio_shared_components_keep_missing_risk_scores_unassessed():
    result = build_portfolio_intelligence(
        [
            {"id": "analysis-1", "project_name": "Controller"},
            {"id": "analysis-2", "project_name": "Gateway"},
        ],
        [
            {"analysis_id": "analysis-1", "mpn": "SHARED-UNKNOWN"},
            {"analysis_id": "analysis-2", "mpn": "SHARED-UNKNOWN"},
            {"analysis_id": "analysis-1", "mpn": "SHARED-SCORED", "risk_score": 72},
            {"analysis_id": "analysis-2", "mpn": "SHARED-SCORED", "risk_score": 72},
        ],
        [],
    )

    shared = {row["Part Number"]: row for row in result["shared_components"]}
    assert shared["SHARED-UNKNOWN"]["Highest Risk Score"] is None
    assert shared["SHARED-SCORED"]["Highest Risk Score"] == 72
    assert [row["Part Number"] for row in result["shared_components"]] == [
        "SHARED-SCORED",
        "SHARED-UNKNOWN",
    ]
    assert _shared_component_evidence_labels(shared["SHARED-UNKNOWN"]) == (
        "Risk not assessed",
        "Stock not recorded",
        "Supplier sources not recorded",
    )


def test_portfolio_distribution_reconciles_summary_counts_to_saved_bom_total():
    result = build_portfolio_intelligence(
        [{
            "id": "analysis-summary-only",
            "project_name": "Legacy BOM",
            "total_parts": 8,
            "high_risk_count": 2,
            "medium_risk_count": 1,
            "low_risk_count": 3,
        }],
        [],
        [],
    )

    assert result["risk_distribution"] == {
        "High risk": 2,
        "Medium risk": 1,
        "Low risk": 3,
        "Unassessed": 2,
    }


def test_portfolio_does_not_report_missing_part_numbers_as_shared_parts():
    result = build_portfolio_intelligence(
        [
            {"id": "analysis-1", "project_name": "Controller"},
            {"id": "analysis-2", "project_name": "Sensor"},
        ],
        [
            {"analysis_id": "analysis-1", "risk_level": "Unknown"},
            {"analysis_id": "analysis-2", "risk_level": "Unknown"},
        ],
        [],
    )

    assert result["shared_components"] == []


def test_portfolio_time_filter_uses_saved_analysis_dates_and_keeps_matching_parts():
    analyses = [
        {"id": "recent", "created_at": "2026-10-01T00:00:00Z"},
        {"id": "old", "created_at": "2025-01-01T00:00:00Z"},
        {"id": "undated"},
    ]
    parts = [
        {"analysis_id": "recent", "mpn": "A"},
        {"analysis_id": "old", "mpn": "B"},
        {"analysis_id": "undated", "mpn": "C"},
    ]

    selected_analyses, selected_parts, _, note = filter_portfolio_window(
        analyses,
        parts,
        [],
        "Last 30 days",
        now=datetime(2026, 10, 18, tzinfo=timezone.utc),
    )

    assert [row["id"] for row in selected_analyses] == ["recent"]
    assert [row["mpn"] for row in selected_parts] == ["A"]
    assert "undated BOM(s) are excluded" in note


def test_portfolio_previous_window_uses_the_immediately_preceding_period():
    analyses = [
        {"id": "current", "created_at": "2026-10-01T00:00:00Z"},
        {"id": "previous", "created_at": "2026-09-01T00:00:00Z"},
        {"id": "too-old", "created_at": "2026-08-01T00:00:00Z"},
    ]
    parts = [
        {"analysis_id": "current", "mpn": "A"},
        {"analysis_id": "previous", "mpn": "B"},
        {"analysis_id": "too-old", "mpn": "C"},
    ]

    previous_analyses, previous_parts, _, note = filter_previous_portfolio_window(
        analyses,
        parts,
        [],
        "Last 30 days",
        now=datetime(2026, 10, 18, tzinfo=timezone.utc),
    )

    assert [row["id"] for row in previous_analyses] == ["previous"]
    assert [row["mpn"] for row in previous_parts] == ["B"]
    assert "Prior window" in note


def test_portfolio_load_uses_thin_fields_and_filters_the_selected_period():
    source = (Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py").read_text()
    block = source.split('if app_mode == "Portfolio Intelligence":', 1)[1].split(
        '# ---------- Procurement Advisor ----------', 1
    )[0]

    assert '.select("*")' not in block
    assert 'select("part_number,mpn,created_at")' in block
    assert 'query.in_("analysis_id", relevant_analysis_ids)' in block
    assert '"supplier_offers"' not in block

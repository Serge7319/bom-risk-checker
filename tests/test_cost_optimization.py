from pathlib import Path

from src.cost_optimization import _opportunity_table_markup, build_cost_optimization


def test_cost_opportunity_table_uses_saved_prices_and_component_illustrations():
    intelligence = build_cost_optimization(
        [{"id": "analysis-1", "project_name": "Motor controller"}],
        [
            {
                "analysis_id": "analysis-1",
                "mpn": "CAP-100",
                "description": "Ceramic capacitor",
                "manufacturer": "Acme",
                "quantity": 10,
                "unit_price": 1.25,
                "supplier_count": 2,
                "stock_available": 100,
                "risk_score": 20,
            }
        ],
        build_quantity=100,
    )

    assert intelligence["production_run_cost"] == 1250
    assert intelligence["estimated_savings"] == 62.5
    assert intelligence["opportunities"][0]["Description"] == "Ceramic capacitor"

    markup = _opportunity_table_markup(intelligence["opportunities"])

    assert 'data-illustration="capacitor"' in markup
    assert "Ceramic capacitor" in markup
    assert "CAP-100" in markup
    assert "$1.2500" in markup
    assert "$62.50" in markup
    assert "Optimization path" in markup


def test_cost_optimization_route_uses_the_data_driven_workspace():
    source = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")
    route = source.split("# ---------- Cost Optimization ----------", 1)[1].split(
        "# ---------- Design Impact Analyzer ----------", 1
    )[0]

    assert "render_simple_workspace" not in route
    assert "render_cost_optimization(" in route
    assert "control=_cost_build_control" in route

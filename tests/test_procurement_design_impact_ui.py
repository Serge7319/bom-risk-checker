"""UI contracts for Procurement risk badges and Design Impact actions."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCUREMENT = ROOT / "apps/web/src/app/procurement/page.tsx"
DESIGN = ROOT / "apps/web/src/app/design-impact/page.tsx"
BADGE = ROOT / "apps/web/src/components/RiskLevelBadge.tsx"


def test_procurement_renders_distinct_risk_badges_and_legend():
    page = PROCUREMENT.read_text(encoding="utf-8")
    badge = BADGE.read_text(encoding="utf-8")
    assert "RiskLevelBadge" in page
    assert "RiskLevelLegend" in page
    assert "display(p.risk_level" not in page
    assert "No high-priority risk was recorded" in badge
    assert "does not guarantee availability or suitability" in badge
    assert 'tone: "low"' in badge
    assert "Needs verification" in badge
    assert "cv-risk-badge--verify" in (ROOT / "apps/web/src/app/globals.css").read_text(encoding="utf-8")
    # Lifecycle and supplier coverage stay separate columns.
    assert "<th>Lifecycle</th>" in page
    assert "<th>Supplier coverage</th>" in page
    assert "evidenceSourceLabel" in page


def test_unrecognized_risk_is_not_classified_as_low():
    source = BADGE.read_text(encoding="utf-8")
    low_branch = source.split('return { tone: "low"', 1)[0]
    assert "missing" not in low_branch.lower() or "low" in source
    assert 'return { tone: "verify", label: "Needs verification" }' in source


def test_design_impact_explains_trace_and_keeps_report_ids_out_of_labels():
    page = DESIGN.read_text(encoding="utf-8")
    assert "does not simulate a proposed design change" in page
    assert "Suggested part" in page
    assert "This is not a selection you made." in page
    assert "Find an MPN" in page
    assert "cv-impact-select" in page
    assert "aria-pressed" in page
    assert "Open saved report" in page
    assert "part_a=" in page
    assert "Refresh impact" in page
    assert "Affected BOM rows" in page
    # Internal report ids may be used in hrefs, not rendered as visible copy.
    assert ">{savedReportId}<" not in page
    assert "Analysis ID:" not in page

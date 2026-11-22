from __future__ import annotations

from apps.api import migration_tools
from src.portfolio_intelligence import build_portfolio_intelligence


def test_shared_portfolio_signals_drop_legacy_scores_without_current_evidence(monkeypatch):
    analyses = [
        {"id": "analysis-1", "project_name": "Project One", "filename": "one.csv"},
        {"id": "analysis-2", "project_name": "Project Two", "filename": "two.csv"},
    ]
    reports = {
        analysis["id"]: {
            "id": analysis["id"],
            "filename": analysis["filename"],
            "mode": "live",
            "parts": [
                {
                    "mpn": "MPU-6050",
                    "manufacturer": "TDK InvenSense",
                    "Lifecycle": "Obsolete",
                    "risk_score": 80,
                    "risk_level": "High",
                    "evidence_source": "missing",
                    "identity_source": "missing",
                }
            ],
        }
        for analysis in analyses
    }
    monkeypatch.setattr(
        migration_tools,
        "get_report",
        lambda analysis_id, *, workspace_id: reports.get(analysis_id),
    )

    current_parts = migration_tools._portfolio_parts_with_current_evidence(
        analyses, workspace_id="workspace-1"
    )
    result = build_portfolio_intelligence(analyses, current_parts, [])
    shared = result["shared_components"][0]

    assert shared["Highest Risk Score"] is None
    assert shared["Lifecycle"] == "Needs verification"
    assert shared["Reported Lifecycle"] == "Obsolete"
    assert shared["Lifecycle Evidence"] == "unverified"

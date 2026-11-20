"""Customer-facing visibility rules for clearly marked internal QA analyses."""
from __future__ import annotations

from typing import Any


def is_internal_test_fixture_analysis(row: dict[str, Any]) -> bool:
    """Identify fixtures only through explicit server-side metadata.

    Project names, BOM names, revisions, and uploaded filenames are user data.
    They can contain words such as "test", "QA", or "synthetic" without being
    internal fixtures, so visibility must never be inferred from those values.
    Evidence mode is also not a fixture marker: valid customer analyses may
    legitimately use preview or synthetic evidence.
    """
    return row.get("internal_test_fixture") is True or row.get("is_test_fixture") is True


def customer_visible_analyses(
    rows: list[dict[str, Any]], *, production: bool
) -> list[dict[str, Any]]:
    """Hide clearly named internal fixtures from production customer lists."""
    if not production:
        return rows
    return [row for row in rows if not is_internal_test_fixture_analysis(row)]


def customer_visible_projects(
    projects: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
    *,
    production: bool,
) -> list[dict[str, Any]]:
    """Filter internal fixtures from saved-project summaries in production."""
    if not production:
        return projects

    visible_analyses = customer_visible_analyses(analyses, production=True)
    visible_ids = {str(row.get("id") or row.get("analysis_id") or "") for row in visible_analyses}
    visible_by_id = {
        str(row.get("id") or row.get("analysis_id") or ""): row
        for row in visible_analyses
        if row.get("id") or row.get("analysis_id")
    }
    visible_by_bom: dict[str, dict[str, Any]] = {}
    for report in visible_analyses:
        bom_id = str(report.get("bom_id") or "").strip()
        if bom_id and bom_id not in visible_by_bom:
            visible_by_bom[bom_id] = report

    result: list[dict[str, Any]] = []
    for project in projects:
        if is_internal_test_fixture_analysis(project):
            continue

        boms = project.get("boms")
        if not isinstance(boms, list):
            result.append(project)
            continue

        visible_boms: list[dict[str, Any]] = []
        for bom in boms:
            if not isinstance(bom, dict):
                continue
            if is_internal_test_fixture_analysis(bom):
                continue

            bom_id = str(bom.get("id") or bom.get("bom_id") or "").strip()
            analysis_id = str(bom.get("latest_analysis_id") or "").strip()
            report = visible_by_id.get(analysis_id) if analysis_id else None
            if not report and bom_id:
                report = visible_by_bom.get(bom_id)
            if analysis_id and analysis_id not in visible_ids and not report:
                continue

            if report and analysis_id != str(report.get("id") or report.get("analysis_id") or ""):
                bom = {
                    **bom,
                    "latest_analysis_id": str(report.get("id") or report.get("analysis_id") or ""),
                    "latest_analysis": report,
                    "health_score": report.get("health_score"),
                    "high_risk_count": report.get("high_risk_count"),
                    "has_hierarchy": report.get("has_hierarchy"),
                    "top_rolled_risk": report.get("top_rolled_risk"),
                }
            visible_boms.append(bom)

        # Projects without a saved customer-visible BOM are empty shells, not
        # active portfolio projects. This also keeps a project row from
        # lingering after its last BOM has been deleted.
        if not visible_boms:
            continue
        result.append({**project, "boms": visible_boms, "bom_count": len(visible_boms)})

    return result

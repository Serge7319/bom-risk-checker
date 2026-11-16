"""Customer-facing visibility rules for clearly marked internal QA analyses."""
from __future__ import annotations

import re
from typing import Any


_INTERNAL_MARKER = re.compile(
    r"(?<![a-z0-9])(?:synthetic|preview|fixture|e2e|qa)(?![a-z0-9])", re.I
)
_TEST_BOM_MARKER = re.compile(r"(?<![a-z0-9])test[\s_-]*bom(?:[\s_-]*\d+)?(?![a-z0-9])", re.I)
_SMOKE_MARKER = re.compile(
    r"(?<![a-z0-9])(?:smoke[\s_-]+(?:test|nested|flat)|(?:nested|flat)[\s_-]+smoke)(?![a-z0-9])",
    re.I,
)
_DEMO_FIXTURE_MARKER = re.compile(
    r"(?<![a-z0-9])demo[\s_-]+(?:controller(?:[\s_-]+bom)?|product[\s_-]+line)(?![a-z0-9])",
    re.I,
)


def is_internal_test_fixture_analysis(row: dict[str, Any]) -> bool:
    """Identify explicitly named demo/QA analyses without relying on evidence mode.

    Supplier evidence can be synthetic on a legitimate customer BOM, so mode
    and evidence labels are deliberately not used to hide the analysis.
    """
    if row.get("internal_test_fixture") is True or row.get("is_test_fixture") is True:
        return True

    values = [
        str(row.get(key) or "").strip()
        for key in ("project_name", "bom_name", "filename", "revision")
    ]
    searchable = " ".join(value for value in values if value)
    if not searchable:
        return False

    if _INTERNAL_MARKER.search(searchable):
        return True
    if _TEST_BOM_MARKER.search(searchable) or _SMOKE_MARKER.search(searchable):
        return True
    return bool(_DEMO_FIXTURE_MARKER.search(searchable))


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
        project_name = str(project.get("name") or project.get("project_name") or "")
        if is_internal_test_fixture_analysis({"project_name": project_name}):
            continue

        boms = project.get("boms")
        if not isinstance(boms, list):
            result.append(project)
            continue

        visible_boms: list[dict[str, Any]] = []
        for bom in boms:
            if not isinstance(bom, dict):
                continue
            bom_name = str(bom.get("name") or bom.get("bom_name") or "")
            if is_internal_test_fixture_analysis(
                {
                    "project_name": project_name,
                    "bom_name": bom_name,
                    "filename": bom.get("filename"),
                    "revision": bom.get("revision"),
                }
            ):
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

        if boms and not visible_boms:
            continue
        result.append({**project, "boms": visible_boms, "bom_count": len(visible_boms)})

    return result

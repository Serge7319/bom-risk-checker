"""Headless synthetic BOM analyze using production parse/risk/health modules.

Supplier HTTP, Stripe, email are not used. Analyses persist via the migration
workspace store (Postgres when CADIVOR_MIGRATION_DATABASE_URL is set; otherwise
ephemeral file for local/tests only). Part enrichment is deterministic
synthetic evidence so health scoring can complete offline.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from apps.api.bom_hierarchy import (
    attach_hierarchy_fields,
    has_hierarchy,
    rollup_assemblies,
)
from apps.api.json_safe import json_safe
from apps.api.workspace_store import PersistenceNotConfiguredError, get_store
from src.bom_intake import BomIntakeError, IntakeResult, parse_intake
from src.health_score import calculate_bom_health_score
from src.risk_engine import calculate_risk

# Process-local mirror kept for backward compatibility with in-flight callers.
_REPORTS: dict[str, dict[str, Any]] = {}


class PersistenceVerifyError(RuntimeError):
    """Raised when an analysis write cannot be read back from the workspace store."""


def _synthetic_part(mpn: str, manufacturer: str, description: str, quantity: Any) -> dict[str, Any]:
    """Build verified-looking part evidence without calling distributors."""
    digest = int(hashlib.sha256(str(mpn).encode("utf-8")).hexdigest()[:8], 16)
    stock = 50 + (digest % 450)
    lifecycle = "Active" if digest % 7 else "NRND"
    return {
        "mpn": mpn,
        "manufacturer": manufacturer,
        "description": description,
        "quantity": quantity,
        "lifecycle_status": lifecycle,
        "stock_total": stock,
        "stock_available": stock,
        "total_market_stock": stock,
        "stock_data_complete": True,
        "supplier_data_verified": True,
        "unit_price": round(0.15 + (digest % 100) / 100.0, 3),
        "source": "synthetic-preview",
    }


def parse_bom_intake(
    filename: str,
    payload: bytes,
    *,
    column_mapping: dict[str, str] | None = None,
    supplier_specific: bool = False,
    default_supplier: str = "",
    exclude_invalid_rows: bool = False,
    row_corrections: dict[str, dict[str, str]] | None = None,
) -> IntakeResult:
    """Read, map, and normalize a BOM without analyzing it."""
    return parse_intake(
        filename,
        payload,
        column_mapping=column_mapping,
        supplier_specific=supplier_specific,
        default_supplier=default_supplier,
        exclude_invalid_rows=exclude_invalid_rows,
        row_corrections=row_corrections,
    )


def _require_analyzable(result: IntakeResult) -> None:
    if result.can_analyze:
        return
    preview = result.preview()
    message = (preview.get("errors") or ["The BOM could not be analyzed."])[0]
    raise BomIntakeError(message, preview=preview, code="bom_validation_failed")


def parse_bom_bytes(filename: str, payload: bytes, **intake_options: Any) -> pd.DataFrame:
    """Parse a BOM into the analysis frame, refusing files with unresolved errors."""
    result = parse_bom_intake(filename, payload, **intake_options)
    _require_analyzable(result)
    return result.dataframe()


def assess_saved_report(report: dict[str, Any] | None) -> dict[str, Any]:
    """Derive customer-facing summary fields from row-level saved evidence.

    Persisted risk/health labels are snapshots from the analysis run. They can
    outlive supplier evidence or older scoring rules, so report reads recompute
    these summary fields using the same strict evidence contract as a health
    recalculation. This never contacts a supplier and never writes to storage.
    """
    parts = [
        row for row in ((report or {}).get("parts") or [])
        if isinstance(row, dict)
    ]
    assessments = [calculate_risk(part) for part in parts]
    health = calculate_bom_health_score(pd.DataFrame(parts))
    needs_verification = sum(
        not bool(item.get("evidence_coverage_complete")) for item in assessments
    )
    return {
        "health_score": health.get("health_score"),
        "health_status": health.get("health_status") or "Not scored",
        "summary_message": health.get("summary_message")
        or "Health could not be calculated from saved evidence.",
        "assessment_coverage": health.get("assessment_coverage"),
        "needs_verification_count": needs_verification,
        "high_risk_count": sum(item.get("risk_level") == "High" for item in assessments),
        "medium_risk_count": sum(item.get("risk_level") == "Medium" for item in assessments),
        "low_risk_count": sum(item.get("risk_level") == "Low" for item in assessments),
        "total_parts": len(parts),
        "health_source": "saved-evidence",
    }


def _report_with_current_assessment(report: dict[str, Any]) -> dict[str, Any]:
    """Return a report whose summary cannot inherit stale stored score labels."""
    return {**report, **assess_saved_report(report)}


def current_priority_items(
    report: dict[str, Any], analysis: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Build home-page review items from current row evidence, never saved labels."""
    from apps.api.evidence_contract import classify_part_evidence

    context = analysis or report or {}
    items: list[dict[str, Any]] = []
    rank = {"High": 0, "Medium": 1, "Needs verification": 2}
    for part in (report.get("parts") or []):
        if not isinstance(part, dict):
            continue
        assessment = calculate_risk(part)
        level = str(assessment.get("risk_level") or "Needs verification")
        if level == "Low":
            continue
        envelope = classify_part_evidence(part)
        reasons = [str(item).strip() for item in assessment.get("risk_reasons") or [] if str(item).strip()]
        items.append({
            "analysis_id": str(context.get("id") or context.get("analysis_id") or report.get("id") or ""),
            "project_name": context.get("project_name") or report.get("project_name"),
            "bom_name": context.get("bom_name") or report.get("bom_name"),
            "mpn": str(part.get("MPN") or part.get("mpn") or part.get("manufacturer_part_number") or "Component"),
            "risk_level": level,
            "bom_path": part.get("bom_path_display") or part.get("bom_path"),
            "why": "; ".join(reasons) or "Current supplier evidence is insufficient to assess this component.",
            "evidence_source": str(envelope.get("evidence_class") or "missing"),
            "action": "Open the report and review the component evidence",
            "risk_score": assessment.get("risk_score"),
        })
    return sorted(
        items,
        key=lambda item: (rank.get(str(item.get("risk_level") or ""), 3), -(float(item.get("risk_score") or 0))),
    )


def _attach_intake(report: dict[str, Any], result: IntakeResult) -> None:
    """Keep each raw input value beside its normalized value on the saved report."""
    by_part = result.source_rows_by_part()
    for part in report.get("parts") or []:
        mpn = str(part.get("mpn") or part.get("MPN") or "").strip().casefold()
        parent = (
            str(part.get("parent_mpn_display") or "").strip().casefold()
            if result.hierarchical
            else ""
        )
        rows = by_part.get((mpn, parent))
        if rows:
            part["source_rows"] = rows
    report["intake"] = result.intake_record()


def analyze_dataframe(
    df: pd.DataFrame,
    *,
    analysis_mode: str | None = None,
    analysis_id: str | None = None,
) -> dict[str, Any]:
    from apps.api.legacy_supplier_workflow import production_analysis_enabled

    use_legacy_engine = (
        bool(analysis_mode == "legacy-supplier")
        if analysis_mode is not None
        else production_analysis_enabled()
    )
    rows: list[dict[str, Any]] = []
    if use_legacy_engine:
        from apps.api.legacy_supplier_workflow import analyze_rows

        rows = analyze_rows(df)
        for index, (_, row) in enumerate(df.iterrows()):
            if index < len(rows):
                rows[index].update(attach_hierarchy_fields(row.to_dict()))
        report_mode = "legacy-supplier-engine"
    else:
        for _, row in df.iterrows():
            source = row.to_dict()
            # Prefer the BOM spelling for display; keep normalized form for lookup keys.
            display_mpn = str(row.get("mpn") or row.get("mpn_normalized") or "").strip()
            mpn_key = str(row.get("mpn_normalized") or row.get("mpn") or "").strip()
            manufacturer = str(row.get("manufacturer") or "").strip()
            description = str(row.get("description") or "").strip()
            quantity = row.get("quantity", 1)
            part = _synthetic_part(mpn_key or display_mpn, manufacturer, description, quantity)
            risk = calculate_risk(part)
            hierarchy_fields = attach_hierarchy_fields(source)
            rows.append(
                {
                    "MPN": display_mpn or mpn_key,
                    "mpn": display_mpn or mpn_key,
                    "mpn_normalized": mpn_key or display_mpn,
                    "Manufacturer": manufacturer,
                    "manufacturer": manufacturer,
                    "Description": description,
                    "description": description,
                    "Quantity": quantity,
                    "quantity": quantity,
                    "Lifecycle": part["lifecycle_status"],
                    "lifecycle_status": part["lifecycle_status"],
                    "Stock": part["stock_total"],
                    "stock": part["stock_total"],
                    "stock_available": part["stock_available"],
                    "Unit Price": part["unit_price"],
                    "unit_price": part["unit_price"],
                    "unit_price_currency": "USD",
                    "Risk Score": risk.get("risk_score"),
                    "risk_score": risk.get("risk_score"),
                    "Risk Level": risk.get("risk_level"),
                    "risk_level": risk.get("risk_level"),
                    "Risk Reasons": "; ".join(risk.get("reasons") or []),
                    "supplier_count": 1,
                    "Supplier Data Verified": True,
                    "Stock Data Complete": True,
                    "Source": "synthetic-preview",
                    "source": "synthetic-preview",
                    "price_source": "synthetic-preview",
                    "evidence_class": "synthetic-preview",
                    "evidence_source": "synthetic-preview",
                    **hierarchy_fields,
                }
            )
        report_mode = "synthetic-preview"

    hierarchy: dict[str, Any] | None = None
    if has_hierarchy(rows):
        hierarchy = rollup_assemblies(rows)
        rows = hierarchy["parts"]

    results = pd.DataFrame(rows)
    # Health score uses leaf/component rows; assembly lines still counted but
    # risk comes from synthetic evidence on each row.
    health = calculate_bom_health_score(results)
    levels = results["Risk Level"].fillna("").astype(str).str.casefold()
    analysis_id = str(analysis_id or uuid.uuid4())
    report = {
        "id": analysis_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": report_mode,
        "filename": "",
        "total_parts": int(len(results)),
        "health_score": health.get("health_score"),
        "health_status": health.get("health_status"),
        "summary_message": health.get("summary_message"),
        "high_risk_count": int(levels.eq("high").sum()),
        "medium_risk_count": int(levels.eq("medium").sum()),
        "low_risk_count": int(levels.isin(["low", "healthy"]).sum()),
        "needs_verification_count": int(health.get("needs_verification_count") or 0),
        "parts": rows,
        "hierarchy": hierarchy,
    }
    _REPORTS[analysis_id] = report
    return report


def analyze_upload(
    *,
    filename: str,
    payload: bytes,
    workspace_id: str,
    project_name: str | None = None,
    bom_name: str | None = None,
    revision: str | None = None,
    persist: bool = True,
    analysis_mode: str | None = None,
    analysis_id: str | None = None,
    derived_from_analysis_id: str | None = None,
    applied_decision_ids: list[str] | None = None,
    used_decision_ids: list[str] | None = None,
    column_mapping: dict[str, str] | None = None,
    supplier_specific: bool = False,
    default_supplier: str = "",
    exclude_invalid_rows: bool = False,
    row_corrections: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    intake = parse_bom_intake(
        filename,
        payload,
        column_mapping=column_mapping,
        supplier_specific=supplier_specific,
        default_supplier=default_supplier,
        exclude_invalid_rows=exclude_invalid_rows,
        row_corrections=row_corrections,
    )
    _require_analyzable(intake)
    df = intake.dataframe()
    report = analyze_dataframe(df, analysis_mode=analysis_mode, analysis_id=analysis_id)
    _attach_intake(report, intake)
    report["filename"] = filename or "bom.csv"
    report["workspace_id"] = workspace_id
    if derived_from_analysis_id:
        report["derived_from_analysis_id"] = str(derived_from_analysis_id)
    if applied_decision_ids:
        report["applied_decision_ids"] = [str(item) for item in applied_decision_ids]
    if used_decision_ids:
        report["used_decision_ids"] = [str(item) for item in used_decision_ids]
    # Durable stores require JSON-safe payloads (no NaN / numpy scalars).
    report = json_safe(report)
    assert isinstance(report, dict)
    _REPORTS[report["id"]] = report
    if persist:
        store = get_store()
        report = store.upsert_analysis_report(
            report,
            workspace_id=workspace_id,
            project_name=project_name,
            bom_name=bom_name,
            revision=revision,
        )
        verified = store.get_report(str(report["id"]), workspace_id=workspace_id)
        if not verified:
            _REPORTS.pop(str(report.get("id") or ""), None)
            raise PersistenceVerifyError(
                "BOM analysis could not be confirmed in workspace storage after save. "
                "The report was not kept — retry the analysis."
            )
        if not verified.get("persisted", True):
            raise PersistenceNotConfiguredError(
                "BOM analysis completed but workspace storage did not mark it as saved."
            )
        parts = verified.get("parts") or []
        if int(verified.get("total_parts") or 0) > 0 and not parts:
            raise PersistenceVerifyError(
                "BOM analysis saved without component rows. Retry the analysis."
            )
        report = verified
        report["persisted"] = True
        _REPORTS[report["id"]] = report
    return report


def get_report(analysis_id: str, *, workspace_id: str) -> dict[str, Any] | None:
    from apps.api.workspace_store import WorkspaceAccessError

    store = get_store()
    try:
        report = store.get_report(analysis_id, workspace_id=workspace_id)
    except WorkspaceAccessError:
        raise
    if report:
        _REPORTS[analysis_id] = report
        return _report_with_current_assessment(report)
    # Store is authoritative — do not resurrect deleted analyses from memory.
    _REPORTS.pop(analysis_id, None)
    return None


def recalculate_report_health(
    analysis_id: str, *, workspace_id: str
) -> dict[str, Any] | None:
    """Re-evaluate a saved report's health from its saved part evidence only."""
    report = get_report(analysis_id, workspace_id=workspace_id)
    if not report:
        return None

    calculated = assess_saved_report(report)
    recalculated_at = datetime.now(timezone.utc).isoformat()
    health = {
        "health_score": calculated.get("health_score"),
        "health_status": calculated.get("health_status") or "Not scored",
        "summary_message": calculated.get("summary_message") or "Health could not be calculated from saved evidence.",
        "assessment_coverage": calculated.get("assessment_coverage"),
        "needs_verification_count": int(calculated.get("needs_verification_count") or 0),
        "high_risk_count": int(calculated.get("high_risk_count") or 0),
        "medium_risk_count": int(calculated.get("medium_risk_count") or 0),
        "low_risk_count": int(calculated.get("low_risk_count") or 0),
        "health_recalculated_at": recalculated_at,
        "health_source": "saved-evidence",
    }
    saved = get_store().update_analysis_health(
        analysis_id,
        workspace_id=workspace_id,
        health=health,
    )
    if not saved:
        return None
    _REPORTS[analysis_id] = dict(saved)
    return {
        "ok": True,
        "analysis_id": analysis_id,
        **health,
        "source_label": "Saved evidence; suppliers were not queried.",
    }


def delete_report(analysis_id: str, *, workspace_id: str) -> bool:
    """Delete analysis from durable store and drop any process-local cache."""
    from apps.api.workspace_store import WorkspaceAccessError

    store = get_store()
    deleted = store.delete_analysis(analysis_id, workspace_id=workspace_id)
    _REPORTS.pop(analysis_id, None)
    return deleted


def delete_project(project_id: str, *, workspace_id: str) -> bool:
    """Delete project (cascade) and drop cached reports for that workspace."""
    store = get_store()
    # Capture report ids before cascade so the process cache stays honest.
    before = {
        rid
        for rid, report in _REPORTS.items()
        if report.get("workspace_id") == workspace_id
        and report.get("project_id") == project_id
    }
    deleted = store.delete_project(project_id, workspace_id=workspace_id)
    if deleted:
        for rid in before:
            _REPORTS.pop(rid, None)
        # Also drop any remaining ids that store no longer has for this workspace.
        for rid in list(_REPORTS):
            cached = _REPORTS.get(rid) or {}
            if cached.get("workspace_id") != workspace_id:
                continue
            if cached.get("project_id") == project_id:
                _REPORTS.pop(rid, None)
    return deleted


def list_reports(*, workspace_id: str) -> list[dict[str, Any]]:
    """Newest-first summaries for one workspace only."""
    store = get_store()
    reports = store.list_reports(workspace_id=workspace_id)
    # Fetch rows in one store operation so all report summaries are recalculated
    # from row-level provenance without N+1 detail requests.
    try:
        _analyses, saved_parts = store.analyses_and_parts(workspace_id=workspace_id)
    except Exception:  # noqa: BLE001 - fall back to workspace-scoped report reads below
        saved_parts = []
    parts_by_analysis: dict[str, list[dict[str, Any]]] = {}
    for part in saved_parts:
        if not isinstance(part, dict):
            continue
        analysis_key = str(part.get("analysis_id") or "")
        if analysis_key:
            parts_by_analysis.setdefault(analysis_key, []).append(part)

    stored: dict[str, dict[str, Any]] = {}
    for row in reports:
        analysis_key = str(row.get("id") or row.get("analysis_id") or "")
        detail = _REPORTS.get(analysis_key) or {}
        if not detail.get("parts") and analysis_key:
            try:
                detail = store.get_report(analysis_key, workspace_id=workspace_id) or {}
            except Exception:  # noqa: BLE001
                detail = {}
        detail_parts = detail.get("parts") if isinstance(detail.get("parts"), list) else []
        assessment_source = {
            **detail,
            "parts": detail_parts or parts_by_analysis.get(analysis_key, []),
        }
        stored[analysis_key] = {
            **row,
            **assess_saved_report(assessment_source),
        }
    for report in _REPORTS.values():
        if report.get("workspace_id") != workspace_id:
            continue
        stored.setdefault(
            report["id"],
            {
                "id": report["id"],
                "analysis_id": report["id"],
                "workspace_id": workspace_id,
                "filename": report.get("filename") or "bom.csv",
                "created_at": report.get("created_at"),
                **assess_saved_report(report),
                "mode": report.get("mode"),
                "project_name": report.get("project_name"),
                "bom_name": report.get("bom_name"),
                "revision": report.get("revision"),
                "has_hierarchy": bool((report.get("hierarchy") or {}).get("has_hierarchy")),
            },
        )
    return sorted(
        stored.values(),
        key=lambda row: str(row.get("created_at") or ""),
        reverse=True,
    )


def analyses_and_parts(
    *, workspace_id: str, analysis_id: str | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Shape persisted reports for Cadivor build_* helpers (workspace-scoped)."""
    from apps.api.workspace_store import WorkspaceAccessError

    store = get_store()
    try:
        analyses, parts = store.analyses_and_parts(
            workspace_id=workspace_id, analysis_id=analysis_id
        )
    except WorkspaceAccessError:
        raise
    if analyses:
        parts_by_analysis: dict[str, list[dict[str, Any]]] = {}
        for part in parts:
            if isinstance(part, dict):
                parts_by_analysis.setdefault(
                    str(part.get("analysis_id") or ""), []
                ).append(part)
        refreshed_analyses = []
        for analysis in analyses:
            key = str(analysis.get("id") or analysis.get("analysis_id") or "")
            assessment = assess_saved_report({"parts": parts_by_analysis.get(key, [])})
            refreshed_analyses.append({**analysis, **assessment})
        return refreshed_analyses, parts
    if analysis_id:
        report = get_report(analysis_id, workspace_id=workspace_id)
        selected = [report] if report else []
    else:
        selected = [
            report
            for report in _REPORTS.values()
            if report.get("workspace_id") == workspace_id
        ]
    out_a: list[dict[str, Any]] = []
    out_p: list[dict[str, Any]] = []
    for report in selected:
        if not report:
            continue
        out_a.append(
            {
                "id": report["id"],
                "workspace_id": workspace_id,
                "filename": report.get("filename") or "bom.csv",
                "name": report.get("project_name") or report.get("filename") or "bom.csv",
                "project_name": report.get("project_name")
                or report.get("filename")
                or "Synthetic BOM",
                "created_at": report.get("created_at"),
                "updated_at": report.get("created_at"),
                **assess_saved_report(report),
                "total_parts": report.get("total_parts"),
                "mode": report.get("mode"),
            }
        )
        for part in report.get("parts") or []:
            enriched = dict(part)
            enriched["analysis_id"] = report["id"]
            enriched["workspace_id"] = workspace_id
            enriched.setdefault("filename", report.get("filename") or "bom.csv")
            out_p.append(enriched)
    return out_a, out_p


def synthetic_compare_part(mpn: str, *, from_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a compare-ready part record without live distributor lookup."""
    from apps.api.compare_catalog import enrich_compare_part

    if from_report:
        record = {
            "manufacturer_part_number": str(from_report.get("MPN") or mpn),
            "manufacturer": str(from_report.get("Manufacturer") or ""),
            "description": str(from_report.get("Description") or ""),
            "lifecycle_status": str(from_report.get("Lifecycle") or "Unknown"),
            "stock_available": from_report.get("Stock"),
            "unit_price": from_report.get("unit_price") or from_report.get("Unit Price"),
            "found": True,
            "source": "synthetic-preview-analysis",
            "supplier_data_verified": False,
        }
        return enrich_compare_part(str(record["manufacturer_part_number"] or mpn), record)
    base = _synthetic_part(mpn, "", "", 1)
    record = {
        "manufacturer_part_number": mpn,
        "manufacturer": base["manufacturer"],
        "description": base["description"],
        "lifecycle_status": base["lifecycle_status"],
        "stock_available": base["stock_available"],
        "unit_price": base["unit_price"],
        "found": True,
        "source": "synthetic-preview",
        "supplier_data_verified": False,
    }
    return enrich_compare_part(mpn, record)

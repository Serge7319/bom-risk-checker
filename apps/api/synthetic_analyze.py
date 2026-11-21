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
        return report
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

    saved_parts = [row for row in (report.get("parts") or []) if isinstance(row, dict)]
    results = pd.DataFrame(saved_parts)
    aliases = {
        "Risk Level": "risk_level",
        "Risk Score": "risk_score",
        "Supplier Data Verified": "supplier_data_verified",
        "Stock Data Complete": "stock_data_complete",
    }
    for target, source in aliases.items():
        if target not in results.columns and source in results.columns:
            results[target] = results[source]

    calculated = calculate_bom_health_score(results)
    recalculated_at = datetime.now(timezone.utc).isoformat()
    health = {
        "health_score": calculated.get("health_score"),
        "health_status": calculated.get("health_status") or "Not scored",
        "summary_message": calculated.get("summary_message") or "Health could not be calculated from saved evidence.",
        "assessment_coverage": calculated.get("assessment_coverage"),
        "needs_verification_count": int(calculated.get("needs_verification_count") or 0),
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
    stored = {row["id"]: row for row in store.list_reports(workspace_id=workspace_id)}
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
                "total_parts": report.get("total_parts"),
                "health_score": report.get("health_score"),
                "health_status": report.get("health_status"),
                "high_risk_count": report.get("high_risk_count"),
                "medium_risk_count": report.get("medium_risk_count"),
                "low_risk_count": report.get("low_risk_count"),
                "mode": report.get("mode"),
                "project_name": report.get("project_name"),
                "bom_name": report.get("bom_name"),
                "revision": report.get("revision"),
                "has_hierarchy": bool((report.get("hierarchy") or {}).get("has_hierarchy")),
            },
        )
    return sorted(
        stored.values(),
        key=lambda row: str(row
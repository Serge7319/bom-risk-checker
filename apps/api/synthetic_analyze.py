"""Headless synthetic BOM analyze using production parse/risk/health modules.

Supplier HTTP, Stripe, email are not used. Analyses persist via the migration
workspace store (Postgres when CADIVOR_MIGRATION_DATABASE_URL is set; otherwise
ephemeral file for local/tests only). Part enrichment is deterministic
synthetic evidence so health scoring can complete offline.
"""
from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from apps.api.bom_hierarchy import (
    attach_hierarchy_fields,
    has_hierarchy,
    rollup_assemblies,
)
from apps.api.workspace_store import get_store
from src.bom_parser import (
    aggregate_bom_rows,
    clean_bom_data,
    normalize_bom_columns,
    validate_bom,
)
from src.health_score import calculate_bom_health_score
from src.risk_engine import calculate_risk

# Process-local mirror kept for backward compatibility with in-flight callers.
_REPORTS: dict[str, dict[str, Any]] = {}


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


def parse_bom_bytes(filename: str, payload: bytes) -> pd.DataFrame:
    buffer = io.BytesIO(payload)
    buffer.name = filename or "bom.csv"
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xls")):
        df = pd.read_excel(buffer)
    else:
        df = pd.read_csv(buffer)
    df = normalize_bom_columns(df)
    df = validate_bom(df)
    # Preserve parent/child structure: aggregate only when flat.
    hierarchical = "parent_mpn" in df.columns and df["parent_mpn"].fillna("").astype(str).str.strip().ne("").any()
    if hierarchical:
        # Aggregate identical (mpn, parent) pairs only.
        if "parent_mpn" not in df.columns:
            df["parent_mpn"] = ""
        df["parent_mpn"] = df["parent_mpn"].fillna("").astype(str)
        groups = []
        for (_mpn, _parent), group in df.groupby(["mpn", "parent_mpn"], sort=False, dropna=False):
            first = group.iloc[0].to_dict()
            if "quantity" in group.columns:
                quantity_values = pd.to_numeric(group["quantity"], errors="coerce")
                first["quantity"] = quantity_values.fillna(0).sum()
            groups.append(first)
        df = pd.DataFrame(groups)
    else:
        df = aggregate_bom_rows(df)
    return clean_bom_data(df)


def analyze_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        source = row.to_dict()
        mpn = str(row.get("mpn_normalized") or row.get("mpn") or "").strip()
        manufacturer = str(row.get("manufacturer") or "").strip()
        description = str(row.get("description") or "").strip()
        quantity = row.get("quantity", 1)
        part = _synthetic_part(mpn, manufacturer, description, quantity)
        risk = calculate_risk(part)
        hierarchy_fields = attach_hierarchy_fields(source)
        rows.append(
            {
                "MPN": mpn,
                "mpn": mpn,
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
                **hierarchy_fields,
            }
        )

    hierarchy: dict[str, Any] | None = None
    if has_hierarchy(rows):
        hierarchy = rollup_assemblies(rows)
        rows = hierarchy["parts"]

    results = pd.DataFrame(rows)
    # Health score uses leaf/component rows; assembly lines still counted but
    # risk comes from synthetic evidence on each row.
    health = calculate_bom_health_score(results)
    levels = results["Risk Level"].fillna("").astype(str).str.casefold()
    analysis_id = str(uuid.uuid4())
    report = {
        "id": analysis_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "synthetic-preview",
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
) -> dict[str, Any]:
    df = parse_bom_bytes(filename, payload)
    report = analyze_dataframe(df)
    report["filename"] = filename or "bom.csv"
    report["workspace_id"] = workspace_id
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
        return analyses, parts
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
                "health_score": report.get("health_score"),
                "high_risk_count": report.get("high_risk_count"),
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
    if from_report:
        return {
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
    base = _synthetic_part(mpn, "", "", 1)
    return {
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

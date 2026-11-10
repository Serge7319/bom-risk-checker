"""Tool handlers for Next.js migration pages.

Reuses Cadivor build_* helpers on saved synthetic analyses. Never calls
live distributors, Stripe, email, or Supabase. Prices/stock are labeled
synthetic-preview when present.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from apps.api.synthetic_analyze import (
    analyses_and_parts,
    get_report,
    list_reports,
    synthetic_compare_part,
)
from src.cost_optimization import build_cost_optimization
from src.datasheet_qa import (
    answer_datasheet_question,
    extract_uploaded_datasheet,
    suggest_datasheet_follow_ups,
)
from src.design_impact_analyzer import build_design_impact
from apps.api.evidence_contract import annotate_report_parts, classify_part_evidence
from apps.api.supplier_lookup import lookup_exact_part
from apps.api import monitoring_store
from src.monitoring_engine import build_alert_record
from src.monitoring_intelligence import build_monitoring_action_center
from src.parts_compare import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    build_parts_comparison,
    user_facing_compare_rows,
)
from src.portfolio_intelligence import build_portfolio_intelligence
from src.procurement_advisor import (
    apply_sourcing_override,
    build_procurement_advisor,
    normalize_supplier_offer_records,
)
from src.supply_risk_scenario import build_supply_scenario
from src.ui.detailed_risk_export import component_rows, report_exposure_summary


def _json_safe(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return _json_safe(value.replace({pd.NA: None}).to_dict(orient="records"))
    if isinstance(value, pd.Series):
        return _json_safe(value.replace({pd.NA: None}).to_dict())
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, set):
        return sorted(_json_safe(v) for v in value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            return str(value)
    if isinstance(value, float) and (value != value):  # NaN
        return None
    return value

def _require_analysis(
    analysis_id: str | None, *, workspace_id: str
) -> dict[str, Any] | None:
    if analysis_id:
        return get_report(analysis_id, workspace_id=workspace_id)
    reports = list_reports(workspace_id=workspace_id)
    if not reports:
        return None
    return get_report(reports[0]["id"], workspace_id=workspace_id)


def _customer_assessment(value: Any) -> str:
    """Map internal needs-data labels to customer-facing Needs verification."""
    text = str(value or "").strip()
    lower = text.lower()
    if not text:
        return "Needs verification"
    if "conflict" in lower:
        return "Conflicting evidence"
    if (
        "needs data" in lower
        or "needs validation" in lower
        or "needs verification" in lower
        or "unable to confirm" in lower
        or "unassess" in lower
    ):
        return "Needs verification"
    return text


def _customer_compare_value(value: Any) -> Any:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "null", "n/a", "—", "-"}:
        return "Needs verification"
    lower = text.lower()
    if "not stated" in lower or "not retrieved" in lower or "not available" in lower:
        return "Needs verification"
    if "unable to confirm" in lower:
        return "Needs verification"
    return value


def _optional_number(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    if abs(number - round(number)) < 1e-9:
        return int(round(number))
    return number


def _risk_score_from_report_part(part: dict[str, Any]) -> float | int | None:
    known = _optional_number(part.get("Risk Score") if part.get("Risk Score") is not None else part.get("risk_score"))
    if known is not None:
        return known
    level = str(part.get("Risk Level") or part.get("risk_level") or "").strip().lower()
    if level == "high":
        return 75
    if level == "medium":
        return 45
    if level in {"low", "healthy"}:
        return 15
    return None


def _monitoring_evidence_source(part: dict[str, Any], report: dict[str, Any]) -> str:
    """Use the part's saved provenance; never relabel live evidence as synthetic."""
    raw = str(
        part.get("evidence_source")
        or part.get("evidence_class")
        or part.get("Source")
        or part.get("source")
        or part.get("price_source")
        or ""
    ).strip()
    tag = raw.casefold()
    verified = part.get("supplier_data_verified") is True or str(
        part.get("Supplier Data Verified") or ""
    ).strip().casefold() in {"1", "true", "yes", "verified"}
    report_mode = str(report.get("mode") or "").casefold()
    if tag == "missing":
        return "missing"
    if tag.startswith("live") or (verified and report_mode == "legacy-supplier-engine"):
        return raw if tag.startswith("live") else "live-authorized-supplier"
    if any(token in tag for token in ("synthetic", "preview", "offline")):
        return raw or "synthetic-preview-analysis"
    if report_mode == "synthetic-preview":
        return raw or "synthetic-preview-analysis"
    if report_mode == "legacy-supplier-engine" and verified:
        return "live-authorized-supplier"
    return raw or "missing"


def _monitoring_evidence_phrase(evidence_source: str) -> str:
    tag = str(evidence_source or "").casefold()
    if tag.startswith("live"):
        return "live authorized-supplier evidence"
    if "synthetic" in tag or "preview" in tag:
        return "synthetic analysis"
    if tag == "missing":
        return "saved analysis without verified supplier evidence"
    return "saved analysis"


def monitoring_payload(
    *, workspace_id: str, analysis_id: str | None = None
) -> dict[str, Any]:
    report = _require_analysis(analysis_id, workspace_id=workspace_id)
    if not report:
        return {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": "No analyzed BOM yet. Run BOM Analyzer first. This view needs saved analysis data.",
            "metrics": {
                "monitored_parts": 0,
                "active_alerts": 0,
                "high_priority": 0,
                "lifecycle_changes": 0,
            },
            "alerts": [],
            "action_center": {},
        }

    alerts: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    report_mode = str(report.get("mode") or "synthetic-preview")
    for part in report.get("parts") or []:
        if not isinstance(part, dict):
            continue
        mpn = str(part.get("MPN") or part.get("mpn") or "")
        if not mpn:
            continue
        lifecycle = str(part.get("Lifecycle") or part.get("lifecycle_status") or "")
        risk = str(part.get("Risk Level") or part.get("risk_level") or "")
        evidence_source = _monitoring_evidence_source(part, report)
        evidence_phrase = _monitoring_evidence_phrase(evidence_source)
        if lifecycle.upper() == "NRND":
            alerts.append(
                {
                    **build_alert_record(
                        "smoke-user",
                        report["id"],
                        mpn,
                        "Lifecycle Signal",
                        f"Lifecycle recorded as {lifecycle} in {evidence_phrase}",
                        "High",
                        "Active (assumed)",
                        lifecycle,
                    ),
                    "created_at": now,
                    "acknowledged": False,
                    "evidence_source": evidence_source,
                }
            )
        if risk.lower() == "high":
            alerts.append(
                {
                    **build_alert_record(
                        "smoke-user",
                        report["id"],
                        mpn,
                        "Risk Signal",
                        f"High risk in latest analysis: {part.get('Risk Reasons') or part.get('risk_reasons') or 'see report'}",
                        "High",
                        "—",
                        risk,
                    ),
                    "created_at": now,
                    "acknowledged": False,
                    "evidence_source": evidence_source,
                }
            )
        elif risk.lower() == "medium":
            alerts.append(
                {
                    **build_alert_record(
                        "smoke-user",
                        report["id"],
                        mpn,
                        "Risk Signal",
                        f"Medium risk in latest analysis: {part.get('Risk Reasons') or part.get('risk_reasons') or 'see report'}",
                        "Medium",
                        "—",
                        risk,
                    ),
                    "created_at": now,
                    "acknowledged": False,
                    "evidence_source": evidence_source,
                }
            )

    for alert in alerts:
        alert["analysis_id"] = report["id"]
        alert["workspace_id"] = workspace_id
        # Preserve the per-part provenance already attached above.
        alert["evidence_source"] = alert.get("evidence_source") or _monitoring_evidence_source(
            {}, report
        )

    durable = monitoring_store.persist_alerts(workspace_id, alerts)
    # Hard scope: only alerts for this analysis_id feed KPIs / action center / UI.
    scoped = [
        alert
        for alert in durable
        if str(alert.get("analysis_id") or "").strip() == str(report["id"]).strip()
    ]
    alert_df = pd.DataFrame(scoped)
    monitor_df = pd.DataFrame(
        [
            {
                "part_number": p.get("MPN") or p.get("mpn"),
                "lifecycle_status": p.get("Lifecycle") or p.get("lifecycle_status"),
                "stock": p.get("Stock") if p.get("Stock") is not None else p.get("stock"),
                "risk_level": p.get("Risk Level") or p.get("risk_level"),
            }
            for p in report.get("parts") or []
            if isinstance(p, dict)
        ]
    )
    action_center = build_monitoring_action_center(alert_df, monitor_df)
    high = sum(1 for a in scoped if str(a.get("severity")).lower() == "high")
    lifecycle_n = sum(
        1 for a in scoped if "lifecycle" in str(a.get("alert_type") or "").lower()
    )
    refresh = monitoring_store.record_refresh(
        workspace_id,
        analysis_id=report["id"],
        alert_count=len(scoped),
        mode=report_mode,
    )
    prefs = monitoring_store.get_preferences(workspace_id)
    return _json_safe(
        {
            "ok": True,
            "mode": report_mode,
            "analysis_id": report["id"],
            "filename": report.get("filename"),
            "gap": (
                "Monitoring persists tenant-scoped alert history from saved analysis. "
                "Scheduled supplier refresh and real alert email remain disabled."
            ),
            "metrics": {
                "monitored_parts": report.get("total_parts") or 0,
                "active_alerts": len(scoped),
                "high_priority": high,
                "lifecycle_changes": lifecycle_n,
            },
            "alerts": scoped,
            "action_center": action_center,
            "preferences": prefs,
            "refresh": refresh,
            "refresh_history": monitoring_store.list_refresh_history(workspace_id)[:10],
        }
    )


def compare_parts_payload(
    *,
    workspace_id: str,
    part_a: str,
    part_b: str,
    analysis_id: str | None = None,
    use_latest_if_missing: bool = True,
    datasheet_uploads: dict[str, Any] | None = None,
) -> dict[str, Any]:
    a = str(part_a or "").strip()
    b = str(part_b or "").strip()
    if not a or not b:
        return {
            "ok": False,
            "status": STATUS_FAILED,
            "detail": "Enter both Part A and Part B manufacturer part numbers.",
        }
    if a.casefold() == b.casefold():
        return {
            "ok": False,
            "status": STATUS_FAILED,
            "detail": "Part A and Part B must be different.",
        }

    # Production Next.js comparisons use the same supplier and datasheet
    # engines as the original Streamlit workflow. Local/synthetic previews keep
    # their isolated data path unless a reviewer attaches exact-MPN PDFs.
    from apps.api.legacy_supplier_workflow import production_analysis_enabled

    if production_analysis_enabled():
        return _legacy_compare_parts_payload(
            workspace_id=workspace_id,
            part_a=a,
            part_b=b,
            analysis_id=analysis_id,
            datasheet_uploads=datasheet_uploads,
            extract_linked_datasheets=True,
        )
    if datasheet_uploads:
        return _uploaded_compare_parts_payload(
            workspace_id=workspace_id,
            part_a=a,
            part_b=b,
            analysis_id=analysis_id,
            datasheet_uploads=datasheet_uploads,
        )

    report = (
        _require_analysis(analysis_id, workspace_id=workspace_id)
        if analysis_id or use_latest_if_missing
        else None
    )

    by_mpn: dict[str, dict[str, Any]] = {}
    if report:
        for part in report.get("parts") or []:
            key = str(part.get("MPN") or "").strip().casefold()
            if key:
                by_mpn[key] = part

    source_a = "synthetic-preview"
    source_b = "synthetic-preview"
    if a.casefold() in by_mpn:
        data_a = synthetic_compare_part(a, from_report=by_mpn[a.casefold()])
        source_a = "synthetic-preview-analysis"
    else:
        data_a = synthetic_compare_part(a)
    if b.casefold() in by_mpn:
        data_b = synthetic_compare_part(b, from_report=by_mpn[b.casefold()])
        source_b = "synthetic-preview-analysis"
    else:
        data_b = synthetic_compare_part(b)

    comparison = build_parts_comparison(
        data_a,
        data_b,
        part_a_mpn=a,
        part_b_mpn=b,
        extract_linked_datasheets=False,
    )
    # Prefer rows that already carry Assessment from build_parts_comparison so
    # family-mismatch verdicts are not collapsed to "Needs data".
    raw_rows = comparison.get("rows") or comparison.get("comparison_rows") or []
    rows: list[dict[str, Any]] = []
    if isinstance(raw_rows, list) and raw_rows and isinstance(raw_rows[0], dict) and (
        "Assessment" in raw_rows[0]
    ):
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "Attribute": row.get("Attribute", ""),
                    "Part A": _customer_compare_value(row.get("Part A", row.get("Original", ""))),
                    "Part B": _customer_compare_value(
                        row.get(
                            "Part B",
                            row.get("Candidate", row.get("Selected Alternative", "")),
                        )
                    ),
                    "Part A MPN": row.get("Part A MPN") or a,
                    "Part B MPN": row.get("Part B MPN") or b,
                    "Part A source": row.get("Part A source") or row.get("OriginalSource") or "Not stated",
                    "Part B source": row.get("Part B source") or row.get("CandidateSource") or "Not stated",
                    "Unit": row.get("Unit") or "",
                    "Test condition": row.get("Test condition") or "Not stated",
                    "Part A value class": row.get("Part A value class") or "unknown",
                    "Part B value class": row.get("Part B value class") or "unknown",
                    "Assessment": _customer_assessment(
                        row.get("Assessment") or row.get("Status") or ""
                    ),
                    "Evidence": row.get("Evidence") or row.get("Note") or "",
                }
            )
    if not rows:
        rows = [
            {
                **item,
                "Part A": _customer_compare_value(item.get("Part A")),
                "Part B": _customer_compare_value(item.get("Part B")),
                "Assessment": _customer_assessment(item.get("Assessment")),
            }
            for item in user_facing_compare_rows(raw_rows)
        ]
    if not rows and isinstance(comparison.get("user_facing_rows"), list):
        rows = [
            {
                **item,
                "Part A": _customer_compare_value(item.get("Part A")),
                "Part B": _customer_compare_value(item.get("Part B")),
                "Assessment": _customer_assessment(item.get("Assessment")),
            }
            for item in comparison["user_facing_rows"]
            if isinstance(item, dict)
        ]

    finding = (
        comparison.get("overall_finding")
        or comparison.get("finding")
        or comparison.get("summary")
    )
    family_mismatch = bool(comparison.get("family_mismatch"))
    gap = (
        "No live supplier or manufacturer datasheet lookup is connected in this deployment. "
        "Values absent from the saved BOM and offline identity catalog remain unverified; "
        "this result cannot confirm drop-in compatibility."
    )
    if family_mismatch:
        gap = (
            "The offline catalog identifies different component families. Treat this as a "
            "review signal, not a qualified drop-in verdict; manufacturer datasheets were not fetched."
        )
    elif not rows:
        gap = (
            "No comparable source-backed attributes were found. Connect supplier/datasheet "
            "evidence or review manufacturer documentation before making a substitution."
        )

    counts = comparison.get("counts") or {}
    evidence_sources = comparison.get("evidence_sources") or {}
    unknown_attributes = [
        str(row.get("Attribute") or "")
        for row in rows
        if str(row.get("Assessment") or "").strip().lower()
        in {"unable to confirm", "needs validation", "needs data"}
        and str(row.get("Attribute") or "").strip()
    ]
    analysis_context = str((report or {}).get("id") or "") or None

    return _json_safe(
        {
            "ok": True,
            "status": STATUS_COMPLETED,
            "mode": "synthetic-preview",
            "analysis_id": analysis_context,
            "part_a": a,
            "part_b": b,
            "source_a": source_a,
            "source_b": source_b,
            "gap": gap,
            "finding": finding,
            "family": (comparison.get("family") or comparison.get("family_meta") or {}),
            "family_mismatch": family_mismatch,
            "engineering_evidence_summary": comparison.get("engineering_evidence_summary") or "",
            "engineering_evidence_status": comparison.get("engineering_evidence_status") or "unverified",
            "counts": counts,
            "unknown_attributes": unknown_attributes,
            "rows": rows,
            "part_cards": {
                "a": comparison.get("part_a"),
                "b": comparison.get("part_b"),
            },
            "evidence_sources": evidence_sources,
            "datasheet_identity": comparison.get("datasheet_identity") or {},
            "review_warnings": comparison.get("review_warnings") or [],
            "comparison": {
                k: comparison.get(k)
                for k in (
                    "overall_finding",
                    "finding",
                    "summary",
                    "counts",
                    "engineering_confidence",
                    "engineering_evidence_summary",
                    "engineering_evidence_status",
                    "evidence_sources",
                    "datasheet_identity",
                    "family_mismatch",
                )
                if k in comparison
            },
        }
    )


def _comparison_source_label(
    comparison: dict[str, Any], side: str, *, uploaded: bool = False
) -> str:
    identity = comparison.get("datasheet_identity")
    identity = identity if isinstance(identity, dict) else {}
    side_identity = identity.get(f"part_{side}")
    side_identity = side_identity if isinstance(side_identity, dict) else {}
    if side_identity.get("verified"):
        return "uploaded-manufacturer-datasheet" if uploaded else "manufacturer-datasheet"
    if uploaded:
        return "uploaded-datasheet-unverified"
    card = comparison.get(f"part_{side}")
    card = card if isinstance(card, dict) else {}
    if card.get("supplier_url") or card.get("datasheet_url"):
        return "supplier-record-unverified"
    return "unverified"


def _comparison_payload_from_engine(
    *,
    workspace_id: str,
    part_a: str,
    part_b: str,
    analysis_id: str | None,
    engine_result: dict[str, Any],
    mode: str,
    upload_a: bool = False,
    upload_b: bool = False,
) -> dict[str, Any]:
    comparison = engine_result.get("comparison")
    if not isinstance(comparison, dict):
        return {
            "ok": False,
            "status": STATUS_FAILED,
            "detail": engine_result.get("error") or "Comparison evidence could not be prepared.",
        }
    rows = [row for row in comparison.get("rows") or [] if isinstance(row, dict)]
    unknown = [
        str(row.get("Attribute") or "")
        for row in rows
        if str(row.get("Assessment") or "").casefold()
        in {"unable to confirm", "needs data / engineering validation", "needs validation"}
        and str(row.get("Attribute") or "").strip()
    ]
    source_a = _comparison_source_label(comparison, "a", uploaded=upload_a)
    source_b = _comparison_source_label(comparison, "b", uploaded=upload_b)
    gap = str(engine_result.get("error") or "").strip()
    if not gap and (source_a in {"unverified", "uploaded-datasheet-unverified"} or source_b in {"unverified", "uploaded-datasheet-unverified"}):
        sides = []
        if source_a in {"unverified", "uploaded-datasheet-unverified"}:
            sides.append("Part A")
        if source_b in {"unverified", "uploaded-datasheet-unverified"}:
            sides.append("Part B")
        gap = (
            f"No exact-MPN manufacturer datasheet or verified supplier record was confirmed for "
            f"{' and '.join(sides)}. The returned matrix keeps those attributes unverified."
        )
    counts = comparison.get("counts") or {}
    finding = str(comparison.get("finding") or comparison.get("overall_finding") or "Needs data / engineering validation")
    return _json_safe({
        "ok": True,
        "status": STATUS_COMPLETED,
        "mode": mode,
        "analysis_id": analysis_id,
        "workspace_id": workspace_id,
        "part_a": part_a,
        "part_b": part_b,
        "source_a": source_a,
        "source_b": source_b,
        "gap": gap,
        "finding": finding,
        "family": comparison.get("family") or "General electronic component",
        "family_mismatch": bool(comparison.get("family_mismatch")),
        "engineering_evidence_summary": comparison.get("engineering_evidence_summary") or "",
        "engineering_evidence_status": comparison.get("engineering_evidence_status") or "unverified",
        "counts": counts,
        "unknown_attributes": unknown,
        "rows": rows,
        "part_cards": {
            "a": comparison.get("part_a"),
            "b": comparison.get("part_b"),
        },
        "evidence_sources": comparison.get("evidence_sources") or {},
        "package_dimension_evidence": comparison.get("package_dimension_evidence") or {},
        "datasheet_identity": comparison.get("datasheet_identity") or {},
        "review_warnings": comparison.get("review_warnings") or [],
        "comparison": {
            key: comparison.get(key)
            for key in (
                "finding", "family", "family_display_name", "family_mismatch", "counts",
                "engineering_evidence_summary", "engineering_evidence_status",
                "datasheet_identity", "evidence_sources", "review_warnings",
            )
            if key in comparison
        },
    })


def _legacy_compare_parts_payload(
    *,
    workspace_id: str,
    part_a: str,
    part_b: str,
    analysis_id: str | None,
    datasheet_uploads: dict[str, Any] | None,
    extract_linked_datasheets: bool,
) -> dict[str, Any]:
    from src.parts_compare import run_compare_parts

    report = _require_analysis(analysis_id, workspace_id=workspace_id) if analysis_id else None
    result = run_compare_parts(
        part_a,
        part_b,
        datasheet_uploads=datasheet_uploads,
        extract_linked_datasheets=extract_linked_datasheets,
    )
    return _comparison_payload_from_engine(
        workspace_id=workspace_id,
        part_a=part_a,
        part_b=part_b,
        analysis_id=str((report or {}).get("id") or "") or None,
        engine_result=result,
        mode="legacy-supplier-engine",
        upload_a=bool((datasheet_uploads or {}).get("a")),
        upload_b=bool((datasheet_uploads or {}).get("b")),
    )


def _uploaded_compare_parts_payload(
    *,
    workspace_id: str,
    part_a: str,
    part_b: str,
    analysis_id: str | None,
    datasheet_uploads: dict[str, Any],
) -> dict[str, Any]:
    from src.parts_compare import build_parts_comparison, _datasheet_from_upload_payload

    report = _require_analysis(analysis_id, workspace_id=workspace_id) if analysis_id else None
    from_report: dict[str, dict[str, Any]] = {}
    if report:
        for part in report.get("parts") or []:
            key = str(part.get("MPN") or "").strip().casefold()
            if key:
                from_report[key] = part

    data_a = synthetic_compare_part(part_a, from_report=from_report.get(part_a.casefold()))
    data_b = synthetic_compare_part(part_b, from_report=from_report.get(part_b.casefold()))
    doc_a = _datasheet_from_upload_payload(
        datasheet_uploads.get("a"), manufacturer=str(data_a.get("manufacturer") or ""), mpn=part_a
    ) if datasheet_uploads.get("a") else None
    doc_b = _datasheet_from_upload_payload(
        datasheet_uploads.get("b"), manufacturer=str(data_b.get("manufacturer") or ""), mpn=part_b
    ) if datasheet_uploads.get("b") else None
    comparison = build_parts_comparison(
        data_a,
        data_b,
        part_a_mpn=part_a,
        part_b_mpn=part_b,
        datasheet_a=doc_a,
        datasheet_b=doc_b,
        extract_linked_datasheets=False,
    )
    result = {"comparison": comparison, "error": ""}
    return _comparison_payload_from_engine(
        workspace_id=workspace_id,
        part_a=part_a,
        part_b=part_b,
        analysis_id=str((report or {}).get("id") or "") or None,
        engine_result=result,
        mode="uploaded-datasheet-review",
        upload_a=bool(doc_a),
        upload_b=bool(doc_b),
    )


def _optional_analysis_context(
    analysis_id: str | None, *, workspace_id: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Load BOM context only when an analysis ID was explicitly supplied.

    No ID means no BOM context — never imply the workspace's latest report.
    Stale or inaccessible IDs degrade to a safe notice; they must not block
    standalone search or leak another workspace's report.
    """
    from apps.api.workspace_store import WorkspaceAccessError

    requested_id = str(analysis_id or "").strip()
    if not requested_id:
        return None, None
    try:
        report = get_report(requested_id, workspace_id=workspace_id)
    except WorkspaceAccessError:
        return None, (
            "Saved BOM context is unavailable for this workspace. "
            "Running a standalone replacement search instead."
        )
    if not report:
        return None, (
            "Saved BOM context is unavailable for this workspace. "
            "Running a standalone replacement search instead."
        )
    return report, None


def find_replacement_payload(
    *,
    workspace_id: str,
    mpn: str,
    manufacturer: str = "",
    analysis_id: str | None = None,
) -> dict[str, Any]:
    """Standalone replacement search; BOM analysis is optional context only."""
    from apps.api.legacy_supplier_workflow import find_replacements, production_analysis_enabled
    from apps.api.compare_catalog import offline_replacement_candidates
    from apps.api.supplier_lookup import live_lookups_enabled, lookup_exact_part

    requested = str(mpn or "").strip()
    if not requested:
        return {
            "ok": False,
            "status": STATUS_FAILED,
            "detail": "Enter a manufacturer part number to search.",
        }

    report, context_notice = _optional_analysis_context(
        analysis_id, workspace_id=workspace_id
    )
    bom_context = None
    if report:
        for part in report.get("parts") or []:
            if str(part.get("MPN") or "").strip().casefold() == requested.casefold():
                bom_context = {
                    "analysis_id": report["id"],
                    "filename": report.get("filename"),
                    "project_name": report.get("project_name"),
                    "part": part,
                }
                break
        if bom_context is None and not context_notice:
            # Explicit analysis id was valid but the MPN is not on that BOM —
            # still treat as standalone; do not invent part data from the report.
            context_notice = (
                "The linked BOM does not include this part number. "
                "Running a standalone replacement search."
            )

    context_analysis_id = (
        str(bom_context.get("analysis_id")) if bom_context else None
    )

    if production_analysis_enabled():
        result = find_replacements(requested)
        original = result.get("original") if isinstance(result.get("original"), dict) else {}
        if manufacturer and not original.get("manufacturer"):
            original["manufacturer"] = manufacturer.strip()
        outcome = (
            "candidates_found"
            if result.get("candidates")
            else str(result.get("search_outcome") or "unable_to_confirm")
        )
        return _json_safe({
            "ok": True,
            **result,
            "outcome": outcome if outcome != "failure" else (
                "unable_to_confirm" if not result.get("candidates") else outcome
            ),
            "analysis_id": context_analysis_id,
            "bom_context": bom_context,
            "context_unavailable": context_notice,
            "original": original,
        })

    original_lookup = lookup_exact_part(requested)
    original = synthetic_compare_part(
        requested,
        from_report=(bom_context or {}).get("part") if bom_context else None,
    )
    if manufacturer and not original.get("manufacturer"):
        original["manufacturer"] = manufacturer.strip()

    candidates_raw = offline_replacement_candidates(requested)
    candidates: list[dict[str, Any]] = []
    for item in candidates_raw:
        cand_mpn = str(item.get("mpn") or "").strip()
        if not cand_mpn or cand_mpn.casefold() == requested.casefold():
            continue
        enriched = synthetic_compare_part(cand_mpn)
        candidates.append(
            {
                "mpn": cand_mpn,
                "manufacturer": item.get("manufacturer") or enriched.get("manufacturer") or "",
                "description": enriched.get("description") or "",
                "rationale": item.get("rationale") or "",
                "fit": item.get("fit") or "unable_to_confirm",
                "missing_evidence": list(item.get("missing") or []),
                "evidence_class": "synthetic",
                "compare_href_query": f"part_a={requested}&part_b={cand_mpn}",
            }
        )

    missing: list[str] = []
    if not live_lookups_enabled():
        missing.append("live authorized-distributor search (credentials / transport not enabled)")
    if not candidates:
        missing.append("catalog or supplier candidate list for this MPN")
    missing.append("datasheet-backed fit scoring")

    outcome = "candidates_found" if candidates else "unable_to_confirm"
    gap = (
        "Candidate list uses the offline reference catalog. Fit is not confirmed — "
        "compare datasheets before any design change. Live supplier offers are not connected."
        if candidates
        else (
            "Unable to confirm replacements for this part. "
            + "Missing: "
            + "; ".join(missing)
            + "."
        )
    )

    return _json_safe(
        {
            "ok": True,
            "status": STATUS_COMPLETED,
            "mode": "synthetic-preview",
            "outcome": outcome,
            "requested_mpn": requested,
            "manufacturer": manufacturer or original.get("manufacturer") or "",
            "analysis_id": context_analysis_id,
            "original": {
                "mpn": original.get("manufacturer_part_number") or requested,
                "manufacturer": original.get("manufacturer") or "",
                "description": original.get("description") or "",
                "lifecycle_status": original.get("lifecycle_status") or "",
                "source": original.get("source") or "synthetic-preview",
                "lookup": original_lookup,
            },
            "bom_context": bom_context,
            "context_unavailable": context_notice,
            "candidates": candidates,
            "missing_evidence": missing,
            "gap": gap,
            "live_lookups_enabled": live_lookups_enabled(),
        }
    )


def ask_cadivor_payload(
    *,
    workspace_id: str,
    analysis_id: str,
    question: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Grounded Ask Cadivor against a saved analysis (local fallback without OpenAI)."""
    from src.services.engineering_ai import EngineeringAI, EngineeringAIError

    report = _require_analysis(analysis_id, workspace_id=workspace_id)
    if not report:
        return {
            "ok": False,
            "status": STATUS_FAILED,
            "detail": "Saved analysis required. Open a report, then ask a question.",
        }
    clean_q = str(question or "").strip()
    if not clean_q:
        return {
            "ok": False,
            "status": STATUS_FAILED,
            "detail": "Enter an engineering question.",
        }

    components: list[dict[str, Any]] = []
    for part in report.get("parts") or []:
        if not isinstance(part, dict):
            continue
        # Keep missing supplier/stock/lead fields as None so EngineeringAI does
        # not invent "0 recorded source" or equal 100/100 priorities.
        components.append(
            {
                "mpn": part.get("MPN") or part.get("mpn"),
                "part_number": part.get("MPN") or part.get("mpn"),
                "manufacturer": part.get("Manufacturer") or part.get("manufacturer"),
                "description": part.get("Description") or part.get("description"),
                "lifecycle_status": part.get("Lifecycle") or part.get("lifecycle_status"),
                "lifecycle": part.get("Lifecycle") or part.get("lifecycle_status"),
                "risk_level": part.get("Risk Level") or part.get("risk_level"),
                "risk_score": _risk_score_from_report_part(part),
                "risk_reasons": part.get("Risk Reasons") or part.get("risk_reasons"),
                "supplier_count": _optional_number(
                    part.get("supplier_count")
                    if part.get("supplier_count") is not None
                    else part.get("Supplier Count")
                ),
                "stock_available": _optional_number(
                    part.get("stock_available")
                    if part.get("stock_available") is not None
                    else part.get("Stock")
                    if part.get("Stock") is not None
                    else part.get("stock")
                ),
                "stock": part.get("Stock") if part.get("Stock") is not None else part.get("stock"),
                "lead_time_weeks": _optional_number(
                    part.get("lead_time_weeks")
                    if part.get("lead_time_weeks") is not None
                    else part.get("Lead Time Weeks")
                ),
                "quantity": (
                    part.get("effective_quantity")
                    if part.get("effective_quantity") is not None
                    else part.get("Effective Quantity")
                    if part.get("Effective Quantity") is not None
                    else part.get("Quantity")
                    if part.get("Quantity") is not None
                    else part.get("quantity")
                ),
                "quantity_per_parent": (
                    part.get("quantity_per_parent")
                    if part.get("quantity_per_parent") is not None
                    else part.get("Quantity per Parent")
                    if part.get("Quantity per Parent") is not None
                    else part.get("Quantity")
                    if part.get("Quantity") is not None
                    else part.get("quantity")
                ),
                "source": part.get("Source") or part.get("source") or report.get("mode"),
                "evidence_source": part.get("evidence_source") or part.get("Source") or part.get("source") or report.get("mode"),
            }
        )
    context = {
        "analysis": {
            "id": report.get("id"),
            "filename": report.get("filename"),
            "project_name": report.get("project_name"),
            "bom_name": report.get("bom_name"),
            "revision": report.get("revision"),
        },
        "summary": {
            "health_score": report.get("health_score"),
            "health_status": report.get("health_status"),
            "high_risk_parts": report.get("high_risk_count") or 0,
            "medium_risk_parts": report.get("medium_risk_count") or 0,
            "low_risk_parts": report.get("low_risk_count") or 0,
            "total_parts": report.get("total_parts") or len(components),
            "priority_risk_parts": int(report.get("high_risk_count") or 0)
            + int(report.get("medium_risk_count") or 0),
        },
        "components": components,
        "monitoring": [],
        "alternatives": [],
        "decisions": [],
    }
    try:
        response = EngineeringAI().ask(
            question=clean_q,
            context=context,
            history=history or [],
        )
    except EngineeringAIError as exc:
        return {
            "ok": False,
            "status": STATUS_FAILED,
            "detail": str(exc),
            "code": getattr(exc, "code", "error"),
        }

    return _json_safe(
        {
            "ok": True,
            "status": STATUS_COMPLETED,
            "analysis_id": report["id"],
            "question": clean_q,
            "answer": response.answer,
            "provider": response.provider,
            "model": response.model,
            "grounded": bool(response.grounded),
            "gap": (
                None
                if response.provider != "cadivor-grounded"
                else "Answer is grounded in this saved analysis. Cloud AI assist is optional and was not required."
            ),
        }
    )


def datasheet_qa_payload(
    *,
    filename: str,
    payload: bytes,
    question: str,
) -> dict[str, Any]:
    document = extract_uploaded_datasheet(payload, filename=filename or "datasheet.pdf")
    # Prefer local grounded answers; do not require cloud AI credentials.
    result = answer_datasheet_question(document, question, ai_client=None, history=None)
    follow_ups: list[str] = []
    try:
        follow_ups = list(suggest_datasheet_follow_ups(document, question) or [])
    except Exception:  # noqa: BLE001
        follow_ups = []
    return _json_safe(
        {
            "ok": bool(result.get("ok")),
            "mode": "synthetic-preview",
            "gap": "Answers are grounded in the uploaded PDF text. Cloud AI assist is not required; live web datasheet fetch is disabled.",
            "document": {
                "available": bool(document.get("available")),
                "filename": filename,
                "page_count": document.get("page_count") or document.get("pages"),
                "reason": document.get("reason") or "",
            },
            "question": question,
            "answer": result.get("answer") or "",
            "error": result.get("error") or "",
            "citations": result.get("citations") or [],
            "evidence": result.get("evidence") or [],
            "provider": result.get("provider") or "local",
            "follow_ups": follow_ups[:6],
        }
    )


def procurement_payload(*, workspace_id: str, analysis_id: str | None = None) -> dict[str, Any]:
    requested_id = str(analysis_id or "").strip()
    if requested_id:
        report = get_report(requested_id, workspace_id=workspace_id)
        if not report:
            return {
                "ok": False,
                "mode": "analysis-not-found",
                "analysis_id": requested_id,
                "gap": (
                    f"No saved analysis matches id {requested_id} in this workspace. "
                    "Select another analysis or run a new BOM."
                ),
                "parts": [],
            }
    else:
        report = _require_analysis(None, workspace_id=workspace_id)
    if not report:
        return {
            "ok": True,
            "mode": "no-analysis",
            "gap": None,
            "parts": [],
        }

    def first_value(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
        for key in keys:
            value = row.get(key)
            if value is not None and value != "":
                return value
        return default

    raw_parts = [
        apply_sourcing_override(dict(part))
        for part in report.get("parts") or []
        if isinstance(part, dict)
    ]
    # Reuse the established Procurement Advisor rules over the exact saved
    # report rows. Synthetic preview values remain visible as estimates, but
    # are excluded from purchasing recommendations.
    recommendation_parts = []
    for part in raw_parts:
        recommendation_part = dict(part)
        # Normalize the report contract used by both the original Streamlit
        # analysis ("Supplier Offers", "Lead Time Weeks", etc.) and Next.
        # The saved report may contain either shape depending on when it ran.
        for target, aliases in {
            "mpn": ("mpn", "MPN", "Part Number", "part_number"),
            "manufacturer": ("manufacturer", "Manufacturer"),
            "description": ("description", "Description", "part_description", "product_description"),
            "category": ("category", "Category", "component_type", "part_type", "architecture"),
            "quantity": ("effective_quantity", "Effective Quantity", "quantity", "Quantity", "qty"),
            "lifecycle_status": ("lifecycle_status", "Lifecycle Status", "Lifecycle"),
            "risk_score": ("risk_score", "Risk Score"),
            "supplier_count": ("supplier_count", "Supplier Count", "Supplier Sources"),
            "stock_available": (
                "stock_available", "Stock Available", "Total Market Stock", "stock", "Stock"
            ),
            "unit_price": ("unit_price", "Unit Price", "price"),
            "unit_price_currency": (
                "unit_price_currency", "Unit Price Currency", "currency", "Currency"
            ),
            "lead_time_weeks": (
                "lead_time_weeks", "Lead Time Weeks", "Lead Time (Weeks)", "lead_time"
            ),
            "primary_supplier": (
                "primary_supplier", "best_source", "Best Source", "supplier", "Supplier", "source", "Source"
            ),
            "supplier_offers": ("supplier_offers", "Supplier Offers"),
            "supplier_data_verified": ("supplier_data_verified", "Supplier Data Verified"),
        }.items():
            value = first_value(part, *aliases)
            if value is not None:
                recommendation_part[target] = value
        part_source = str(
            first_value(
                part,
                "evidence_source",
                "evidence_class",
                "price_source",
                "source",
                "Source",
                default="",
            )
            or ""
        ).casefold()
        verification_value = first_value(
            part, "supplier_data_verified", "Supplier Data Verified"
        )
        has_verified_source = (
            verification_value is True
            or str(verification_value or "").strip().casefold()
            in {"1", "true", "yes", "verified"}
        )
        if (
            str(report.get("mode") or "").casefold() == "synthetic-preview"
            or "synthetic" in part_source
            or not has_verified_source
        ):
            recommendation_part["supplier_data_verified"] = False
        recommendation_parts.append(recommendation_part)
    advisor = build_procurement_advisor(
        analyses=[report], parts=recommendation_parts, alerts=[]
    )
    recommendations_by_mpn = {
        str(row.get("Part Number") or "").strip().casefold(): row
        for row in advisor.get("recommendations") or []
        if isinstance(row, dict)
    }

    rows = []
    evidence_counts = {"live": 0, "synthetic": 0, "missing": 0}
    for part in raw_parts:
        mpn = str(first_value(part, "MPN", "mpn", "Part Number", "part_number", default="") or "").strip()
        manufacturer = str(first_value(part, "Manufacturer", "manufacturer", default="") or "").strip()
        supplier = str(
            first_value(
                part,
                "primary_supplier",
                "best_source",
                "Best Source",
                "supplier",
                "source",
                "Source",
                "Supplier",
                default="",
            )
            or ""
        ).strip()
        verified_value = first_value(part, "supplier_data_verified", "Supplier Data Verified")
        raw_evidence_source = str(
            first_value(
                part,
                "evidence_source",
                "evidence_class",
                "price_source",
                "Evidence Source",
                "Price Source",
                default="",
            )
            or ""
        ).strip()
        report_mode = str(report.get("mode") or "").casefold()
        verified = verified_value is True or str(verified_value or "").strip().casefold() in {
            "1", "true", "yes", "verified"
        }
        evidence_tag = raw_evidence_source.casefold()
        if evidence_tag == "missing":
            evidence_source = "missing"
        elif evidence_tag.startswith("live"):
            evidence_source = raw_evidence_source
        elif any(token in evidence_tag for token in ("synthetic", "preview", "offline")):
            evidence_source = "synthetic-preview"
        elif report_mode == "synthetic-preview":
            evidence_source = "synthetic-preview"
        elif report_mode == "legacy-supplier-engine" and verified and supplier:
            evidence_source = "live-authorized-supplier"
        else:
            evidence_source = "missing"
        normalized_evidence_part = {
            **part,
            "MPN": mpn,
            "manufacturer_part_number": first_value(
                part, "manufacturer_part_number", "Manufacturer Part Number", default=mpn
            ),
            "Manufacturer": manufacturer,
            "source": supplier,
            "supplier_data_verified": verified_value,
            "evidence_source": evidence_source,
            "evidence_class": evidence_source,
            "Unit Price": first_value(part, "Unit Price", "unit_price", "price"),
            "unit_price_currency": first_value(
                part,
                "unit_price_currency",
                "Unit Price Currency",
                "currency",
                "Currency",
                default="",
            ),
            "product_url": first_value(
                part, "product_url", "Product URL", "product_detail_url", default=""
            ),
            "datasheet_url": first_value(part, "datasheet_url", "Datasheet URL", default=""),
            "retrieved_at": first_value(
                part,
                "retrieved_at",
                "Sourcing Updated At",
                "sourcing_updated_at",
                "updated_at",
                default="",
            ),
        }
        evidence = classify_part_evidence(normalized_evidence_part)
        evidence_class = str(evidence.get("evidence_class") or "missing")
        if evidence_class == "live-authorized-supplier":
            evidence_counts["live"] += 1
        elif evidence_class == "synthetic-preview":
            evidence_counts["synthetic"] += 1
        else:
            evidence_counts["missing"] += 1

        offers = normalize_supplier_offer_records(part)
        recommendation = recommendations_by_mpn.get(mpn.casefold()) or {}
        has_manual_price = "unit_price" in (part.get("_sourcing_override_fields") or ())
        reported_price = first_value(part, "Unit Price", "unit_price", "price")
        price_source = (
            "user-entered"
            if has_manual_price
            else evidence_class
            if evidence_class in {"live-authorized-supplier", "synthetic-preview"}
            else "not-recorded"
        )
        trusted_saved_values = evidence_class in {
            "live-authorized-supplier",
            "synthetic-preview",
        } or has_manual_price
        saved_stock = first_value(
            part, "stock_available", "Stock Available", "Total Market Stock", "stock", "Stock"
        )
        display_price = recommendation.get("Unit Price")
        if display_price is None and trusted_saved_values:
            display_price = reported_price
        display_stock = recommendation.get("Available Stock")
        if display_stock is None and trusted_saved_values:
            display_stock = saved_stock
        supplier_count = recommendation.get("Supplier Sources")
        if offers:
            coverage = f"{len(offers)} saved offer{'s' if len(offers) != 1 else ''}"
        elif supplier_count is not None:
            coverage = f"{supplier_count} source{'s' if supplier_count != 1 else ''}; no offer details saved"
        elif evidence_class == "live-authorized-supplier":
            coverage = "Live source verified; no offer rows returned"
        else:
            coverage = "No supplier offers recorded"

        rows.append(
            {
                "mpn": mpn,
                "manufacturer": manufacturer,
                "description": first_value(part, "Description", "description", "part_description", default=""),
                "category": first_value(part, "Category", "category", "component_type", "part_type", default=""),
                "image_url": first_value(part, "image_url", "Image URL", "Photo", default=""),
                "product_url": normalized_evidence_part["product_url"],
                "datasheet_url": normalized_evidence_part["datasheet_url"],
                "quantity": recommendation.get("Required Quantity")
                if recommendation.get("Required Quantity") is not None
                else first_value(
                    part,
                    "effective_quantity",
                    "Effective Quantity",
                    "Quantity",
                    "quantity",
                    "qty",
                ),
                "quantity_per_parent": first_value(
                    part,
                    "quantity_per_parent",
                    "Quantity per Parent",
                    "Quantity",
                    "quantity",
                    "qty",
                ),
                "lifecycle": recommendation.get("Lifecycle Status")
                or first_value(part, "Lifecycle", "lifecycle_status", default="Unknown"),
                "risk_level": first_value(part, "Risk Level", "risk_level", default="Needs verification"),
                "risk_score": first_value(part, "Risk Score", "risk_score"),
                "recommendation": recommendation.get("Recommendation") or "Complete sourcing data",
                "next_step": recommendation.get("Next Step")
                or (
                    "Find and verify an authorized distributor source for this MPN before ordering."
                    if evidence_class == "missing"
                    else "Confirm current supplier evidence before ordering."
                ),
                "priority_score": recommendation.get("Priority Score"),
                "evidence_status": recommendation.get("Evidence Status") or "Incomplete",
                "missing_sourcing_data": recommendation.get("Missing Sourcing Data") or "",
                "supplier": supplier,
                "supplier_count": supplier_count,
                "stock": display_stock,
                "unit_price": display_price,
                "currency": recommendation.get("Currency")
                or normalized_evidence_part["unit_price_currency"],
                "lead_time_weeks": recommendation.get("Lead Time (Weeks)"),
                "price_source": price_source,
                "evidence_class": evidence_class,
                "supplier_offers": offers,
                "offer_count": len(offers),
                "coverage": coverage,
                "evidence": evidence,
                "retrieved_at": normalized_evidence_part["retrieved_at"],
                "stock_sources": first_value(part, "stock_data_sources", "Stock Data Sources", default=[]),
            }
        )

    counts = evidence_counts
    total = len(rows)
    configured_sources = 0
    try:
        from apps.api.legacy_supplier_workflow import configured_supplier_count

        configured_sources = configured_supplier_count()
    except Exception:  # noqa: BLE001
        configured_sources = 0

    if counts["live"] and (counts["synthetic"] or counts["missing"]):
        mode = "mixed-evidence"
        gap = "Evidence varies by component. Check each row's source and timestamp before using sourcing values."
    elif counts["live"]:
        mode = "live-source-evidence"
        gap = None
    elif counts["synthetic"]:
        mode = "synthetic-preview"
        gap = (
            "This saved analysis contains sample estimates, not distributor quotes. "
            "No supplier credentials are configured on this API service."
            if configured_sources == 0
            else "This saved analysis contains sample estimates, not distributor quotes. Supplier integrations are configured; run the BOM again to retrieve current supplier evidence."
        )
    elif configured_sources == 0:
        mode = "source-unavailable"
        gap = "No supplier credentials are configured on this API service, so this analysis has no live distributor quotes."
    else:
        mode = "source-check-complete"
        gap = "No verified supplier quotes are saved for this analysis. Supplier integrations are configured; run the BOM again to check current availability and pricing."

    return _json_safe(
        {
            "ok": True,
            "mode": mode,
            "analysis_mode": report.get("mode"),
            "analysis_id": report["id"],
            "filename": report.get("filename"),
            "project_name": report.get("project_name"),
            "bom_name": report.get("bom_name"),
            "revision": report.get("revision"),
            "gap": gap,
            "recommendation_note": advisor.get("summary") or "Review saved sourcing evidence before placing an order.",
            "evidence_summary": {
                "live_parts": counts["live"],
                "sample_parts": counts["synthetic"],
                "parts_without_verified_supplier_evidence": counts["missing"],
                "parts_total": total,
                "configured_supplier_sources": configured_sources,
            },
            "parts": rows,
        }
    )


def design_impact_payload(
    *, workspace_id: str, analysis_id: str | None = None, selected_mpn: str = ""
) -> dict[str, Any]:
    analyses, parts = analyses_and_parts(workspace_id=workspace_id, analysis_id=analysis_id)
    if not analyses:
        return {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": "Analyze a BOM first. Design impact needs at least one saved analysis.",
            "intelligence": {},
        }
    intelligence = build_design_impact(
        analyses,
        parts,
        selected_mpn=selected_mpn,
        select_recommended_when_empty=True,
    )
    return _json_safe(
        {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": "Based on saved analyses in this workspace.",
            "intelligence": intelligence,
        }
    )


def cost_optimization_payload(
    *, workspace_id: str, analysis_id: str | None = None, build_quantity: int = 100
) -> dict[str, Any]:
    analyses, parts = analyses_and_parts(workspace_id=workspace_id, analysis_id=analysis_id)
    if not analyses:
        return {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": "Analyze a BOM first.",
            "optimization": {},
        }
    optimization = build_cost_optimization(
        analyses, parts, build_quantity=max(1, int(build_quantity or 100))
    )
    return _json_safe(
        {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": "Cost figures use synthetic-preview unit prices from analysis. They are not live contract or distributor quotes.",
            "build_quantity": max(1, int(build_quantity or 100)),
            "optimization": optimization,
        }
    )


def supply_risk_payload(
    *,
    workspace_id: str,
    analysis_id: str | None = None,
    build_quantity: int = 100,
    stock_reduction_percent: int = 25,
    supplier_loss: int = 0,
    demand_growth_percent: int = 0,
    include_lifecycle_event: bool = False,
) -> dict[str, Any]:
    analyses, parts = analyses_and_parts(workspace_id=workspace_id, analysis_id=analysis_id)
    if not analyses:
        return {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": "Analyze a BOM first.",
            "scenario": {},
        }
    scenario = build_supply_scenario(
        analyses,
        parts,
        build_quantity=max(1, int(build_quantity or 100)),
        stock_reduction_percent=int(stock_reduction_percent or 0),
        supplier_loss=int(supplier_loss or 0),
        demand_growth_percent=int(demand_growth_percent or 0),
        include_lifecycle_event=bool(include_lifecycle_event),
    )
    return _json_safe(
        {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": "Scenario uses synthetic stock/lifecycle fields from analysis. It does not pull live supplier inventory.",
            "parameters": {
                "build_quantity": max(1, int(build_quantity or 100)),
                "stock_reduction_percent": int(stock_reduction_percent or 0),
                "supplier_loss": int(supplier_loss or 0),
                "demand_growth_percent": int(demand_growth_percent or 0),
                "include_lifecycle_event": bool(include_lifecycle_event),
            },
            "scenario": scenario,
        }
    )


def portfolio_payload(*, workspace_id: str) -> dict[str, Any]:
    analyses, parts = analyses_and_parts(workspace_id=workspace_id)
    monitoring = monitoring_payload(workspace_id=workspace_id)
    alerts = monitoring.get("alerts") or []
    if not analyses:
        return {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": "No saved analyses yet. Analyze a BOM first.",
            "intelligence": {},
            "reports": [],
        }
    intelligence = build_portfolio_intelligence(analyses, parts, alerts)
    return _json_safe(
        {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": "Based on saved analyses in this workspace.",
            "reports": list_reports(workspace_id=workspace_id),
            "intelligence": intelligence,
        }
    )


def detailed_risk_payload(*, workspace_id: str, analysis_id: str | None = None) -> dict[str, Any]:
    report = _require_analysis(analysis_id, workspace_id=workspace_id)
    if not report:
        return {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": "Analyze a BOM first.",
            "rows": [],
            "summary": {},
        }
    rows = component_rows(report.get("parts") or [])
    summary = report_exposure_summary(rows)
    high_risk_count = int(report.get("high_risk_count") or 0)
    if not high_risk_count:
        high_risk_count = int(summary.get("high_risk_component_count") or 0)
    return _json_safe(
        {
            "ok": True,
            "mode": "synthetic-preview",
            "analysis_id": report["id"],
            "filename": report.get("filename"),
            "health_score": report.get("health_score"),
            "health_status": report.get("health_status"),
            "high_risk_count": high_risk_count,
            "gap": "Detailed risk rows come from the synthetic analysis. Extended costs use synthetic-preview unit prices when present.",
            "rows": rows,
            "summary": summary,
        }
    )


def with_evidence_labels(report: dict[str, Any] | None) -> dict[str, Any]:
    """Attach live/synthetic evidence envelopes to a saved report payload."""
    if not report:
        return {"ok": False, "detail": "Report not found"}
    annotated = annotate_report_parts(report)
    annotated["ok"] = True
    annotated["mode"] = annotated.get("mode") or "synthetic-preview"
    return _json_safe(annotated)


def decorate_parts_with_evidence(parts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out = []
    for part in parts or []:
        row = dict(part) if isinstance(part, dict) else {"value": part}
        row["evidence"] = classify_part_evidence(row)
        # Attach mocked authorized lookup metadata without claiming live evidence.
        mpn = str(row.get("MPN") or row.get("manufacturer_part_number") or "")
        if mpn:
            lookup = lookup_exact_part(mpn)
            row["authorized_lookup"] = {
                "evidence_class": lookup.get("evidence_class"),
                "synthetic": lookup.get("synthetic"),
                "source_url": (lookup.get("match") or {}).get("source_url") or "",
                "retrieved_at": (lookup.get("match") or {}).get("retrieved_at") or "",
                "live_lookups_enabled": lookup.get("live_lookups_enabled"),
                "gap": lookup.get("gap"),
            }
        out.append(row)
    return out

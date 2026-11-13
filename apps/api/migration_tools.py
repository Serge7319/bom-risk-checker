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
from src.datasheet_comparison import verify_datasheet_identity
from src.design_impact_analyzer import build_design_impact
from apps.api.evidence_contract import (
    annotate_report_parts,
    classify_part_evidence,
    evidence_mode_and_gap,
)
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


MONITORING_STALE_AFTER_HOURS = 24


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _part_mpn(part: dict[str, Any]) -> str:
    return str(part.get("MPN") or part.get("mpn") or "").strip()


def _derive_monitoring_alerts(
    report: dict[str, Any],
    *,
    workspace_id: str,
    part_number: str | None = None,
) -> list[dict[str, Any]]:
    """Pure derivation of alert rows from a saved analysis (no store access)."""
    alerts: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    wanted = str(part_number or "").strip().casefold()
    for part in report.get("parts") or []:
        if not isinstance(part, dict):
            continue
        mpn = _part_mpn(part)
        if not mpn:
            continue
        if wanted and mpn.casefold() != wanted:
            continue
        lifecycle = str(part.get("Lifecycle") or part.get("lifecycle_status") or "")
        risk = str(part.get("Risk Level") or part.get("risk_level") or "")
        evidence_source = _monitoring_evidence_source(part, report)
        evidence_phrase = _monitoring_evidence_phrase(evidence_source)
        reasons = part.get("Risk Reasons") or part.get("risk_reasons") or "see report"
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
        if risk.lower() in {"high", "medium"}:
            level = "High" if risk.lower() == "high" else "Medium"
            alerts.append(
                {
                    **build_alert_record(
                        "smoke-user",
                        report["id"],
                        mpn,
                        "Risk Signal",
                        f"{level} risk in latest analysis: {reasons}",
                        level,
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
    return alerts


def _alert_key(alert: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(alert.get("analysis_id") or "").strip(),
        str(alert.get("part_number") or "").strip().casefold(),
        str(alert.get("alert_type") or "").strip(),
    )


def _part_data_status(part: dict[str, Any]) -> dict[str, Any]:
    """Per-part freshness / provider-failure view from saved analysis only."""
    health = part.get("provider_health") if isinstance(part.get("provider_health"), dict) else {}
    failed_sources = [str(s) for s in (health.get("failed_sources") or []) if str(s).strip()]
    verified_flag = part.get("supplier_data_verified")
    if verified_flag is None:
        raw = str(part.get("Supplier Data Verified") or "").strip().casefold()
        verified_flag = True if raw in {"1", "true", "yes", "verified"} else (
            False if raw in {"0", "false", "no", "unverified"} else None
        )
    has_verified = health.get("has_verified_data")
    provider_failure = bool(failed_sources) or (
        has_verified is False or (has_verified is None and verified_flag is False)
    )
    if provider_failure:
        message = str(
            health.get("summary_message")
            or "Supplier data could not be verified during this analysis."
        )
    elif verified_flag is True or has_verified is True:
        message = ""
    else:
        message = "No live supplier verification is recorded for this part."
    return {
        "part_number": _part_mpn(part),
        "provider_failure": provider_failure,
        "failed_sources": failed_sources,
        "data_verified": bool(verified_flag is True or has_verified is True) and not failed_sources,
        "data_message": message,
        "last_checked": str(
            part.get("Last Checked")
            or part.get("last_checked")
            or part.get("retrieved_at")
            or ""
        ),
    }


def _monitoring_freshness(
    report: dict[str, Any], refresh_history: list[dict[str, Any]]
) -> dict[str, Any]:
    analysis_id = str(report.get("id") or "")
    latest = next(
        (
            row
            for row in refresh_history
            if str(row.get("analysis_id") or "") in {analysis_id, ""}
            or str(row.get("scope") or "") == "portfolio"
        ),
        None,
    )
    last_refresh_at = str((latest or {}).get("ran_at") or "")
    refreshed = _parse_iso(last_refresh_at)
    saved = _parse_iso(report.get("created_at"))
    now = datetime.now(timezone.utc)
    if refreshed is None:
        stale, reason = True, "never_refreshed"
    elif (now - refreshed).total_seconds() > MONITORING_STALE_AFTER_HOURS * 3600:
        stale, reason = True, "refresh_older_than_threshold"
    elif saved is not None and saved > refreshed:
        stale, reason = True, "analysis_newer_than_refresh"
    else:
        stale, reason = False, "fresh"
    return {
        "last_refresh_at": last_refresh_at or None,
        "never_refreshed": refreshed is None,
        "stale": stale,
        "stale_reason": reason,
        "stale_after_hours": MONITORING_STALE_AFTER_HOURS,
        "analysis_saved_at": report.get("created_at"),
        "live_supplier_refresh": False,
    }


def _empty_monitoring_payload() -> dict[str, Any]:
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


def monitoring_payload(
    *, workspace_id: str, analysis_id: str | None = None
) -> dict[str, Any]:
    """READ-ONLY monitoring view.

    Loads persisted alerts / refresh history and derives the view from the saved
    analysis in memory. Never calls ``persist_alerts`` or ``record_refresh`` —
    use :func:`monitoring_refresh_payload` for an explicit refresh.
    """
    report = _require_analysis(analysis_id, workspace_id=workspace_id)
    if not report:
        return _empty_monitoring_payload()

    report_mode = str(report.get("mode") or "synthetic-preview")
    report_id = str(report["id"])
    derived = _derive_monitoring_alerts(report, workspace_id=workspace_id)
    persisted = [
        a
        for a in monitoring_store.list_alerts(workspace_id, analysis_id=report_id)
        if str(a.get("analysis_id") or "").strip() == report_id
        and a.get("active") is not False
        and str(a.get("status") or "active").lower() != "inactive"
    ]
    persisted_by_key = {_alert_key(a): a for a in persisted}
    scoped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for alert in derived:
        key = _alert_key(alert)
        seen.add(key)
        saved = persisted_by_key.get(key)
        if saved:
            scoped.append({**alert, **saved, "persisted": True, "active": True})
        else:
            scoped.append({**alert, "persisted": False, "active": True})
    # Stale persisted alerts that no longer derive from the analysis are not
    # shown as active. They remain in storage as inactive until the next refresh
    # reconciles them.

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
    history = monitoring_store.list_refresh_history(workspace_id)
    scoped_history = [
        row
        for row in history
        if str(row.get("analysis_id") or "") in {report_id, ""}
        or str(row.get("scope") or "") == "portfolio"
    ]
    freshness = _monitoring_freshness(report, scoped_history)
    part_status = [
        _part_data_status(p) for p in report.get("parts") or [] if isinstance(p, dict) and _part_mpn(p)
    ]
    prefs = monitoring_store.get_preferences(workspace_id)
    return _json_safe(
        {
            "ok": True,
            "read_only": True,
            "mode": report_mode,
            "analysis_id": report_id,
            "filename": report.get("filename"),
            "gap": (
                "Monitoring is read-only on this view: it shows current signals from the saved "
                "analysis and active persisted alerts. Use Refresh to re-derive and save alerts "
                "(refresh never sends email). Email requires the separate Notify action when "
                "delivery is enabled. Scheduled supplier refresh remains disabled."
            ),
            "metrics": {
                "monitored_parts": report.get("total_parts") or 0,
                "active_alerts": len(scoped),
                "high_priority": high,
                "lifecycle_changes": lifecycle_n,
                "provider_failures": sum(1 for s in part_status if s["provider_failure"]),
                "unpersisted_alerts": sum(1 for a in scoped if not a.get("persisted")),
            },
            "alerts": scoped,
            "action_center": action_center,
            "preferences": prefs,
            "freshness": freshness,
            "refresh": scoped_history[0] if scoped_history else None,
            "refresh_history": scoped_history[:10],
            "part_status": part_status,
        }
    )


def monitoring_refresh_payload(
    *,
    workspace_id: str,
    analysis_id: str | None = None,
    part_number: str | None = None,
    portfolio: bool = False,
) -> dict[str, Any]:
    """EXPLICIT refresh: re-derive alerts from saved analysis, persist, record.

    Scope is always labeled in the response:
    - ``part``: one MPN within ``analysis_id``
    - ``analysis``: all parts in ``analysis_id``
    - ``portfolio``: every saved analysis in the workspace (only when
      ``portfolio=True``; never inferred from a missing ``analysis_id``)
    Does not call live suppliers and does not send email.
    """
    if portfolio:
        if analysis_id or part_number:
            raise ValueError("portfolio refresh cannot be combined with analysis_id/part_number")
        summaries = list_reports(workspace_id=workspace_id)
        reports = [
            r
            for r in (
                get_report(str(s.get("id") or s.get("analysis_id")), workspace_id=workspace_id)
                for s in summaries
            )
            if r
        ]
        alerts: list[dict[str, Any]] = []
        for report in reports:
            alerts.extend(_derive_monitoring_alerts(report, workspace_id=workspace_id))
        durable = monitoring_store.persist_alerts(workspace_id, alerts) if alerts else []
        refresh = monitoring_store.record_refresh(
            workspace_id,
            analysis_id=None,
            alert_count=len(durable),
            mode="portfolio",
            scope="portfolio",
        )
        return _json_safe(
            {
                "ok": True,
                "scope": "portfolio",
                "scope_label": f"Portfolio-wide refresh across {len(reports)} saved analyses",
                "analysis_ids": [str(r["id"]) for r in reports],
                "alert_count": len(durable),
                "alerts": durable,
                "refresh": refresh,
                "live_supplier_refresh": False,
            }
        )

    if not str(analysis_id or "").strip():
        raise ValueError("analysis_id is required (or request an explicit portfolio refresh)")
    report = _require_analysis(analysis_id, workspace_id=workspace_id)
    if not report:
        raise ValueError("analysis not found")
    part = str(part_number or "").strip() or None
    if part and not any(
        _part_mpn(p).casefold() == part.casefold()
        for p in report.get("parts") or []
        if isinstance(p, dict)
    ):
        raise ValueError("part not found in selected analysis")
    alerts = _derive_monitoring_alerts(report, workspace_id=workspace_id, part_number=part)
    report_id = str(report["id"])
    scoped = monitoring_store.reconcile_alerts(
        workspace_id,
        analysis_id=report_id,
        active_alerts=alerts,
        part_number=part,
    )
    scope = "part" if part else "analysis"
    refresh = monitoring_store.record_refresh(
        workspace_id,
        analysis_id=report_id,
        alert_count=len(scoped),
        mode=str(report.get("mode") or "synthetic-preview"),
        scope=scope,
        part_number=part,
    )
    return _json_safe(
        {
            "ok": True,
            "scope": scope,
            "scope_label": (
                f"Part {part} in analysis {report_id}" if part else f"Analysis {report_id}"
            ),
            "analysis_id": report_id,
            "part_number": part,
            "alert_count": len(scoped),
            "alerts": scoped,
            "refresh": refresh,
            "live_supplier_refresh": False,
            "email_sent": False,
        }
    )


def compare_parts_payload(
    *,
    workspace_id: str,
    part_a: str,
    part_b: str,
    analysis_id: str | None = None,
    manufacturer_a: str | None = None,
    manufacturer_b: str | None = None,
    use_latest_if_missing: bool = True,
    datasheet_uploads: dict[str, Any] | None = None,
) -> dict[str, Any]:
    a = str(part_a or "").strip()
    b = str(part_b or "").strip()
    mfr_a = str(manufacturer_a or "").strip()
    mfr_b = str(manufacturer_b or "").strip()
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
            manufacturer_a=mfr_a,
            manufacturer_b=mfr_b,
            datasheet_uploads=datasheet_uploads,
            extract_linked_datasheets=True,
        )
    if datasheet_uploads:
        return _uploaded_compare_parts_payload(
            workspace_id=workspace_id,
            part_a=a,
            part_b=b,
            analysis_id=analysis_id,
            manufacturer_a=mfr_a,
            manufacturer_b=mfr_b,
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

    from src.parts_compare import _verify_compare_lookup_identity

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
    data_a = _verify_compare_lookup_identity(
        a, data_a, requested_manufacturer=mfr_a
    )
    data_b = _verify_compare_lookup_identity(
        b, data_b, requested_manufacturer=mfr_b
    )
    identity_blocked = any(
        str(side.get("identity_status") or "") in {"unresolved", "ambiguous"}
        for side in (data_a, data_b)
    )

    comparison = build_parts_comparison(
        data_a,
        data_b,
        part_a_mpn=a,
        part_b_mpn=b,
        extract_linked_datasheets=False,
    )
    if identity_blocked:
        comparison["finding"] = "Needs verification"
        comparison["rows"] = []
        comparison["engineering_evidence_status"] = "incomplete"
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

    if identity_blocked:
        finding = "Needs verification"
        rows = []
        gap = str(
            data_a.get("identity_gap")
            or data_b.get("identity_gap")
            or gap
            or "Manufacturer identity could not be verified for this comparison."
        )

    return _json_safe(
        {
            "ok": True,
            "status": STATUS_COMPLETED,
            "mode": "synthetic-preview",
            "analysis_id": analysis_context,
            "part_a": a,
            "part_b": b,
            "manufacturer_a": mfr_a,
            "manufacturer_b": mfr_b,
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
    manufacturer_a: str = "",
    manufacturer_b: str = "",
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
    if engine_result.get("identity_blocked"):
        finding = "Needs verification"
    mfr_a = str(manufacturer_a or engine_result.get("manufacturer_a") or "").strip()
    mfr_b = str(manufacturer_b or engine_result.get("manufacturer_b") or "").strip()
    return _json_safe({
        "ok": True,
        "status": STATUS_COMPLETED,
        "mode": mode,
        "analysis_id": analysis_id,
        "workspace_id": workspace_id,
        "part_a": part_a,
        "part_b": part_b,
        "manufacturer_a": mfr_a,
        "manufacturer_b": mfr_b,
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
    manufacturer_a: str = "",
    manufacturer_b: str = "",
) -> dict[str, Any]:
    from src.parts_compare import run_compare_parts

    report = _require_analysis(analysis_id, workspace_id=workspace_id) if analysis_id else None
    result = run_compare_parts(
        part_a,
        part_b,
        manufacturer_a=manufacturer_a,
        manufacturer_b=manufacturer_b,
        datasheet_uploads=datasheet_uploads,
        extract_linked_datasheets=extract_linked_datasheets,
    )
    payload = _comparison_payload_from_engine(
        workspace_id=workspace_id,
        part_a=part_a,
        part_b=part_b,
        analysis_id=str((report or {}).get("id") or "") or None,
        engine_result=result,
        mode="legacy-supplier-engine",
        upload_a=bool((datasheet_uploads or {}).get("a")),
        upload_b=bool((datasheet_uploads or {}).get("b")),
        manufacturer_a=manufacturer_a,
        manufacturer_b=manufacturer_b,
    )
    return payload


def _uploaded_compare_parts_payload(
    *,
    workspace_id: str,
    part_a: str,
    part_b: str,
    analysis_id: str | None,
    datasheet_uploads: dict[str, Any],
    manufacturer_a: str = "",
    manufacturer_b: str = "",
) -> dict[str, Any]:
    from src.parts_compare import (
        build_parts_comparison,
        _datasheet_from_upload_payload,
        _identity_blocks_compare,
        _verify_compare_lookup_identity,
    )

    report = _require_analysis(analysis_id, workspace_id=workspace_id) if analysis_id else None
    from_report: dict[str, dict[str, Any]] = {}
    if report:
        for part in report.get("parts") or []:
            key = str(part.get("MPN") or "").strip().casefold()
            if key:
                from_report[key] = part

    data_a = _verify_compare_lookup_identity(
        part_a,
        synthetic_compare_part(part_a, from_report=from_report.get(part_a.casefold())),
        requested_manufacturer=manufacturer_a,
    )
    data_b = _verify_compare_lookup_identity(
        part_b,
        synthetic_compare_part(part_b, from_report=from_report.get(part_b.casefold())),
        requested_manufacturer=manufacturer_b,
    )
    doc_a = _datasheet_from_upload_payload(
        datasheet_uploads.get("a"),
        manufacturer=str(data_a.get("manufacturer") or manufacturer_a or ""),
        mpn=part_a,
    ) if datasheet_uploads.get("a") else None
    doc_b = _datasheet_from_upload_payload(
        datasheet_uploads.get("b"),
        manufacturer=str(data_b.get("manufacturer") or manufacturer_b or ""),
        mpn=part_b,
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
    identity_blocked = _identity_blocks_compare(data_a) or _identity_blocks_compare(
        data_b
    )
    if identity_blocked:
        comparison["finding"] = "Needs verification"
        comparison["rows"] = []
        comparison["engineering_evidence_status"] = "incomplete"
    result = {
        "comparison": comparison,
        "error": (
            str(data_a.get("identity_gap") or data_b.get("identity_gap") or "")
            if identity_blocked
            else ""
        ),
        "identity_blocked": identity_blocked,
    }
    return _comparison_payload_from_engine(
        workspace_id=workspace_id,
        part_a=part_a,
        part_b=part_b,
        analysis_id=str((report or {}).get("id") or "") or None,
        engine_result=result,
        mode="uploaded-datasheet-review",
        upload_a=bool(doc_a),
        upload_b=bool(doc_b),
        manufacturer_a=manufacturer_a,
        manufacturer_b=manufacturer_b,
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

    from apps.api.manufacturer_identity import (
        identity_ambiguity_payload,
        manufacturers_match,
        multi_brand_choices_for_mpn,
        select_manufacturer_choice,
    )

    requested_manufacturer = str(manufacturer or "").strip()
    dual_source_choices = multi_brand_choices_for_mpn(requested)
    # Multi-brand MPNs with registered official evidence require an explicit manufacturer.
    if dual_source_choices and not requested_manufacturer:
        return _json_safe(
            {
                **identity_ambiguity_payload(
                    mpn=requested,
                    requested_manufacturer="",
                    choices=dual_source_choices,
                ),
                "analysis_id": context_analysis_id,
                "bom_context": bom_context,
                "context_unavailable": context_notice,
            }
        )
    if dual_source_choices and requested_manufacturer:
        selected = select_manufacturer_choice(
            requested, requested_manufacturer, choices=dual_source_choices
        )
        if selected is None:
            return _json_safe(
                {
                    **identity_ambiguity_payload(
                        mpn=requested,
                        requested_manufacturer=requested_manufacturer,
                        choices=dual_source_choices,
                    ),
                    "analysis_id": context_analysis_id,
                    "bom_context": bom_context,
                    "context_unavailable": context_notice,
                }
            )

    if production_analysis_enabled():
        result = find_replacements(requested, manufacturer=requested_manufacturer)
        original = result.get("original") if isinstance(result.get("original"), dict) else {}
        resolved_mfr = str(
            original.get("manufacturer")
            or original.get("Manufacturer")
            or ""
        ).strip()
        identity_status = str(original.get("identity_status") or "").strip()
        identity_review_only = bool(
            (result.get("identity_review_only") or original.get("identity_review_only"))
            and requested_manufacturer
            and identity_status == "unresolved"
            and not resolved_mfr
            and not original.get("identity_verified")
        )
        if identity_status == "ambiguous" or (
            requested_manufacturer
            and not identity_review_only
            and (
                identity_status in {"manufacturer_mismatch", "unresolved"}
                or (
                    resolved_mfr
                    and not manufacturers_match(
                        requested_manufacturer, resolved_mfr, mpn=requested
                    )
                )
                or not resolved_mfr
            )
        ):
            choices = dual_source_choices or original.get("identity_choices") or None
            return _json_safe(
                {
                    **identity_ambiguity_payload(
                        mpn=requested,
                        requested_manufacturer=requested_manufacturer,
                        resolved_manufacturer=resolved_mfr
                        or str(original.get("resolved_manufacturer") or ""),
                        choices=choices if isinstance(choices, list) else None,
                    ),
                    "analysis_id": context_analysis_id,
                    "bom_context": bom_context,
                    "context_unavailable": context_notice,
                }
            )
        from src.alternative_finder_state import (
            OUTCOME_CATALOG_LEADS_ONLY,
            OUTCOME_FAILURE,
            OUTCOME_NO_RESULTS,
            OUTCOME_PARTIAL_SUPPLIER,
            search_outcome_label,
        )

        raw_outcome = str(result.get("search_outcome") or "").strip()
        review_lead_count = sum(
            len(result.get(key) or [])
            for key in ("candidates", "unclassified_leads", "unfiltered_leads")
        )
        if identity_review_only:
            if raw_outcome == OUTCOME_PARTIAL_SUPPLIER:
                outcome = raw_outcome
            elif review_lead_count:
                outcome = OUTCOME_CATALOG_LEADS_ONLY
            elif raw_outcome == OUTCOME_FAILURE:
                outcome = OUTCOME_FAILURE
            else:
                outcome = "unable_to_confirm"
        elif result.get("candidates"):
            outcome = "candidates_found"
        elif raw_outcome in {
            OUTCOME_CATALOG_LEADS_ONLY,
            OUTCOME_PARTIAL_SUPPLIER,
            OUTCOME_NO_RESULTS,
        }:
            outcome = raw_outcome
        elif raw_outcome == OUTCOME_FAILURE:
            outcome = "unable_to_confirm"
        else:
            outcome = raw_outcome or "unable_to_confirm"
        final_search_outcome = outcome if identity_review_only else (raw_outcome or outcome)
        review_detail = (
            f"No supplier record verified {requested_manufacturer} as the manufacturer of {requested}. "
            "Any catalog rows below are discovery leads only; confirm the source part against an authorized "
            "source before evaluating a replacement."
            if identity_review_only
            else ""
        )
        return _json_safe({
            "ok": True,
            **result,
            "outcome": outcome,
            "search_outcome": final_search_outcome,
            "search_outcome_label": search_outcome_label(
                final_search_outcome,
                candidates=[]
                if identity_review_only
                else list(result.get("candidates") or []),
            ),
            "identity_status": original.get("identity_status") or "resolved",
            "identity_review_only": identity_review_only,
            "identity_choices": list(original.get("identity_choices") or []),
            "identity_verified": bool(original.get("identity_verified")),
            "requested_manufacturer": requested_manufacturer,
            "detail": review_detail or str(result.get("gap") or ""),
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
    resolved_mfr = str(original.get("manufacturer") or "").strip()
    if requested_manufacturer and resolved_mfr and not manufacturers_match(
        requested_manufacturer, resolved_mfr, mpn=requested
    ):
        return _json_safe(
            {
                **identity_ambiguity_payload(
                    mpn=requested,
                    requested_manufacturer=requested_manufacturer,
                    resolved_manufacturer=resolved_mfr,
                    choices=dual_source_choices or None,
                ),
                "analysis_id": context_analysis_id,
                "bom_context": bom_context,
                "context_unavailable": context_notice,
            }
        )
    if requested_manufacturer and not resolved_mfr:
        # Offline path cannot verify brand — fail closed rather than stamp selection.
        return _json_safe(
            {
                **identity_ambiguity_payload(
                    mpn=requested,
                    requested_manufacturer=requested_manufacturer,
                    resolved_manufacturer="",
                    choices=dual_source_choices or None,
                ),
                "analysis_id": context_analysis_id,
                "bom_context": bom_context,
                "context_unavailable": context_notice,
            }
        )
    if requested_manufacturer and resolved_mfr:
        original["identity_status"] = "matched"
        original["requested_manufacturer"] = requested_manufacturer

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

    # Always surface per-provider outcomes, even in synthetic preview when live
    # credentials are absent. Counts stay provider-local (not the combined lead total).
    offline_count = len(candidates)
    provider_state = {
        "lookup": "not_configured",
        "catalog": "not_configured",
        "substitutions": "not_configured",
        "family_search": "not_configured",
        "parametric_search": "not_configured",
        "explicit_count": 0,
        "catalog_count": 0,
        "message": "Supplier credentials are not configured on this API service.",
    }
    discovery = {
        "original_mpn": requested,
        "providers": {
            "DigiKey": dict(provider_state),
            "Mouser": dict(provider_state),
            "Newark": dict(provider_state),
            "Offline catalog": {
                "lookup": "searched",
                "catalog": "ok" if offline_count else "no_results",
                "substitutions": "not_requested",
                "family_search": "not_requested",
                "parametric_search": "not_requested",
                "explicit_count": 0,
                "catalog_count": offline_count,
                "message": (
                    f"Offline reference catalog returned {offline_count} lead(s)."
                    if offline_count
                    else "Offline reference catalog returned no leads for this MPN."
                ),
            },
        },
        "provider_failures": [],
        "has_incomplete_evidence": True,
        "explicit_count": 0,
        "catalog_count": offline_count,
    }

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
            "discovery": discovery,
            "provider_failures": [],
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
    requested_mpn: str = "",
    manufacturer: str = "",
) -> dict[str, Any]:
    document = extract_uploaded_datasheet(payload, filename=filename or "datasheet.pdf")
    mpn = str(requested_mpn or "").strip()
    mfr = str(manufacturer or "").strip()
    identity: dict[str, Any] | None = None
    if mpn and document.get("available"):
        # Bind the PDF to the selected part only when its text names the exact
        # MPN. An unverified PDF keeps the requested MPN on the document so the
        # answer layer abstains with "Needs verification." rather than citing it.
        identity = verify_datasheet_identity(document, manufacturer=mfr, mpn=mpn)
        document["requested_mpn"] = mpn
        document["identity"] = identity
        if mfr:
            document["manufacturer"] = mfr
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
                "requested_mpn": mpn or None,
                "manufacturer": mfr or None,
                "bound": bool(identity and identity.get("mpn_verified")),
                "identity": identity,
            },
            "question": question,
            "answer_kind": result.get("answer_kind") or "",
            "source_document": result.get("source_document") or {},
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
        fields = evidence.get("fields") if isinstance(evidence.get("fields"), dict) else {}
        price_field = fields.get("price") if isinstance(fields.get("price"), dict) else {}
        lifecycle_field = fields.get("lifecycle") if isinstance(fields.get("lifecycle"), dict) else {}
        stock_field = fields.get("stock") if isinstance(fields.get("stock"), dict) else {}
        identity_field = fields.get("identity") if isinstance(fields.get("identity"), dict) else {}
        price_class = str(price_field.get("evidence_class") or "").strip() or "missing"
        price_source = (
            "user-entered"
            if has_manual_price
            else price_class
            if price_class in {"live-authorized-supplier", "synthetic-preview"}
            else "not-recorded"
        )
        # Trust saved commercial values only when that field's own class allows it.
        trusted_price = has_manual_price or price_class in {
            "live-authorized-supplier",
            "synthetic-preview",
        }
        trusted_stock = str(stock_field.get("evidence_class") or evidence_class) in {
            "live-authorized-supplier",
            "synthetic-preview",
        }
        saved_stock = first_value(
            part, "stock_available", "Stock Available", "Total Market Stock", "stock", "Stock"
        )
        display_price = recommendation.get("Unit Price")
        if display_price is None and trusted_price:
            display_price = reported_price
        if display_price is None and not trusted_price:
            display_price = None
        display_stock = recommendation.get("Available Stock")
        if display_stock is None and trusted_stock:
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

        default_recommendation = (
            "Check an authorized source"
            if evidence_class == "missing" or price_class == "missing"
            else "Confirm current supplier evidence"
        )
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
                "recommendation": (
                    "Check an authorized source"
                    if str(recommendation.get("Recommendation") or "") == "Complete sourcing data"
                    else (recommendation.get("Recommendation") or default_recommendation)
                ),
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
                "price_type": price_field.get("price_type") or "not-recorded",
                "price_retrieved_at": price_field.get("retrieved_at") or "",
                "identity_source": identity_field.get("source") or evidence.get("source") or "",
                "identity_retrieved_at": identity_field.get("retrieved_at")
                or evidence.get("retrieved_at")
                or "",
                "lifecycle_source": lifecycle_field.get("source") or "",
                "lifecycle_retrieved_at": lifecycle_field.get("retrieved_at") or "",
                "stock_source": stock_field.get("source") or "",
                "stock_retrieved_at": stock_field.get("retrieved_at") or "",
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

    mode, gap = evidence_mode_and_gap(
        live_count=counts["live"],
        synthetic_count=counts["synthetic"],
        missing_count=counts["missing"],
        configured_sources=configured_sources,
        analysis_mode=str(report.get("mode") or ""),
    )

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
                "live_price_parts": sum(
                    1 for row in rows if str(row.get("price_source") or "") == "live-authorized-supplier"
                ),
                "synthetic_price_parts": sum(
                    1 for row in rows if str(row.get("price_source") or "") == "synthetic-preview"
                ),
                "missing_price_parts": sum(1 for row in rows if row.get("unit_price") is None),
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
    annotated = annotate_report_parts({"parts": list(parts or []), "mode": (analyses[0] or {}).get("mode")})
    summary = annotated.get("evidence_summary") or {}
    configured_sources = 0
    try:
        from apps.api.legacy_supplier_workflow import configured_supplier_count

        configured_sources = configured_supplier_count()
    except Exception:  # noqa: BLE001
        configured_sources = 0
    mode, gap = evidence_mode_and_gap(
        live_count=int(summary.get("live_count") or 0),
        synthetic_count=int(summary.get("synthetic_count") or 0),
        missing_count=int(summary.get("missing_count") or 0),
        configured_sources=configured_sources,
        analysis_mode=str((analyses[0] or {}).get("mode") or ""),
    )
    missing_prices = int(summary.get("missing_price_count") or 0)
    if missing_prices and not gap:
        gap = (
            f"{missing_prices} component(s) have no recorded unit price. "
            "Cost opportunities only use parts with saved prices; absent prices stay blank."
        )
    elif missing_prices and gap:
        gap = (
            f"{gap} {missing_prices} component(s) have no recorded unit price and are excluded from priced opportunities."
        )
    selected = analyses[0] if analyses else {}
    return _json_safe(
        {
            "ok": True,
            "mode": mode,
            "gap": gap,
            "analysis_id": selected.get("id") or analysis_id,
            "filename": selected.get("filename"),
            "project_name": selected.get("project_name"),
            "bom_name": selected.get("bom_name"),
            "revision": selected.get("revision"),
            "build_quantity": max(1, int(build_quantity or 100)),
            "evidence_summary": summary,
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
    requested_analysis_id = str(analysis_id or "").strip() or None
    analyses, parts = analyses_and_parts(
        workspace_id=workspace_id, analysis_id=requested_analysis_id
    )
    if not analyses:
        return {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": "Analyze a BOM first.",
            "scope": "empty",
            "analysis_id": requested_analysis_id,
            "scenario": {},
        }
    scoped = bool(requested_analysis_id)
    # Defensive: when an analysis_id was requested, never silently widen to the
    # whole workspace even if the store returns extra rows.
    if scoped:
        analyses = [
            row
            for row in analyses
            if str(row.get("id") or "").strip() == requested_analysis_id
        ]
        parts = [
            row
            for row in parts
            if str(row.get("analysis_id") or "").strip() == requested_analysis_id
        ]
    source_part_count = len(parts)
    scenario = build_supply_scenario(
        analyses,
        parts,
        build_quantity=max(1, int(build_quantity or 100)),
        stock_reduction_percent=int(stock_reduction_percent or 0),
        supplier_loss=int(supplier_loss or 0),
        demand_growth_percent=int(demand_growth_percent or 0),
        include_lifecycle_event=bool(include_lifecycle_event),
    )
    analysis_label = ""
    if scoped and analyses:
        analysis_label = str(
            analyses[0].get("project_name")
            or analyses[0].get("name")
            or analyses[0].get("filename")
            or requested_analysis_id
        )
    if scoped:
        gap = (
            f"Scenario scoped to analysis {analysis_label or requested_analysis_id} "
            f"({source_part_count} BOM part records). Uses synthetic stock/lifecycle "
            "fields from that analysis — not live supplier inventory."
        )
        scope = "analysis"
    else:
        gap = (
            f"Portfolio-wide scenario across {len(analyses)} saved analyses "
            f"({source_part_count} BOM part records). Uses synthetic stock/lifecycle "
            "fields — not live supplier inventory."
        )
        scope = "portfolio"
    return _json_safe(
        {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": gap,
            "scope": scope,
            "analysis_id": requested_analysis_id if scoped else None,
            "analysis_label": analysis_label or None,
            "source_part_count": source_part_count,
            "analysis_count": len(analyses),
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
    annotated = annotate_report_parts(report)
    rows = component_rows(annotated.get("parts") or [])
    summary = report_exposure_summary(rows)
    high_risk_count = int(report.get("high_risk_count") or 0)
    if not high_risk_count:
        high_risk_count = int(summary.get("high_risk_component_count") or 0)
    evidence_summary = annotated.get("evidence_summary") or {}
    configured_sources = 0
    try:
        from apps.api.legacy_supplier_workflow import configured_supplier_count

        configured_sources = configured_supplier_count()
    except Exception:  # noqa: BLE001
        configured_sources = 0
    mode, gap = evidence_mode_and_gap(
        live_count=int(evidence_summary.get("live_count") or 0),
        synthetic_count=int(evidence_summary.get("synthetic_count") or 0),
        missing_count=int(evidence_summary.get("missing_count") or 0),
        configured_sources=configured_sources,
        analysis_mode=str(report.get("mode") or ""),
    )
    return _json_safe(
        {
            "ok": True,
            "mode": mode,
            "analysis_id": report["id"],
            "filename": report.get("filename"),
            "project_name": report.get("project_name"),
            "bom_name": report.get("bom_name"),
            "revision": report.get("revision"),
            "health_score": report.get("health_score"),
            "health_status": report.get("health_status"),
            "high_risk_count": high_risk_count,
            "gap": gap,
            "evidence_summary": evidence_summary,
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

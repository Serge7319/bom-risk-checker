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
    analyses_and_parts as _stored_analyses_and_parts,
    get_report as _stored_get_report,
    list_reports as _stored_list_reports,
    synthetic_compare_part,
)
from apps.api.report_visibility import (
    customer_visible_analyses,
    is_internal_test_fixture_analysis,
)
from apps.api.sandbox_auth import is_production_runtime
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
from apps.api.workspace_store import get_store
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


def get_report(analysis_id: str, *, workspace_id: str) -> dict[str, Any] | None:
    """Return a report only when it belongs in a production customer view."""
    report = _stored_get_report(analysis_id, workspace_id=workspace_id)
    if report and is_production_runtime() and is_internal_test_fixture_analysis(report):
        return None
    return report


def list_reports(*, workspace_id: str) -> list[dict[str, Any]]:
    return customer_visible_analyses(
        _stored_list_reports(workspace_id=workspace_id),
        production=is_production_runtime(),
    )


def analyses_and_parts(
    *, workspace_id: str, analysis_id: str | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if analysis_id and not get_report(analysis_id, workspace_id=workspace_id):
        return [], []
    analyses, parts = _stored_analyses_and_parts(
        workspace_id=workspace_id, analysis_id=analysis_id
    )
    if not is_production_runtime():
        return analyses, parts
    visible_ids = {
        str(row.get("id") or row.get("analysis_id") or "")
        for row in list_reports(workspace_id=workspace_id)
    }
    return (
        [row for row in analyses if str(row.get("id") or "") in visible_ids],
        [row for row in parts if str(row.get("analysis_id") or "") in visible_ids],
    )

def _require_analysis(
    analysis_id: str | None, *, workspace_id: str
) -> dict[str, Any] | None:
    if analysis_id:
        return get_report(analysis_id, workspace_id=workspace_id)
    reports = customer_visible_analyses(
        list_reports(workspace_id=workspace_id),
        production=is_production_runtime(),
    )
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
        "mode": "workspace-monitoring",
        "analysis_id": None,
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
                "part_nu
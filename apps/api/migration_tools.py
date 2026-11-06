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
    normalize_supplier_offer_records,
    procurement_recommendation_html,
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
    """Map internal needs-data labels to customer-facing Unable to confirm."""
    text = str(value or "").strip()
    lower = text.lower()
    if not text:
        return "Unable to confirm"
    if "needs data" in lower or "needs validation" in lower:
        return "Unable to confirm"
    return text


def _customer_compare_value(value: Any) -> Any:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "null", "n/a", "—", "-"}:
        return "Unable to confirm"
    lower = text.lower()
    if "not stated" in lower or "not retrieved" in lower or "not available" in lower:
        return "Unable to confirm"
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
    for part in report.get("parts") or []:
        mpn = str(part.get("MPN") or "")
        lifecycle = str(part.get("Lifecycle") or "")
        risk = str(part.get("Risk Level") or "")
        if lifecycle.upper() == "NRND":
            alerts.append(
                {
                    **build_alert_record(
                        "smoke-user",
                        report["id"],
                        mpn,
                        "Lifecycle Signal",
                        f"Lifecycle recorded as {lifecycle} in synthetic analysis",
                        "High",
                        "Active (assumed)",
                        lifecycle,
                    ),
                    "created_at": now,
                    "acknowledged": False,
                    "evidence_source": "synthetic-preview-analysis",
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
                        f"High risk in latest analysis: {part.get('Risk Reasons') or 'see report'}",
                        "High",
                        "—",
                        risk,
                    ),
                    "created_at": now,
                    "acknowledged": False,
                    "evidence_source": "synthetic-preview-analysis",
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
                        f"Medium risk in latest analysis: {part.get('Risk Reasons') or 'see report'}",
                        "Medium",
                        "—",
                        risk,
                    ),
                    "created_at": now,
                    "acknowledged": False,
                    "evidence_source": "synthetic-preview-analysis",
                }
            )

    alert_df = pd.DataFrame(alerts)
    monitor_df = pd.DataFrame(
        [
            {
                "part_number": p.get("MPN"),
                "lifecycle_status": p.get("Lifecycle"),
                "stock": p.get("Stock"),
                "risk_level": p.get("Risk Level"),
            }
            for p in report.get("parts") or []
        ]
    )
    action_center = build_monitoring_action_center(alert_df, monitor_df)
    high = sum(1 for a in alerts if str(a.get("severity")).lower() == "high")
    lifecycle_n = sum(
        1 for a in alerts if "lifecycle" in str(a.get("alert_type") or "").lower()
    )
    for alert in alerts:
        alert["analysis_id"] = report["id"]
        alert["workspace_id"] = workspace_id
        alert["evidence_source"] = alert.get("evidence_source") or "synthetic-preview-analysis"
    durable = monitoring_store.persist_alerts(workspace_id, alerts)
    refresh = monitoring_store.record_refresh(
        workspace_id,
        analysis_id=report["id"],
        alert_count=len(durable),
        mode="synthetic-preview",
    )
    prefs = monitoring_store.get_preferences(workspace_id)
    return _json_safe(
        {
            "ok": True,
            "mode": "synthetic-preview",
            "analysis_id": report["id"],
            "filename": report.get("filename"),
            "gap": (
                "Monitoring persists tenant-scoped alert history from saved analysis. "
                "Scheduled supplier refresh and real alert email remain disabled."
            ),
            "metrics": {
                "monitored_parts": report.get("total_parts") or 0,
                "active_alerts": len(durable),
                "high_priority": high,
                "lifecycle_changes": lifecycle_n,
            },
            "alerts": durable,
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

    report = _require_analysis(analysis_id, workspace_id=workspace_id)
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
        "Live supplier and datasheet fetch are not connected. "
        "Comparison uses saved analysis fields when available, otherwise labeled "
        "offline catalog attributes — not live distributor evidence."
    )
    if family_mismatch:
        gap = (
            "Component families differ based on offline catalog attributes. "
            "This is an evidence-backed incompatibility signal, not a qualified "
            "drop-in approval. Live datasheets were not fetched."
        )
    elif not rows:
        gap = (
            "Unable to confirm compatibility: attribute evidence is missing for "
            "both parts. Live supplier lookup and datasheet fetch are not connected."
        )

    return _json_safe(
        {
            "ok": True,
            "status": STATUS_COMPLETED,
            "mode": "synthetic-preview",
            "part_a": a,
            "part_b": b,
            "source_a": source_a,
            "source_b": source_b,
            "gap": gap,
            "finding": finding,
            "family": (comparison.get("family") or comparison.get("family_meta") or {}),
            "family_mismatch": family_mismatch,
            "rows": rows,
            "part_cards": {
                "a": comparison.get("part_a"),
                "b": comparison.get("part_b"),
            },
            "comparison": {
                k: comparison.get(k)
                for k in (
                    "overall_finding",
                    "finding",
                    "summary",
                    "counts",
                    "engineering_confidence",
                    "family_mismatch",
                )
                if k in comparison
            },
        }
    )


def find_replacement_payload(
    *,
    workspace_id: str,
    mpn: str,
    manufacturer: str = "",
    analysis_id: str | None = None,
) -> dict[str, Any]:
    """Standalone replacement search; BOM analysis is optional context only."""
    from apps.api.compare_catalog import offline_replacement_candidates
    from apps.api.supplier_lookup import live_lookups_enabled, lookup_exact_part

    requested = str(mpn or "").strip()
    if not requested:
        return {
            "ok": False,
            "status": STATUS_FAILED,
            "detail": "Enter a manufacturer part number to search.",
        }

    report = _require_analysis(analysis_id, workspace_id=workspace_id)
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
            "original": {
                "mpn": original.get("manufacturer_part_number") or requested,
                "manufacturer": original.get("manufacturer") or "",
                "description": original.get("description") or "",
                "lifecycle_status": original.get("lifecycle_status") or "",
                "source": original.get("source") or "synthetic-preview",
                "lookup": original_lookup,
            },
            "bom_context": bom_context,
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
                "quantity": part.get("Quantity") or part.get("quantity"),
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
    report = _require_analysis(analysis_id, workspace_id=workspace_id)
    if not report:
        return {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": "No analysis yet. Live distributor coverage is not connected.",
            "parts": [],
        }
    rows = []
    for part in report.get("parts") or []:
        offers = normalize_supplier_offer_records(part)
        rows.append(
            {
                "mpn": part.get("MPN"),
                "manufacturer": part.get("Manufacturer"),
                "lifecycle": part.get("Lifecycle"),
                "risk_level": part.get("Risk Level"),
                "stock": part.get("Stock"),
                "unit_price": part.get("unit_price") or part.get("Unit Price"),
                "price_source": part.get("price_source") or "synthetic-preview",
                "supplier_offers": offers,
                "offer_count": len(offers),
                "coverage": "unavailable"
                if not offers
                else "recorded-offers",
                "evidence": classify_part_evidence(
                    {
                        "MPN": part.get("MPN"),
                        "Manufacturer": part.get("Manufacturer"),
                        "Unit Price": part.get("unit_price") or part.get("Unit Price"),
                        "evidence_source": part.get("price_source") or "synthetic-preview",
                        "source": part.get("Supplier") or "",
                    }
                ),
                "authorized_lookup": (
                    lambda hit: {
                        "evidence_class": hit.get("evidence_class"),
                        "synthetic": hit.get("synthetic"),
                        "source_url": (hit.get("match") or {}).get("source_url") or "",
                        "retrieved_at": (hit.get("match") or {}).get("retrieved_at") or "",
                        "live_lookups_enabled": hit.get("live_lookups_enabled"),
                        "gap": hit.get("gap"),
                    }
                )(lookup_exact_part(str(part.get("MPN") or ""))),
            }
        )
    return _json_safe(
        {
            "ok": True,
            "mode": "synthetic-preview",
            "analysis_id": report["id"],
            "filename": report.get("filename"),
            "gap": "Live supplier pricing and availability are disabled. Unit prices shown are synthetic-preview fields from analysis, not distributor quotes.",
            "recommendation_note": "Use recorded analysis fields for triage only. Do not treat synthetic unit prices as procurement awards.",
            "parts": rows,
            "recommendation_html_available": callable(procurement_recommendation_html),
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
            "gap": "Impact is computed from saved analyses in this workspace only.",
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
            "gap": "Portfolio is calculated from this workspace's saved analyses only.",
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
    return _json_safe(
        {
            "ok": True,
            "mode": "synthetic-preview",
            "analysis_id": report["id"],
            "filename": report.get("filename"),
            "health_score": report.get("health_score"),
            "health_status": report.get("health_status"),
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

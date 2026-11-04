"""Sandbox tool handlers for Next.js migration pages.

Reuses Cadivor build_* helpers on in-memory synthetic analyses. Never calls
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


def monitoring_payload(
    *, workspace_id: str, analysis_id: str | None = None
) -> dict[str, Any]:
    report = _require_analysis(analysis_id, workspace_id=workspace_id)
    if not report:
        return {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": "No analyzed BOM yet. Run BOM Analyzer first. Durable Supabase monitor_alerts are not available in sandbox.",
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
    return _json_safe(
        {
            "ok": True,
            "mode": "synthetic-preview",
            "analysis_id": report["id"],
            "filename": report.get("filename"),
            "gap": "Sandbox monitoring derives review signals from the latest synthetic analysis. It does not read Supabase monitor_alerts or run scheduled supplier refresh.",
            "metrics": {
                "monitored_parts": report.get("total_parts") or 0,
                "active_alerts": len(alerts),
                "high_priority": high,
                "lifecycle_changes": lifecycle_n,
            },
            "alerts": alerts,
            "action_center": action_center,
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
    rows = user_facing_compare_rows(comparison.get("rows") or comparison.get("comparison_rows"))
    if not rows and isinstance(comparison.get("user_facing_rows"), list):
        rows = comparison["user_facing_rows"]
    # Fall back to raw rows if helper shape differs
    if not rows and isinstance(comparison.get("rows"), list):
        rows = comparison["rows"]

    return _json_safe(
        {
            "ok": True,
            "status": STATUS_COMPLETED,
            "mode": "synthetic-preview",
            "part_a": a,
            "part_b": b,
            "source_a": source_a,
            "source_b": source_b,
            "gap": "Live supplier lookup is disabled in sandbox. Comparison uses analysis records when present, otherwise labeled synthetic-preview fields — not live distributor evidence.",
            "finding": comparison.get("overall_finding")
            or comparison.get("finding")
            or comparison.get("summary"),
            "family": (comparison.get("family") or comparison.get("family_meta") or {}),
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
                )
                if k in comparison
            },
        }
    )


def datasheet_qa_payload(
    *,
    filename: str,
    payload: bytes,
    question: str,
) -> dict[str, Any]:
    document = extract_uploaded_datasheet(payload, filename=filename or "datasheet.pdf")
    # Prefer local grounded answers; do not require AI credentials in sandbox.
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
            "gap": "No analysis yet. Live distributor coverage is disabled in sandbox.",
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
            "gap": "Analyze a BOM first. Design impact needs at least one in-memory analysis.",
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
            "gap": "Impact is computed from sandbox in-memory analyses only — not the production saved-BOM catalog.",
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
            "gap": "No in-memory analyses yet. Production Streamlit portfolio history is not mirrored.",
            "intelligence": {},
            "reports": [],
        }
    intelligence = build_portfolio_intelligence(analyses, parts, alerts)
    return _json_safe(
        {
            "ok": True,
            "mode": "synthetic-preview",
            "gap": "Portfolio is limited to analyses created in this sandbox API process for the authenticated workspace.",
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

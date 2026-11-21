"""Evidence-linked compliance and lifecycle packs.

These exports describe evidence attached to a saved part record. They never
turn a catalog listing into a compliance claim and never infer that no PCN,
last-time-buy date, or end-of-life notice exists when a source did not report it.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from apps.api.evidence_contract import EVIDENCE_LIVE


EVIDENCE_PACK_TYPES = ("rohs", "reach", "pfas", "conflict_minerals", "pcn")
PACK_TYPES = (*EVIDENCE_PACK_TYPES, "audit")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _part_rows(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [dict(p) for p in (report or {}).get("parts") or [] if isinstance(p, dict)]


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None and str(value).strip():
            return value
    return None


def _part_evidence(part: dict[str, Any], kind: str) -> dict[str, Any]:
    evidence = part.get("evidence") if isinstance(part.get("evidence"), dict) else {}
    compliance_root = part.get("compliance_evidence")
    if not isinstance(compliance_root, dict):
        compliance_root = evidence.get("compliance") if isinstance(evidence.get("compliance"), dict) else {}
    node = compliance_root.get(kind) if isinstance(compliance_root.get(kind), dict) else {}
    value = _first(
        node.get("reported_value"), node.get("status"),
        part.get(f"{kind}_status"), part.get(f"{kind}_reported"),
        part.get("PFAS status") if kind == "pfas" else None,
        part.get("RoHS status") if kind == "rohs" else None,
        part.get("REACH status") if kind == "reach" else None,
    )
    source_url = _first(
        node.get("source_url"), node.get("url"), node.get("document_url"),
        part.get(f"{kind}_source_url"), part.get(f"{kind}_evidence_url"),
        part.get(f"{kind}_url"),
    )
    source = _first(node.get("source"), part.get(f"{kind}_source"))
    evidence_class = str(
        _first(node.get("evidence_class"), part.get(f"{kind}_evidence_class")) or ""
    ).strip()
    retrieved_at = _first(node.get("retrieved_at"), part.get(f"{kind}_retrieved_at"))
    from src.normalizer import normalize_part_number

    part_mpn = str(
        part.get("MPN") or part.get("mpn") or part.get("manufacturer_part_number") or ""
    ).strip()
    evidence_mpn = str(node.get("mpn") or part_mpn).strip()
    identity_matches = bool(
        part_mpn
        and evidence_mpn
        and normalize_part_number(part_mpn) == normalize_part_number(evidence_mpn)
    )
    conflict = bool(node.get("conflict"))
    normalized_value = str(value or "").strip().casefold()
    source_reports_unknown = normalized_value in {
        "unknown", "not stated", "not reported", "not provided", "not available",
        "reach unknown", "rohs unknown", "pfas unknown",
    }
    evidence_linked = bool(
        value is not None
        and source_url
        and evidence_class == EVIDENCE_LIVE
        and identity_matches
    )
    if conflict:
        status = "conflicting_evidence"
        reason = f"Supplier records disagree on {kind.upper()}; review each source before relying on the declaration."
    elif evidence_linked and source_reports_unknown:
        status = "supplier_reports_unknown"
        reason = f"The supplier source returned “{value}”; no {kind.upper()} compliance conclusion is available."
    elif evidence_linked:
        status = "evidence_linked"
        reason = "Supplier catalog declaration linked to this exact part."
    elif value is not None:
        status = "reported_unverified"
        reason = (
            "The declaration could not be tied to the exact BOM part number."
            if not identity_matches
            else "A value was recorded, but its source is not verified."
        )
    else:
        status = "missing_evidence"
        reason = f"No {kind.upper()} declaration was returned by the supplier lookup; status is unknown."
    return {
        "status": status,
        "reported_value": str(value) if value is not None else None,
        "source": str(source or "") if source is not None else "",
        "source_url": str(source_url or "") if source_url is not None else "",
        "evidence_class": evidence_class or "missing",
        "retrieved_at": str(retrieved_at or "") if retrieved_at is not None else "",
        "reason": reason,
        "conflict": conflict,
        "sources": node.get("sources") if isinstance(node.get("sources"), list) else [],
    }


def _lifecycle_events(part: dict[str, Any]) -> dict[str, Any]:
    evidence = part.get("lifecycle_event_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    pcn = part.get("pcn_evidence")
    if not isinstance(pcn, dict):
        pcn = evidence.get("pcn") if isinstance(evidence.get("pcn"), dict) else {}
    event = {
        "pcn_number": _first(part.get("pcn_number"), part.get("pcn_id"), part.get("PCN Number"), pcn.get("notice_number"), pcn.get("pcn_number"), pcn.get("id")),
        "pcn_date": _first(part.get("pcn_date"), part.get("PCN Date"), pcn.get("date"), pcn.get("notice_date")),
        "pcn_status": _first(part.get("pcn_status"), part.get("PCN Status"), pcn.get("status")),
        "pcn_url": _first(part.get("pcn_url"), part.get("PCN URL"), pcn.get("source_url"), pcn.get("url"), evidence.get("pcn_url")),
        "last_time_buy_date": _first(part.get("last_time_buy_date"), part.get("Last Time Buy Date")),
        "end_of_life_date": _first(part.get("end_of_life_date"), part.get("End Of Life Date"), part.get("EOL Date")),
        "estimated_eol_years": _first(part.get("estimated_eol_years"), part.get("Estimated EOL Years")),
        "source_url": _first(pcn.get("source_url"), evidence.get("source_url"), part.get("lifecycle_event_source_url")),
        "source": _first(pcn.get("source"), evidence.get("source"), part.get("lifecycle_event_source")),
        "evidence_class": _first(evidence.get("evidence_class"), part.get("lifecycle_event_evidence_class")),
        "pcn_evidence_class": _first(part.get("pcn_evidence_class"), pcn.get("evidence_class")),
        "retrieved_at": _first(pcn.get("retrieved_at"), evidence.get("retrieved_at"), part.get("lifecycle_event_retrieved_at")),
    }
    if event["estimated_eol_years"] is not None:
        event["estimated_eol_years_basis"] = "reported by source"
    else:
        end_date = str(event.get("end_of_life_date") or "").strip()
        if end_date and str(event.get("source_url") or "").startswith("https://") and event.get("evidence_class") == EVIDENCE_LIVE:
            try:
                remaining_days = (date.fromisoformat(end_date[:10]) - datetime.now(timezone.utc).date()).days
                event["estimated_eol_years"] = round(remaining_days / 365.2425, 1)
                event["estimated_eol_years_basis"] = "calculated from source end-of-life date at export time"
            except ValueError:
                event["estimated_eol_years_basis"] = "source date could not be parsed"
        else:
            event["estimated_eol_years_basis"] = "not calculated; source-linked end-of-life date is unavailable"
    return event


def build_compliance_record(part: dict[str, Any], pack_type: str) -> dict[str, Any]:
    kind = str(pack_type or "").strip().lower()
    mpn = str(_first(part.get("MPN"), part.get("mpn"), part.get("manufacturer_part_number")) or "")
    if kind == "pcn":
        event = _lifecycle_events(part)
        notice = any(event.get(key) for key in ("pcn_number", "pcn_date", "pcn_status", "pcn_url"))
        supported = bool(
            notice and event.get("pcn_url") and event.get("pcn_evidence_class") == EVIDENCE_LIVE
        )
        status = "evidence_linked" if supported else "reported_unverified" if notice else "missing_evidence"
        return {
            "pack_type": kind,
            "mpn": mpn,
            "status": status,
            "reported_value": event.get("pcn_status") or event.get("pcn_number"),
            "lifecycle_events": event,
            "source_url": event.get("pcn_url") or event.get("source_url") or "",
            "claim": None,
            "gap": None if supported else "No source-verified PCN record is attached. Missing data does not mean no PCN exists.",
        }
    evidence = _part_evidence(part, kind)
    return {
        "pack_type": kind,
        "mpn": mpn,
        **evidence,
        "claim": None,
        "gap": None if evidence["status"] == "evidence_linked" else (
            f"No source-verified {kind.upper()} declaration is attached."
            if evidence["status"] == "missing_evidence"
            else f"A {kind.upper()} value is reported without verifiable supporting evidence."
        ),
    }


def build_pack(report: dict[str, Any] | None, pack_type: str) -> dict[str, Any]:
    kind = str(pack_type or "").strip().lower()
    if kind not in EVIDENCE_PACK_TYPES:
        return {"ok": False, "detail": f"Unknown pack type: {pack_type}", "allowed": list(EVIDENCE_PACK_TYPES)}
    records = [build_compliance_record(part, kind) for part in _part_rows(report)]
    counts = {status: sum(1 for row in records if row["status"] == status) for status in (
        "evidence_linked", "reported_unverified", "missing_evidence"
    )}
    return {
        "ok": True,
        "pack_type": kind,
        "mode": str((report or {}).get("mode") or "unknown"),
        "generated_at": _utc_now(),
        "analysis_id": (report or {}).get("id"),
        "records": records,
        "summary": {"total": len(records), **counts, "compliance_claimed": False},
        "gap": "Evidence is shown only when a component-specific source is attached. Missing records are unknown, not compliant or noncompliant.",
    }


def export_audit_bundle(report: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "ok": True,
        "mode": str((report or {}).get("mode") or "unknown"),
        "generated_at": _utc_now(),
        "analysis_id": (report or {}).get("id"),
        "packs": {kind: build_pack(report, kind) for kind in EVIDENCE_PACK_TYPES},
        "lifecycle_events": [
            {"mpn": str(_first(part.get("MPN"), part.get("mpn")) or ""), **_lifecycle_events(part)}
            for part in _part_rows(report)
        ],
        "compliance_claimed": False,
        "gap": "Evidence-linked working papers only. They are not certifications or compliance determinations.",
    }

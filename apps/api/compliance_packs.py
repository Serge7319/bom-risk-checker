"""Compliance evidence packs (RoHS, REACH, conflict minerals, audit export).

Synthetic examples only. Missing evidence is labeled explicitly. Never claims
compliance without a sourced evidence link.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.api.evidence_contract import classify_part_evidence, EVIDENCE_LIVE


PACK_TYPES = ("rohs", "reach", "conflict_minerals", "audit")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _part_rows(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [dict(p) for p in (report or {}).get("parts") or [] if isinstance(p, dict)]


def build_compliance_record(part: dict[str, Any], pack_type: str) -> dict[str, Any]:
    evidence = classify_part_evidence(part)
    mpn = evidence.get("requested_mpn") or str(part.get("MPN") or "")
    source_url = evidence.get("source_url") or ""
    has_sourced = bool(source_url) and evidence.get("evidence_class") == EVIDENCE_LIVE
    status = "evidence_linked" if has_sourced else "missing_evidence"
    return {
        "pack_type": pack_type,
        "mpn": mpn,
        "status": status,
        "claim": None if status == "missing_evidence" else f"{pack_type.upper()} evidence linked",
        "evidence": evidence,
        "source_url": source_url,
        "retrieved_at": evidence.get("retrieved_at") or "",
        "gap": (
            None
            if has_sourced
            else f"No sourced {pack_type.upper()} evidence for {mpn or 'unknown part'}. Do not claim compliance."
        ),
    }


def build_pack(report: dict[str, Any] | None, pack_type: str) -> dict[str, Any]:
    kind = str(pack_type or "").strip().lower()
    if kind not in PACK_TYPES:
        return {"ok": False, "detail": f"Unknown pack type: {pack_type}", "allowed": list(PACK_TYPES)}
    records = [build_compliance_record(part, kind) for part in _part_rows(report)]
    linked = sum(1 for r in records if r["status"] == "evidence_linked")
    missing = sum(1 for r in records if r["status"] == "missing_evidence")
    return {
        "ok": True,
        "pack_type": kind,
        "mode": "synthetic-preview",
        "generated_at": _utc_now(),
        "analysis_id": (report or {}).get("id"),
        "records": records,
        "summary": {
            "total": len(records),
            "evidence_linked": linked,
            "missing_evidence": missing,
            "compliance_claimed": False,
        },
        "gap": (
            "Compliance packs list evidence links when present. "
            "Missing evidence is labeled; Cadivor does not assert RoHS/REACH/CMRT compliance without sources."
        ),
    }


def export_audit_bundle(report: dict[str, Any] | None) -> dict[str, Any]:
    packs = {kind: build_pack(report, kind) for kind in PACK_TYPES}
    return {
        "ok": True,
        "mode": "synthetic-preview",
        "generated_at": _utc_now(),
        "analysis_id": (report or {}).get("id"),
        "packs": packs,
        "compliance_claimed": False,
        "gap": "Audit export is evidence-linked only; no compliance certification is implied.",
    }

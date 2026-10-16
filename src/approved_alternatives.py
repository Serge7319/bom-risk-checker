"""Helpers for durable, project-scoped alternative approvals."""
from __future__ import annotations

import re
from typing import Any, Iterable

from src.normalizer import normalize_part_number


def part_key(value: Any) -> str:
    text = str(value or "").strip()
    return normalize_part_number(text) or text.upper()


def candidate_lifecycle_is_blocked(candidate: Any) -> bool:
    """True when recorded lifecycle evidence says a candidate is not orderable.

    Unknown status remains reviewable. Explicit obsolete, discontinued, or
    end-of-life records are never presented as replacement-ready or approved.
    """
    if not isinstance(candidate, dict):
        return False
    status_values = [
        str(candidate.get(key) or "").strip().casefold()
        for key in (
            "Lifecycle",
            "Lifecycle Status",
            "lifecycle_status",
            "lifecycle",
            "product_status",
        )
        if str(candidate.get(key) or "").strip()
    ]
    discovery = candidate.get("_discovery_row")
    if isinstance(discovery, dict):
        status_values.extend(
            str(discovery.get(key) or "").strip().casefold()
            for key in (
                "Lifecycle",
                "Lifecycle Status",
                "lifecycle_status",
                "lifecycle",
                "product_status",
            )
            if str(discovery.get(key) or "").strip()
        )
    for status in status_values:
        if re.search(
            r"\b(?:not\s+(?:eol|obsolete|discontinued|end\s+of\s+life)"
            r"|non[\s-]?(?:eol|obsolete|discontinued))\b",
            status,
        ):
            continue
        if re.search(r"\beol\b", status) or any(
            term in status for term in ("obsolete", "discontinued", "end of life")
        ):
            return True
    return False


def toggle_comparison_candidate(
    selected: Iterable[Any] | None,
    candidate: Any,
    *,
    limit: int = 2,
) -> list[str]:
    """Toggle one unique replacement in the bounded compare selection."""
    value = str(candidate or "").strip()
    token = part_key(value)
    if not value or not token:
        return [str(item).strip() for item in (selected or []) if str(item or "").strip()][:limit]
    output: list[str] = []
    seen: set[str] = set()
    for item in selected or []:
        text = str(item or "").strip()
        item_token = part_key(text)
        if not text or not item_token or item_token == token or item_token in seen:
            continue
        seen.add(item_token)
        output.append(text)
    if not any(part_key(str(item or "").strip()) == token for item in selected or []):
        if len(output) < max(int(limit), 0):
            output.append(value)
    return output


def project_decision_context_key(project_name: Any, analysis_id: Any = "") -> str:
    """Keep replacement approvals stable when a BOM is rerun into a new analysis."""
    project = " ".join(str(project_name or "").strip().casefold().split())
    if project:
        return "project:" + project[:180]
    analysis = str(analysis_id or "").strip()
    return analysis or "standalone"


def _same_project(record: dict[str, Any], *, project_name: str, analysis_id: str) -> bool:
    record_analysis = str(record.get("analysis_id") or "").strip()
    if analysis_id and record_analysis == analysis_id:
        return True
    if project_name:
        return " ".join(str(record.get("project_name") or "").strip().casefold().split()) == " ".join(project_name.strip().casefold().split())
    if analysis_id:
        return False
    return str(record.get("context_key") or "") == "standalone"


def approved_records_for_part(
    records: Iterable[dict[str, Any]] | None,
    original_mpn: Any,
    *,
    project_name: str = "",
    analysis_id: str = "",
) -> list[dict[str, Any]]:
    """Return unique active approvals for one component in the same project."""
    original_key = part_key(original_mpn)
    if not original_key:
        return []
    found: dict[str, dict[str, Any]] = {}
    for row in records or []:
        if not isinstance(row, dict) or str(row.get("decision") or "").strip().casefold() != "approved":
            continue
        if part_key(row.get("original_part")) != original_key:
            continue
        if not _same_project(row, project_name=project_name, analysis_id=analysis_id):
            continue
        alternative = str(row.get("alternative_part") or "").strip()
        alternative_key = part_key(alternative)
        if not alternative_key or alternative_key == original_key:
            continue
        previous = found.get(alternative_key)
        if previous is None or str(row.get("updated_at") or row.get("created_at") or "") > str(
            previous.get("updated_at") or previous.get("created_at") or ""
        ):
            found[alternative_key] = row
    return sorted(
        found.values(),
        key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""),
        reverse=True,
    )


def approval_candidate_options(
    candidate_mpns: Iterable[Any] | None,
    records: Iterable[dict[str, Any]] | None,
) -> list[str]:
    """Keep current search results and saved approvals selectable without duplicates."""
    values: list[str] = []
    seen: set[str] = set()
    for item in candidate_mpns or []:
        value = str(item or "").strip()
        key = part_key(value)
        if value and key and key not in seen:
            seen.add(key)
            values.append(value)
    for row in records or []:
        if not isinstance(row, dict):
            continue
        value = str(row.get("alternative_part") or "").strip()
        key = part_key(value)
        if value and key and key not in seen:
            seen.add(key)
            values.append(value)
    return values


def approved_records_for_bom(
    records: Iterable[dict[str, Any]] | None,
    parts: Iterable[dict[str, Any]] | None,
    *,
    project_name: str = "",
    analysis_id: str = "",
) -> list[dict[str, Any]]:
    """Select approved alternatives that belong to a BOM's component list."""
    component_keys = {
        part_key(row.get("mpn") or row.get("MPN") or row.get("part_number"))
        for row in parts or []
        if isinstance(row, dict)
    }
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in records or []:
        if not isinstance(row, dict):
            continue
        original = part_key(row.get("original_part"))
        if original not in component_keys:
            continue
        for approved in approved_records_for_part(
            [row],
            row.get("original_part"),
            project_name=project_name,
            analysis_id=analysis_id,
        ):
            pair = (part_key(approved.get("original_part")), part_key(approved.get("alternative_part")))
            if pair not in seen:
                seen.add(pair)
                selected.append(approved)
    return selected


def report_alternative(record: dict[str, Any]) -> dict[str, Any]:
    """Convert a saved decision into an explicitly approved report row."""
    snapshot = record.get("source_snapshot")
    if isinstance(snapshot, str):
        import json

        try:
            snapshot = json.loads(snapshot)
        except (TypeError, ValueError):
            snapshot = {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    candidate = snapshot.get("candidate") or snapshot.get("selected_alternative") or {}
    candidate = candidate if isinstance(candidate, dict) else {}
    engineer = str(record.get("engineer_name") or "Cadivor user").strip()
    note = str(record.get("engineering_note") or "").strip()
    reason = f"Approved by {engineer}"
    if note:
        reason += f" · {note}"
    return {
        "original_part": str(record.get("original_part") or "").strip(),
        "alternative_part": str(record.get("alternative_part") or "").strip(),
        "manufacturer": candidate.get("Manufacturer") or candidate.get("manufacturer") or "",
        "description": candidate.get("Description") or candidate.get("description") or "",
        "image_url": candidate.get("Image URL") or candidate.get("image_url") or "",
        "decision": "Approved",
        "is_persisted_approval": True,
        "approved_by": engineer,
        "approved_at": record.get("updated_at") or record.get("created_at") or "",
        "engineering_note": note,
        "reason": reason,
    }


def approved_mpn_map(records: Iterable[dict[str, Any]] | None) -> dict[str, list[dict[str, Any]]]:
    """Map saved approval records to the original component MPN."""
    output: dict[str, list[dict[str, Any]]] = {}
    for row in records or []:
        if not isinstance(row, dict) or str(row.get("decision") or "").strip().casefold() != "approved":
            continue
        original = part_key(row.get("original_part"))
        alternative = str(row.get("alternative_part") or "").strip()
        if original and alternative:
            output.setdefault(original, []).append(report_alternative(row))
    return output

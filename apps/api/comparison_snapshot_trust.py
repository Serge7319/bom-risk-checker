"""Server-verifiable comparison snapshot reuse for decision records.

Compare responses receive an HMAC snapshot_token bound to the authenticated
workspace/user, analysis ID, part pair, and a digest of evidence contents.
Decision recording reuses a snapshot only when that token still verifies;
otherwise the server recomputes the comparison. verified_primary_evidence is
derived only from server-verified comparison fields.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Mapping

# Fields that affect engineering evidence / primary-evidence derivation.
SNAPSHOT_CONTENT_KEYS: tuple[str, ...] = (
    "mode",
    "finding",
    "engineering_evidence_summary",
    "engineering_evidence_status",
    "counts",
    "family",
    "family_mismatch",
    "rows",
    "part_cards",
    "source_a",
    "source_b",
    "evidence_sources",
    "datasheet_identity",
    "package_dimension_evidence",
    "review_warnings",
    "gap",
    "manufacturer_a",
    "manufacturer_b",
)

_SNAPSHOT_TTL_SECONDS = 60 * 60 * 12  # 12h, aligned with sandbox JWT TTL


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def snapshot_signing_secret() -> str:
    """Secret used to bind comparison snapshots. Fail closed when unset."""
    for key in (
        "CADIVOR_COMPARISON_SNAPSHOT_SECRET",
        "CADIVOR_SANDBOX_AUTH_SECRET",
    ):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    return ""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )


def snapshot_content_digest(snapshot: Mapping[str, Any] | None) -> str:
    payload = {
        key: (snapshot or {}).get(key)
        for key in SNAPSHOT_CONTENT_KEYS
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _normalize_part(value: object) -> str:
    return str(value or "").strip()


def _normalize_analysis_id(value: object) -> str:
    return str(value or "").strip()


def issue_snapshot_token(
    *,
    workspace_id: str,
    user_id: str | None,
    analysis_id: str | None,
    part_a: str,
    part_b: str,
    snapshot: Mapping[str, Any],
    now: int | None = None,
) -> str:
    """Return a compact HMAC token bound to identity + content digest."""
    secret = snapshot_signing_secret()
    if not secret:
        return ""
    issued_at = int(now if now is not None else time.time())
    claims = {
        "ws": str(workspace_id or "").strip(),
        "uid": str(user_id or "").strip(),
        "aid": _normalize_analysis_id(analysis_id),
        "a": _normalize_part(part_a),
        "b": _normalize_part(part_b),
        "dig": snapshot_content_digest(snapshot),
        "iat": issued_at,
        "exp": issued_at + _SNAPSHOT_TTL_SECONDS,
        "v": 1,
    }
    body = _b64url(_canonical_json(claims))
    sig = _b64url(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def attach_snapshot_token(
    comparison: dict[str, Any],
    *,
    workspace_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    """Mutate/return comparison with a server-issued snapshot_token when possible."""
    if not isinstance(comparison, dict) or comparison.get("ok") is False:
        return comparison
    token = issue_snapshot_token(
        workspace_id=workspace_id,
        user_id=user_id,
        analysis_id=comparison.get("analysis_id"),
        part_a=str(comparison.get("part_a") or ""),
        part_b=str(comparison.get("part_b") or ""),
        snapshot=comparison,
    )
    if token:
        comparison = dict(comparison)
        comparison["snapshot_token"] = token
        comparison["snapshot_binding"] = {
            "workspace_id": str(workspace_id or "").strip(),
            "user_id": str(user_id or "").strip(),
            "analysis_id": _normalize_analysis_id(comparison.get("analysis_id")),
            "part_a": _normalize_part(comparison.get("part_a")),
            "part_b": _normalize_part(comparison.get("part_b")),
            "content_digest": snapshot_content_digest(comparison),
        }
    return comparison


def _verify_pairwise_snapshot_token(
    snapshot: Mapping[str, Any],
    *,
    workspace_id: str,
    user_id: str | None,
    analysis_id: str | None,
    part_a: str,
    part_b: str,
    now: int | None = None,
) -> bool:
    """True only when the snapshot token binds this caller and pairwise content digest."""
    secret = snapshot_signing_secret()
    if not secret:
        return False
    token = str(snapshot.get("snapshot_token") or "").strip()
    if not token or "." not in token:
        return False
    body, _, sig = token.partition(".")
    if not body or not sig:
        return False
    expected = _b64url(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(expected, sig):
        return False
    try:
        claims = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(claims, dict):
        return False
    current = int(now if now is not None else time.time())
    try:
        exp = int(claims.get("exp") or 0)
    except (TypeError, ValueError):
        return False
    if exp < current:
        return False
    if str(claims.get("ws") or "").strip() != str(workspace_id or "").strip():
        return False
    if str(claims.get("uid") or "").strip() != str(user_id or "").strip():
        return False
    claim_aid = _normalize_analysis_id(claims.get("aid"))
    request_aid = _normalize_analysis_id(analysis_id)
    snapshot_aid = _normalize_analysis_id(snapshot.get("analysis_id"))
    # Requested analysis ID (when present) must match both claim and payload.
    if request_aid and (request_aid != claim_aid or request_aid != snapshot_aid):
        return False
    if claim_aid and snapshot_aid and claim_aid != snapshot_aid:
        return False
    if _normalize_part(claims.get("a")) != _normalize_part(part_a):
        return False
    if _normalize_part(claims.get("b")) != _normalize_part(part_b):
        return False
    if _normalize_part(snapshot.get("part_a")) != _normalize_part(part_a):
        return False
    if _normalize_part(snapshot.get("part_b")) != _normalize_part(part_b):
        return False
    claimed_digest = str(claims.get("dig") or "").strip()
    if not claimed_digest or claimed_digest != snapshot_content_digest(snapshot):
        return False
    return True


def _text(value: object, fallback: str = "—") -> str:
    text = str(value or "").strip()
    return text or fallback


def _comparison_rows(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = candidate.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def rebuild_multi_matrix(
    part_a: str,
    verified_candidates: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rebuild the multi-candidate matrix only from verified pairwise rows."""
    attribute_order: list[str] = []
    by_attribute: dict[str, dict[str, Any]] = {}
    candidate_mpns = [
        _normalize_part(entry.get("part_b") or entry.get("mpn"))
        for entry in verified_candidates
    ]
    for entry, mpn in zip(verified_candidates, candidate_mpns):
        for row in _comparison_rows(entry):
            attribute = _text(row.get("Attribute") or row.get("attribute"), "")
            if not attribute or attribute == "—":
                continue
            key = attribute.casefold()
            matrix = by_attribute.get(key)
            if matrix is None:
                attribute_order.append(attribute)
                matrix = {
                    "attribute": attribute,
                    "current": _text(row.get("Part A") or row.get("Original") or row.get("part_a")),
                    "currentSource": _text(row.get("Part A source"), "Not stated"),
                    "currentClass": _text(row.get("Part A value class"), "unknown"),
                    "currentCondition": _text(
                        row.get("Part A test condition") or row.get("Test condition"),
                        "Not stated",
                    ),
                    "unit": _text(row.get("Unit"), ""),
                    "candidates": [],
                }
                by_attribute[key] = matrix
            matrix["candidates"].append(
                {
                    "mpn": mpn,
                    "value": _text(row.get("Part B") or row.get("Candidate") or row.get("part_b")),
                    "source": _text(row.get("Part B source"), "Not stated"),
                    "valueClass": _text(row.get("Part B value class"), "unknown"),
                    "condition": _text(
                        row.get("Part B test condition") or row.get("Test condition"),
                        "Not stated",
                    ),
                    "assessment": _text(
                        row.get("Assessment") or row.get("assessment") or row.get("Status"),
                        "Needs data",
                    ),
                    "evidence": _text(
                        row.get("Evidence") or row.get("evidence") or row.get("Note"),
                        "No source note supplied.",
                    ),
                }
            )
    for matrix in by_attribute.values():
        present = {
            _normalize_part(cell.get("mpn")).casefold()
            for cell in matrix["candidates"]
        }
        for mpn in candidate_mpns:
            if mpn.casefold() in present:
                continue
            matrix["candidates"].append(
                {
                    "mpn": mpn,
                    "value": "—",
                    "source": "Not stated",
                    "valueClass": "unknown",
                    "condition": "Not stated",
                    "assessment": "Needs data",
                    "evidence": (
                        f"No attribute row was returned for {mpn} versus {part_a}."
                    ),
                }
            )
        order = {mpn.casefold(): index for index, mpn in enumerate(candidate_mpns)}
        matrix["candidates"].sort(
            key=lambda cell: order.get(_normalize_part(cell.get("mpn")).casefold(), 10_000)
        )
    return [by_attribute[attribute.casefold()] for attribute in attribute_order]


def rebuild_multi_source_records(
    part_a: str,
    verified_candidates: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Rebuild per-side source records only from verified pairwise evidence."""
    records: list[dict[str, Any]] = []
    if not verified_candidates:
        return records
    primary = verified_candidates[0]
    evidence = primary.get("evidence_sources")
    evidence = evidence if isinstance(evidence, dict) else {}
    part_a_sources = evidence.get("part_a") if isinstance(evidence.get("part_a"), list) else []
    records.append(
        {
            "side": "Part A",
            "mpn": _text(primary.get("part_a") or part_a, part_a),
            "sourceLabel": _text(primary.get("source_a"), "Not stated"),
            "retrievalNotes": [
                (
                    f"{_text(row.get('label') or row.get('name') or row.get('source') or row.get('url'), 'Source')}"
                    + (
                        f" · retrieved {_text(row.get('retrieved_at'), '')}"
                        if str(row.get("retrieved_at") or "").strip()
                        else ""
                    )
                )
                for row in part_a_sources
                if isinstance(row, dict)
            ],
            "fieldEvidence": [
                {
                    "attribute": _text(row.get("Attribute") or row.get("attribute")),
                    "value": _text(row.get("Part A") or row.get("Original") or row.get("part_a")),
                    "source": _text(row.get("Part A source"), "Not stated"),
                    "valueClass": _text(row.get("Part A value class"), "unknown"),
                    "condition": _text(
                        row.get("Part A test condition") or row.get("Test condition"),
                        "Not stated",
                    ),
                    "assessment": _text(
                        row.get("Assessment") or row.get("assessment") or row.get("Status"),
                        "Needs data",
                    ),
                    "evidence": _text(
                        row.get("Evidence") or row.get("evidence") or row.get("Note"),
                        "No source note supplied.",
                    ),
                }
                for row in _comparison_rows(primary)
            ],
        }
    )
    for entry in verified_candidates:
        mpn = _normalize_part(entry.get("part_b") or entry.get("mpn"))
        evidence = entry.get("evidence_sources")
        evidence = evidence if isinstance(evidence, dict) else {}
        part_b_sources = evidence.get("part_b") if isinstance(evidence.get("part_b"), list) else []
        records.append(
            {
                "side": f"Candidate · {mpn}",
                "mpn": _text(entry.get("part_b") or mpn, mpn),
                "sourceLabel": _text(entry.get("source_b"), "Not stated"),
                "retrievalNotes": [
                    (
                        f"{_text(row.get('label') or row.get('name') or row.get('source') or row.get('url'), 'Source')}"
                        + (
                            f" · retrieved {_text(row.get('retrieved_at'), '')}"
                            if str(row.get("retrieved_at") or "").strip()
                            else ""
                        )
                    )
                    for row in part_b_sources
                    if isinstance(row, dict)
                ],
                "fieldEvidence": [
                    {
                        "attribute": _text(row.get("Attribute") or row.get("attribute")),
                        "value": _text(
                            row.get("Part B") or row.get("Candidate") or row.get("part_b")
                        ),
                        "source": _text(row.get("Part B source"), "Not stated"),
                        "valueClass": _text(row.get("Part B value class"), "unknown"),
                        "condition": _text(
                            row.get("Part B test condition") or row.get("Test condition"),
                            "Not stated",
                        ),
                        "assessment": _text(
                            row.get("Assessment") or row.get("assessment") or row.get("Status"),
                            "Needs data",
                        ),
                        "evidence": _text(
                            row.get("Evidence") or row.get("evidence") or row.get("Note"),
                            "No source note supplied.",
                        ),
                    }
                    for row in _comparison_rows(entry)
                ],
            }
        )
    return records


def rebuild_multi_snapshot_from_candidates(
    *,
    part_a: str,
    part_b: str,
    analysis_id: str | None,
    verified_candidates: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Assemble a trusted multi snapshot exclusively from verified pairwise payloads."""
    if len(verified_candidates) < 2:
        raise ValueError("multi snapshot rebuild requires at least two verified candidates")
    primary = dict(verified_candidates[0])
    candidate_mpns = [
        _normalize_part(entry.get("part_b") or entry.get("mpn"))
        for entry in verified_candidates
    ]
    rebuilt = {
        key: primary.get(key)
        for key in SNAPSHOT_CONTENT_KEYS
    }
    rebuilt.update(
        {
            "ok": True,
            "part_a": _normalize_part(part_a),
            "part_b": _normalize_part(part_b),
            "analysis_id": _normalize_analysis_id(analysis_id or primary.get("analysis_id")),
            "multi_candidate_mpns": candidate_mpns,
            "multi_matrix": rebuild_multi_matrix(part_a, verified_candidates),
            "multi_source_records": rebuild_multi_source_records(part_a, verified_candidates),
            # Preserve verified pairwise payloads (tokens included) for audit.
            "candidate_snapshots": [dict(entry) for entry in verified_candidates],
            "snapshot_aggregate_rebuilt": True,
        }
    )
    return rebuilt


def _collect_verified_multi_candidates(
    snapshot: Mapping[str, Any],
    *,
    workspace_id: str,
    user_id: str | None,
    analysis_id: str | None,
    part_a: str,
    part_b: str,
    now: int | None = None,
) -> list[Mapping[str, Any]] | None:
    """Return verified candidate snapshots, or None when multi reuse must fail closed."""
    candidates = snapshot.get("candidate_snapshots")
    if not isinstance(candidates, list) or len(candidates) < 2:
        return None
    verified: list[Mapping[str, Any]] = []
    for entry in candidates:
        if not isinstance(entry, Mapping):
            return None
        candidate_mpn = _normalize_part(entry.get("part_b") or entry.get("mpn"))
        if not candidate_mpn:
            return None
        if not _verify_pairwise_snapshot_token(
            entry,
            workspace_id=workspace_id,
            user_id=user_id,
            analysis_id=analysis_id,
            part_a=part_a,
            part_b=candidate_mpn,
            now=now,
        ):
            return None
        verified.append(entry)
    if _normalize_part(part_b).casefold() != _normalize_part(
        verified[0].get("part_b") or verified[0].get("mpn")
    ).casefold():
        return None
    if _normalize_part(snapshot.get("part_a")).casefold() != _normalize_part(part_a).casefold():
        return None
    request_aid = _normalize_analysis_id(analysis_id)
    snapshot_aid = _normalize_analysis_id(snapshot.get("analysis_id"))
    if request_aid and snapshot_aid and request_aid != snapshot_aid:
        return None
    return verified


def verify_multi_candidate_snapshot(
    snapshot: Mapping[str, Any],
    *,
    workspace_id: str,
    user_id: str | None,
    analysis_id: str | None,
    part_a: str,
    part_b: str,
    now: int | None = None,
) -> bool:
    """True when every candidate token verifies for this caller/BOM/part identities."""
    return (
        _collect_verified_multi_candidates(
            snapshot,
            workspace_id=workspace_id,
            user_id=user_id,
            analysis_id=analysis_id,
            part_a=part_a,
            part_b=part_b,
            now=now,
        )
        is not None
    )


def verify_snapshot_for_reuse(
    snapshot: Mapping[str, Any] | None,
    *,
    workspace_id: str,
    user_id: str | None,
    analysis_id: str | None,
    part_a: str,
    part_b: str,
    now: int | None = None,
) -> bool:
    """True only when the snapshot token(s) bind this caller and evidence contents."""
    return (
        materialize_snapshot_for_reuse(
            snapshot,
            workspace_id=workspace_id,
            user_id=user_id,
            analysis_id=analysis_id,
            part_a=part_a,
            part_b=part_b,
            now=now,
        )
        is not None
    )


def materialize_snapshot_for_reuse(
    snapshot: Mapping[str, Any] | None,
    *,
    workspace_id: str,
    user_id: str | None,
    analysis_id: str | None,
    part_a: str,
    part_b: str,
    now: int | None = None,
) -> dict[str, Any] | None:
    """Return a server-trusted snapshot for reuse, or None to force recompute.

    Multi-candidate assemblies never reuse client aggregate fields. When every
    candidate token verifies, the server rebuilds multi_matrix / source records
    and top-level evidence from those verified pairwise payloads only.
    """
    if not isinstance(snapshot, Mapping):
        return None
    candidates = snapshot.get("candidate_snapshots")
    if isinstance(candidates, list) and len(candidates) >= 2:
        verified = _collect_verified_multi_candidates(
            snapshot,
            workspace_id=workspace_id,
            user_id=user_id,
            analysis_id=analysis_id,
            part_a=part_a,
            part_b=part_b,
            now=now,
        )
        if verified is None:
            return None
        return rebuild_multi_snapshot_from_candidates(
            part_a=part_a,
            part_b=part_b,
            analysis_id=analysis_id,
            verified_candidates=verified,
        )
    if not _verify_pairwise_snapshot_token(
        snapshot,
        workspace_id=workspace_id,
        user_id=user_id,
        analysis_id=analysis_id,
        part_a=part_a,
        part_b=part_b,
        now=now,
    ):
        return None
    # Pairwise tokens only bind SNAPSHOT_CONTENT_KEYS. Copy only those
    # authenticated fields so unsigned multi_* aggregates cannot be smuggled
    # onto a valid pairwise reuse and persisted by /decision-records.
    trusted: dict[str, Any] = {
        "ok": True,
        "part_a": _normalize_part(part_a),
        "part_b": _normalize_part(part_b),
        "analysis_id": _normalize_analysis_id(
            analysis_id or snapshot.get("analysis_id")
        ),
    }
    for key in SNAPSHOT_CONTENT_KEYS:
        if key in snapshot:
            trusted[key] = snapshot.get(key)
    if "snapshot_token" in snapshot:
        trusted["snapshot_token"] = snapshot.get("snapshot_token")
    if "snapshot_binding" in snapshot:
        trusted["snapshot_binding"] = snapshot.get("snapshot_binding")
    return trusted


def server_verified_primary_evidence(
    comparison: Mapping[str, Any] | None,
    *,
    validation_checks: list[str] | None = None,
    required_approval_checks: set[str] | None = None,
) -> bool:
    """Derive verified_primary_evidence only from server comparison fields."""
    comparison = comparison or {}
    required = required_approval_checks or {
        "manufacturer_datasheet_reviewed",
        "package_pinout_verified",
        "electrical_limits_verified",
    }
    checks = set(validation_checks or [])
    checks_complete = required.issubset(checks)
    source_a = str(comparison.get("source_a") or "").casefold()
    source_b = str(comparison.get("source_b") or "").casefold()
    identity = comparison.get("datasheet_identity")
    identity = identity if isinstance(identity, dict) else {}
    identity_a = identity.get("part_a") if isinstance(identity.get("part_a"), dict) else {}
    identity_b = identity.get("part_b") if isinstance(identity.get("part_b"), dict) else {}
    identity_verified = bool(identity_a.get("verified")) and bool(identity_b.get("verified"))
    sources_resolved = (
        bool(source_a)
        and bool(source_b)
        and "unverified" not in source_a
        and "unverified" not in source_b
        and source_a not in {"", "missing", "none"}
        and source_b not in {"", "missing", "none"}
    )
    return bool(checks_complete and identity_verified and sources_resolved)

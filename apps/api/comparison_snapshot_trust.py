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
)

# Multi-candidate assembly fields bound during multi-snapshot verification.
MULTI_SNAPSHOT_CONTENT_KEYS: tuple[str, ...] = (
    "multi_candidate_mpns",
    "multi_matrix",
    "multi_source_records",
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


def _normalize_mpn_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        text = _normalize_part(value)
        if text:
            out.append(text)
    return out


def _multi_assembly_consistent(snapshot: Mapping[str, Any], candidate_mpns: list[str]) -> bool:
    """Require multi list/matrix/source records to reference only verified candidates."""
    listed = _normalize_mpn_list(snapshot.get("multi_candidate_mpns"))
    if [item.casefold() for item in listed] != [item.casefold() for item in candidate_mpns]:
        return False
    matrix = snapshot.get("multi_matrix")
    if matrix is not None:
        if not isinstance(matrix, list):
            return False
        allowed = {item.casefold() for item in candidate_mpns}
        for row in matrix:
            if not isinstance(row, dict):
                return False
            candidates = row.get("candidates")
            if not isinstance(candidates, list):
                return False
            for cell in candidates:
                if not isinstance(cell, dict):
                    return False
                mpn = _normalize_part(cell.get("mpn")).casefold()
                if mpn and mpn not in allowed:
                    return False
    records = snapshot.get("multi_source_records")
    if records is not None:
        if not isinstance(records, list):
            return False
        allowed = {item.casefold() for item in candidate_mpns}
        # First record is Part A; remaining candidate cards must match the verified set.
        candidate_records = [
            row for row in records
            if isinstance(row, dict) and str(row.get("side") or "").casefold().startswith("candidate")
        ]
        record_mpns = [_normalize_part(row.get("mpn")).casefold() for row in candidate_records]
        if set(record_mpns) - {""} != allowed:
            return False
    return True


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
    """Verify every candidate comparison token and multi-assembly binding."""
    candidates = snapshot.get("candidate_snapshots")
    if not isinstance(candidates, list) or len(candidates) < 2:
        return False
    candidate_mpns: list[str] = []
    for entry in candidates:
        if not isinstance(entry, Mapping):
            return False
        candidate_mpn = _normalize_part(entry.get("part_b") or entry.get("mpn"))
        if not candidate_mpn:
            return False
        if not _verify_pairwise_snapshot_token(
            entry,
            workspace_id=workspace_id,
            user_id=user_id,
            analysis_id=analysis_id,
            part_a=part_a,
            part_b=candidate_mpn,
            now=now,
        ):
            return False
        candidate_mpns.append(candidate_mpn)
    # Decision primary part_b must be the first verified candidate.
    if _normalize_part(part_b).casefold() != candidate_mpns[0].casefold():
        return False
    if _normalize_part(snapshot.get("part_a")).casefold() != _normalize_part(part_a).casefold():
        return False
    request_aid = _normalize_analysis_id(analysis_id)
    snapshot_aid = _normalize_analysis_id(snapshot.get("analysis_id"))
    if request_aid and snapshot_aid and request_aid != snapshot_aid:
        return False
    if not _multi_assembly_consistent(snapshot, candidate_mpns):
        return False
    # Presence of multi assembly keys is required so forged empty shells fail closed.
    for key in MULTI_SNAPSHOT_CONTENT_KEYS:
        if key not in snapshot:
            return False
    return True


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
    if not isinstance(snapshot, Mapping):
        return False
    candidates = snapshot.get("candidate_snapshots")
    if isinstance(candidates, list) and len(candidates) >= 2:
        return verify_multi_candidate_snapshot(
            snapshot,
            workspace_id=workspace_id,
            user_id=user_id,
            analysis_id=analysis_id,
            part_a=part_a,
            part_b=part_b,
            now=now,
        )
    return _verify_pairwise_snapshot_token(
        snapshot,
        workspace_id=workspace_id,
        user_id=user_id,
        analysis_id=analysis_id,
        part_a=part_a,
        part_b=part_b,
        now=now,
    )


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

"""Alternative Finder candidate classification, merging, and ranking."""

from __future__ import annotations

import re
from datetime import datetime, timezone

CLASS_VERIFIED_DIRECT = "Verified direct substitute"
CLASS_SUPPLIER_UPGRADE = "Supplier-listed upgrade"
CLASS_SUPPLIER_SIMILAR = "Supplier-listed similar"
CLASS_ORDERING_EQUIVALENT = "Same-manufacturer ordering-code equivalent"
CLASS_SPEC_MATCHED = "Spec-matched alternative — engineering review required"
CLASS_CATALOG_INSUFFICIENT = "Catalog candidate — insufficient evidence for compatibility"

SUITABILITY_PREFERRED = "Preferred for new designs"
SUITABILITY_LIFECYCLE_VERIFY = "Lifecycle verification required"
SUITABILITY_SUSTAINING = "Sustaining-design review required"
SUITABILITY_SOURCE_DISCONTINUATION = "Source discontinuation risk"

EVIDENCE_DISTRIBUTOR_SUBSTITUTE = "distributor-listed substitute"
EVIDENCE_DISTRIBUTOR_CATALOG = "distributor catalog match"

SUBSTITUTE_TYPE_DIRECT = "Direct"
SUBSTITUTE_TYPE_UPGRADE = "Upgrade"
SUBSTITUTE_TYPE_SIMILAR = "Similar"
SUBSTITUTE_TYPE_UNKNOWN = "Unknown"

# Stronger claims first. Conservative merge picks the weakest claim present.
SUBSTITUTE_TYPE_STRENGTH = {
    SUBSTITUTE_TYPE_DIRECT: 3,
    SUBSTITUTE_TYPE_UPGRADE: 2,
    SUBSTITUTE_TYPE_SIMILAR: 1,
    SUBSTITUTE_TYPE_UNKNOWN: 0,
}

CLASSIFICATION_TIER = {
    CLASS_VERIFIED_DIRECT: 0,
    CLASS_SUPPLIER_UPGRADE: 1,
    CLASS_ORDERING_EQUIVALENT: 2,
    CLASS_SUPPLIER_SIMILAR: 3,
    CLASS_SPEC_MATCHED: 4,
    CLASS_CATALOG_INSUFFICIENT: 5,
}

# Lower sorts first. Active lifecycle-safe candidates outrank review/warning states.
SUITABILITY_TIER = {
    SUITABILITY_PREFERRED: 0,
    SUITABILITY_LIFECYCLE_VERIFY: 1,
    SUITABILITY_SUSTAINING: 2,
    SUITABILITY_SOURCE_DISCONTINUATION: 3,
}

# Review/warning-state scores cannot show an equal "Strong" badge (≥75).
WARNING_RECOMMENDATION_SCORE_CAP = 74
SUITABILITY_SCORE_PENALTY = {
    SUITABILITY_LIFECYCLE_VERIFY: 4,
    SUITABILITY_SUSTAINING: 5,
    SUITABILITY_SOURCE_DISCONTINUATION: 8,
}

_PACKAGING_SUFFIXES = ("CT", "TR", "TU", "DKR", "AUTO")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_mpn_for_comparison(mpn: str) -> str:
    """Conservative MPN key for deduplication; display MPN is preserved elsewhere."""
    return re.sub(r"[^A-Z0-9]", "", str(mpn or "").upper())


def _strip_packaging_suffix(mpn_key: str) -> str:
    for suffix in _PACKAGING_SUFFIXES:
        if mpn_key.endswith(suffix) and len(mpn_key) > len(suffix) + 6:
            return mpn_key[: -len(suffix)]
    return mpn_key


def is_ordering_code_variant(original_mpn: str, candidate_mpn: str) -> bool:
    """True when MPNs differ only by packaging/reel/order-code suffixes."""
    orig_key = normalize_mpn_for_comparison(original_mpn)
    cand_key = normalize_mpn_for_comparison(candidate_mpn)
    if not orig_key or not cand_key or orig_key == cand_key:
        return False

    stripped_orig = _strip_packaging_suffix(orig_key)
    stripped_cand = _strip_packaging_suffix(cand_key)
    if stripped_orig == stripped_cand:
        return True

    min_len = min(len(stripped_orig), len(stripped_cand))
    if min_len < 12:
        return False

    prefix = 0
    for left, right in zip(stripped_orig, stripped_cand):
        if left == right:
            prefix += 1
        else:
            break
    suffix_delta = abs(len(stripped_orig) - len(stripped_cand))
    return prefix >= min_len - 4 and prefix >= 12 and suffix_delta <= 6


def normalize_substitute_type(raw_value: object) -> str:
    """Normalize supplier substitute-type payloads to Direct/Upgrade/Similar/Unknown."""
    if isinstance(raw_value, dict):
        for key in ("SubstituteType", "Name", "Status", "Value", "Type"):
            nested = raw_value.get(key)
            if nested not in (None, ""):
                return normalize_substitute_type(nested)
        return SUBSTITUTE_TYPE_UNKNOWN

    text = str(raw_value or "").strip()
    if not text:
        return SUBSTITUTE_TYPE_UNKNOWN
    lowered = text.casefold()
    if lowered == "direct" or lowered.startswith("direct "):
        return SUBSTITUTE_TYPE_DIRECT
    if lowered == "upgrade" or lowered.startswith("upgrade "):
        return SUBSTITUTE_TYPE_UPGRADE
    if lowered == "similar" or lowered.startswith("similar "):
        return SUBSTITUTE_TYPE_SIMILAR
    if lowered in {"candidate", "unknown", "n/a", "none"}:
        return SUBSTITUTE_TYPE_UNKNOWN
    return SUBSTITUTE_TYPE_UNKNOWN


def conservative_substitute_type(types: list[str]) -> str:
    """Return the weakest exact relationship claim among supplier records."""
    normalized = [normalize_substitute_type(value) for value in types]
    known = [value for value in normalized if value != SUBSTITUTE_TYPE_UNKNOWN]
    if not known:
        return SUBSTITUTE_TYPE_UNKNOWN
    return min(known, key=lambda value: SUBSTITUTE_TYPE_STRENGTH.get(value, 0))


def build_supplier_relationship_evidence(
    *,
    supplier: str,
    original_mpn: str,
    candidate_mpn: str,
    substitute_type: object,
    supplier_part_id: str = "",
    source_url: str = "",
    evidence_type: str = "",
) -> dict[str, str]:
    """Build one exact per-pair supplier relationship evidence record."""
    normalized_type = normalize_substitute_type(substitute_type)
    source = str(supplier or "").strip()
    return {
        "supplier": source,
        "supplier_part_id": str(supplier_part_id or "").strip(),
        "original_mpn": str(original_mpn or "").strip(),
        "candidate_mpn": str(candidate_mpn or "").strip(),
        "substitute_type": normalized_type,
        "raw_substitute_type": str(substitute_type or "").strip()
        if not isinstance(substitute_type, dict)
        else normalize_substitute_type(substitute_type),
        "source_url": str(source_url or "").strip(),
        "evidence_type": str(evidence_type or "").strip(),
        "summary": (
            f"{source} substitute type: {normalized_type}"
            if source and normalized_type != SUBSTITUTE_TYPE_UNKNOWN
            else (
                f"{source} relationship evidence unavailable"
                if source
                else "Supplier relationship evidence unavailable"
            )
        ),
    }


def _evidence_identity_key(row: dict) -> tuple:
    """Return the displayed relationship identity for one evidence record.

    SKU/package variants of the same supplier relationship (different DigiKey
    product numbers or product URLs) are the same displayed claim and must
    render once. Distinct suppliers or substitute types stay separate.
    """
    return (
        normalize_mpn_for_comparison(str(row.get("original_mpn") or "")),
        normalize_mpn_for_comparison(str(row.get("candidate_mpn") or "")),
        str(row.get("supplier") or "").strip().casefold(),
        str(row.get("substitute_type") or "").strip().casefold(),
    )


def deduplicate_evidence_rows(evidence_rows: list[dict] | None) -> list[dict]:
    """Return a deduplicated list of supplier relationship evidence records.

    Records are deduplicated by displayed relationship identity
    (original_mpn, candidate_mpn, supplier, substitute_type). Insertion order is
    preserved; later duplicates are dropped.
    """
    rows = [row for row in (evidence_rows or []) if isinstance(row, dict)]
    seen: set[tuple] = set()
    result = []
    for row in rows:
        key = _evidence_identity_key(row)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def relationship_evidence_summary(evidence_rows: list[dict] | None) -> str:
    """Build a concise, deduplicated supplier relationship summary string.

    Each unique relationship renders once as plain text without raw URLs.
    The source URL is omitted from the summary text; callers should render it
    as a separate link (use ``relationship_evidence_link_pairs`` for that).
    """
    rows = deduplicate_evidence_rows(evidence_rows)
    if not rows:
        return "No exact supplier substitute relationship was retained for this candidate."
    summaries = []
    for row in rows:
        summary = str(row.get("summary") or "").strip()
        if summary:
            summaries.append(summary)
    return " · ".join(summaries) if summaries else (
        "No exact supplier substitute relationship was retained for this candidate."
    )


def relationship_evidence_link_pairs(
    evidence_rows: list[dict] | None,
) -> list[tuple[str, str]]:
    """Return (label, url) pairs for clickable supplier reference links.

    Deduplicates by identity key; only rows with a non-empty source_url are
    included. Each pair is suitable for rendering as one clean hyperlink.
    """
    rows = deduplicate_evidence_rows(evidence_rows)
    pairs: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for row in rows:
        source_url = str(row.get("source_url") or "").strip()
        if not source_url or source_url in seen_urls:
            continue
        seen_urls.add(source_url)
        supplier = str(row.get("supplier") or "").strip() or "Supplier"
        pairs.append((f"View {supplier} reference", source_url))
    return pairs


def pair_relationship_evidence_rows(
    result: dict,
    *,
    original_mpn: str,
    candidate_mpn: str = "",
) -> list[dict]:
    """Return evidence rows that describe this original/candidate pair only."""
    orig_key = normalize_mpn_for_comparison(original_mpn)
    cand_key = normalize_mpn_for_comparison(
        candidate_mpn or result.get("manufacturer_part_number") or result.get("Alternative Part") or ""
    )
    rows = result.get("supplier_relationship_evidence") or result.get(
        "Supplier Relationship Evidence"
    )
    matched: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        row_orig = normalize_mpn_for_comparison(str(row.get("original_mpn") or ""))
        row_cand = normalize_mpn_for_comparison(str(row.get("candidate_mpn") or ""))
        if orig_key and row_orig and row_orig != orig_key:
            continue
        if cand_key and row_cand and row_cand != cand_key:
            continue
        if orig_key and not row_orig:
            continue
        if cand_key and not row_cand:
            continue
        matched.append(row)
    return matched


def has_exact_direct_relationship(
    result: dict,
    *,
    original_mpn: str,
    candidate_mpn: str = "",
) -> bool:
    """True when this pair has a concrete distributor Direct relationship record."""
    for row in pair_relationship_evidence_rows(
        result, original_mpn=original_mpn, candidate_mpn=candidate_mpn
    ):
        if normalize_substitute_type(row.get("substitute_type")) != SUBSTITUTE_TYPE_DIRECT:
            continue
        evidence = str(row.get("evidence_type") or result.get("evidence_type") or "").strip().casefold()
        if evidence == EVIDENCE_DISTRIBUTOR_SUBSTITUTE:
            return True
    return False


def classify_from_supplier_evidence(
    result: dict,
    *,
    original_mpn: str,
    original_manufacturer: str = "",
) -> str:
    """Initial classification from exact supplier relationship evidence only.

    Direct/Upgrade/Similar require an exact distributor substitute relationship
    record. Spec comparison, package, manufacturer, and MPN similarity never
    create a Verified direct substitute label. Verified Direct additionally
    requires a pair-scoped Direct evidence record for the original and candidate.
    """
    candidate_mpn = str(
        result.get("manufacturer_part_number") or result.get("Alternative Part") or ""
    )
    pair_rows = pair_relationship_evidence_rows(
        result, original_mpn=original_mpn, candidate_mpn=candidate_mpn
    )
    evidence = str(result.get("evidence_type") or "").strip().casefold()
    substitute_type = normalize_substitute_type(
        result.get("substitute_type")
        or result.get("Substitute Type")
        or ""
    )
    relationship_rows = result.get("supplier_relationship_evidence") or result.get(
        "Supplier Relationship Evidence"
    )
    if pair_rows:
        substitute_type = conservative_substitute_type(
            [str(row.get("substitute_type") or "") for row in pair_rows]
        )
        if any(
            str(row.get("evidence_type") or "").strip().casefold() == EVIDENCE_DISTRIBUTOR_SUBSTITUTE
            for row in pair_rows
        ):
            evidence = EVIDENCE_DISTRIBUTOR_SUBSTITUTE
        if (
            evidence == EVIDENCE_DISTRIBUTOR_SUBSTITUTE
            and substitute_type == SUBSTITUTE_TYPE_DIRECT
            and has_exact_direct_relationship(
                result, original_mpn=original_mpn, candidate_mpn=candidate_mpn
            )
        ):
            return CLASS_VERIFIED_DIRECT
    elif isinstance(relationship_rows, list) and relationship_rows:
        # Evidence exists but none of it describes this original/candidate pair.
        substitute_type = SUBSTITUTE_TYPE_UNKNOWN
        evidence = str(result.get("evidence_type") or "").strip().casefold()
        if evidence == EVIDENCE_DISTRIBUTOR_SUBSTITUTE:
            evidence = EVIDENCE_DISTRIBUTOR_CATALOG

    # Top-level Substitute Type / Evidence Type alone must never create Verified
    # Direct. Only an exact original→candidate pair evidence row may do that.
    if evidence == EVIDENCE_DISTRIBUTOR_SUBSTITUTE and substitute_type == SUBSTITUTE_TYPE_UPGRADE:
        return CLASS_SUPPLIER_UPGRADE
    if evidence == EVIDENCE_DISTRIBUTOR_SUBSTITUTE and substitute_type == SUBSTITUTE_TYPE_SIMILAR:
        return CLASS_SUPPLIER_SIMILAR
    if evidence == EVIDENCE_DISTRIBUTOR_SUBSTITUTE:
        # Exact distributor relationship without a known Direct/Upgrade/Similar type.
        return CLASS_SPEC_MATCHED

    candidate_mpn = str(result.get("manufacturer_part_number") or "")
    manufacturer = str(result.get("manufacturer") or "").strip().casefold()
    original_mfr = str(original_manufacturer or "").strip().casefold()
    same_manufacturer = (
        bool(original_mfr)
        and bool(manufacturer)
        and (original_mfr == manufacturer or original_mfr in manufacturer or manufacturer in original_mfr)
    )
    if same_manufacturer and is_ordering_code_variant(original_mpn, candidate_mpn):
        return CLASS_ORDERING_EQUIVALENT

    if evidence == EVIDENCE_DISTRIBUTOR_CATALOG:
        return CLASS_CATALOG_INSUFFICIENT

    return CLASS_CATALOG_INSUFFICIENT


def refine_classification_after_comparison(
    classification: str,
    comparison_counts: dict,
) -> str:
    """Adjust catalog classifications using spec comparison without upgrading relationship claims."""
    if classification in {
        CLASS_VERIFIED_DIRECT,
        CLASS_SUPPLIER_UPGRADE,
        CLASS_SUPPLIER_SIMILAR,
        CLASS_ORDERING_EQUIVALENT,
    }:
        return classification

    matches = int(comparison_counts.get("Match", 0) or 0)
    differences = int(comparison_counts.get("Different", 0) or 0)
    needs_data = int(comparison_counts.get("Needs data", 0) or 0)

    if classification == CLASS_CATALOG_INSUFFICIENT:
        if differences == 0 and matches >= 3 and needs_data <= matches:
            return CLASS_SPEC_MATCHED
        return CLASS_CATALOG_INSUFFICIENT

    if classification == CLASS_SPEC_MATCHED and differences > 0:
        return CLASS_CATALOG_INSUFFICIENT

    return classification


def classify_recommendation_suitability(
    lifecycle: str,
    *,
    source: str = "",
) -> str:
    """Separate lifecycle/sourcing suitability from substitute-relationship evidence.

    Distributor-specific discontinuation is reported as source risk, not manufacturer EOL.
    Unknown/missing lifecycle must never be presented as preferred for new designs.
    """
    text = str(lifecycle or "").strip().casefold()

    if not text or text in {"unknown", "n/a", "none", "not available", "unavailable"}:
        return SUITABILITY_LIFECYCLE_VERIFY

    discontinued_markers = (
        "discontinued",
        "obsolete at",
        "no longer stocked",
        "end of life at",
    )
    if any(marker in text for marker in discontinued_markers):
        return SUITABILITY_SOURCE_DISCONTINUATION

    # Manufacturer EOL / obsolete is also a hard new-design warning, without
    # relabeling a DigiKey-only discontinuation as manufacturer EOL in copy.
    if any(marker in text for marker in ("obsolete", "end of life", "eol")):
        return SUITABILITY_SOURCE_DISCONTINUATION

    nfnd_markers = (
        "not for new designs",
        "not recommended for new",
        "nrnd",
        "nfd",
    )
    if any(marker in text for marker in nfnd_markers):
        return SUITABILITY_SUSTAINING

    if "active" in text:
        return SUITABILITY_PREFERRED

    # Non-active but unclassified statuses still need verification before new-design use.
    return SUITABILITY_LIFECYCLE_VERIFY


def apply_suitability_score_adjustment(
    recommendation_score: int,
    suitability: str,
) -> dict[str, int | str]:
    """Cap and penalize warning-state recommendation scores below Strong (≥75)."""
    score = max(0, min(int(recommendation_score or 0), 100))
    penalty = int(SUITABILITY_SCORE_PENALTY.get(suitability, 0) or 0)
    capped = False
    if suitability in SUITABILITY_SCORE_PENALTY:
        if score > WARNING_RECOMMENDATION_SCORE_CAP:
            score = WARNING_RECOMMENDATION_SCORE_CAP
            capped = True
        score = max(0, score - penalty)
    return {
        "recommendation_score": score,
        "suitability_penalty": penalty,
        "suitability_capped": 1 if capped else 0,
        "recommendation_suitability": suitability,
    }


def classification_sort_key(candidate: dict) -> tuple:
    classification = str(candidate.get("Classification") or CLASS_CATALOG_INSUFFICIENT)
    tier = CLASSIFICATION_TIER.get(classification, 99)
    suitability = str(
        candidate.get("Recommendation Suitability")
        or classify_recommendation_suitability(
            str(candidate.get("Lifecycle") or ""),
            source=str(candidate.get("Supplier") or candidate.get("Evidence Source") or ""),
        )
    )
    suitability_tier = SUITABILITY_TIER.get(suitability, 1)
    score = int(candidate.get("Recommendation Score", 0) or 0)
    return (tier, suitability_tier, -score)


_PRESERVED_RESULT_TIERS = frozenset({
    CLASS_VERIFIED_DIRECT,
    CLASS_SUPPLIER_UPGRADE,
    CLASS_ORDERING_EQUIVALENT,
})
LOWER_TIER_DISPLAY_CAP = 10


def apply_classification_result_cap(
    sorted_candidates: list[dict],
    *,
    lower_tier_cap: int = LOWER_TIER_DISPLAY_CAP,
) -> list[dict]:
    """Keep every high-confidence candidate; cap only lower-tier review rows."""
    preserved: list[dict] = []
    lower_tier: list[dict] = []
    for candidate in sorted_candidates:
        classification = str(candidate.get("Classification") or CLASS_CATALOG_INSUFFICIENT)
        if classification in _PRESERVED_RESULT_TIERS:
            preserved.append(candidate)
        else:
            lower_tier.append(candidate)
    return preserved + lower_tier[: max(0, int(lower_tier_cap))]


def _attach_or_merge_relationship_evidence(target: dict, source: dict) -> None:
    """Append source relationship evidence onto target without promoting claims."""
    incoming = []
    existing = target.get("supplier_relationship_evidence")
    if isinstance(existing, list):
        incoming.extend(row for row in existing if isinstance(row, dict))
    source_rows = source.get("supplier_relationship_evidence")
    if isinstance(source_rows, list):
        incoming.extend(row for row in source_rows if isinstance(row, dict))
    elif str(source.get("evidence_type") or "").strip().casefold() == EVIDENCE_DISTRIBUTOR_SUBSTITUTE:
        incoming.append(
            build_supplier_relationship_evidence(
                supplier=str(source.get("source") or ""),
                original_mpn=str(source.get("original_mpn") or ""),
                candidate_mpn=str(source.get("manufacturer_part_number") or ""),
                substitute_type=source.get("substitute_type"),
                supplier_part_id=str(source.get("digikey_part_number") or source.get("supplier_part_id") or ""),
                source_url=str(source.get("product_detail_url") or source.get("source_url") or ""),
                evidence_type=str(source.get("evidence_type") or ""),
            )
        )

    deduped: list[dict] = []
    seen_keys: set[tuple] = set()
    for row in incoming:
        key = _evidence_identity_key(row)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(row)

    if deduped:
        target["supplier_relationship_evidence"] = deduped
        conservative = conservative_substitute_type(
            [str(row.get("substitute_type") or "") for row in deduped]
        )
        # Never promote an existing weaker claim when merging another row.
        current = normalize_substitute_type(target.get("substitute_type"))
        if current == SUBSTITUTE_TYPE_UNKNOWN:
            target["substitute_type"] = conservative
        else:
            target["substitute_type"] = conservative_substitute_type([current, conservative])


def merge_discovery_candidates(
    explicit: list[dict],
    catalog: list[dict],
    *,
    original_mpn: str,
) -> list[dict]:
    """Merge explicit substitutes and catalog rows without leaking Direct evidence."""
    merged: list[dict] = []
    by_key: dict[str, dict] = {}
    orig_key = normalize_mpn_for_comparison(original_mpn)
    explicit_keys: set[str] = set()

    for row in explicit:
        mpn = str(row.get("manufacturer_part_number") or "").strip()
        key = normalize_mpn_for_comparison(mpn)
        if not mpn or key == orig_key:
            continue
        payload = dict(row)
        payload.setdefault("original_mpn", original_mpn)
        if key in by_key:
            # Same candidate seen again (e.g. multiple DigiKey package SKUs).
            # Keep both evidence rows and choose the conservative relationship.
            existing = by_key[key]
            _attach_or_merge_relationship_evidence(existing, payload)
            continue
        if not isinstance(payload.get("supplier_relationship_evidence"), list):
            if str(payload.get("evidence_type") or "").strip().casefold() == EVIDENCE_DISTRIBUTOR_SUBSTITUTE:
                payload["supplier_relationship_evidence"] = [
                    build_supplier_relationship_evidence(
                        supplier=str(payload.get("source") or ""),
                        original_mpn=str(payload.get("original_mpn") or original_mpn),
                        candidate_mpn=mpn,
                        substitute_type=payload.get("substitute_type"),
                        supplier_part_id=str(
                            payload.get("digikey_part_number")
                            or payload.get("supplier_part_id")
                            or ""
                        ),
                        source_url=str(
                            payload.get("product_detail_url") or payload.get("source_url") or ""
                        ),
                        evidence_type=str(payload.get("evidence_type") or ""),
                    )
                ]
            else:
                payload["supplier_relationship_evidence"] = []
        payload["substitute_type"] = normalize_substitute_type(payload.get("substitute_type"))
        by_key[key] = payload
        explicit_keys.add(key)
        merged.append(payload)

    for row in catalog:
        mpn = str(row.get("manufacturer_part_number") or "").strip()
        key = normalize_mpn_for_comparison(mpn)
        if not mpn or key == orig_key:
            continue
        if key in explicit_keys:
            # Catalog must not overwrite or inherit explicit Direct evidence.
            continue
        if key in by_key:
            continue
        payload = dict(row)
        payload.setdefault("original_mpn", original_mpn)
        payload["substitute_type"] = normalize_substitute_type(payload.get("substitute_type"))
        payload.setdefault("supplier_relationship_evidence", [])
        by_key[key] = payload
        merged.append(payload)

    return merged


def build_classification_recommendation(
    classification: str,
    substitute_type: str = "",
    *,
    suitability: str = "",
    lifecycle: str = "",
    source: str = "",
) -> str:
    resolved_suitability = str(suitability or "").strip() or classify_recommendation_suitability(
        lifecycle,
        source=source,
    )
    normalized_type = normalize_substitute_type(substitute_type) if substitute_type else ""
    if classification == CLASS_VERIFIED_DIRECT:
        if resolved_suitability == SUITABILITY_SOURCE_DISCONTINUATION:
            source_label = str(source or "the reporting distributor").strip() or "the reporting distributor"
            return (
                f"Supplier lists this as a direct substitute ({normalized_type or 'Direct'}), "
                f"but {source_label} reports discontinuation for this listing. "
                "It may be useful for sustaining an existing design, but should not be "
                "prioritized for a new design without review. This is distributor sourcing "
                "status, not automatic manufacturer end-of-life."
            )
        if resolved_suitability == SUITABILITY_SUSTAINING:
            return (
                f"Supplier lists this as a direct substitute ({normalized_type or 'Direct'}), "
                "but lifecycle status is Not For New Designs. "
                "It may be useful for sustaining an existing design, but should not be "
                "prioritized for a new design without review."
            )
        if resolved_suitability == SUITABILITY_LIFECYCLE_VERIFY:
            return (
                f"Supplier lists this as a direct substitute ({normalized_type or 'Direct'}), "
                "but lifecycle evidence is missing or unknown. "
                "Complete lifecycle verification before new-design approval. "
                "Do not treat this candidate as preferred for a new design until lifecycle is confirmed."
            )
        return (
            f"Supplier lists this as a direct substitute ({normalized_type or 'Direct'}). "
            "Confirm footprint, qualification, and datasheet compatibility before approval."
        )
    if classification == CLASS_SUPPLIER_UPGRADE:
        return (
            "Supplier lists this as an Upgrade substitute. Confirm whether the upgraded "
            "characteristics are acceptable for the design before approval."
        )
    if classification == CLASS_SUPPLIER_SIMILAR:
        return (
            "Supplier lists this as a Similar substitute. Engineering review is required "
            "before treating it as interchangeable."
        )
    if classification == CLASS_ORDERING_EQUIVALENT:
        return (
            "Same manufacturer part family with a packaging or ordering-code difference. "
            "Verify reel/tape and procurement requirements."
        )
    if classification == CLASS_SPEC_MATCHED:
        return (
            "Retrieved specifications support candidacy, but no verified direct-substitute "
            "relationship was returned. Engineering review is required."
        )
    return (
        "Catalog discovery only; insufficient evidence for compatibility. "
        "Verify all electrical, mechanical, and qualification requirements before use."
    )

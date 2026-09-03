"""Alternative Finder candidate classification, merging, and ranking."""

from __future__ import annotations

import re
from datetime import datetime, timezone

CLASS_VERIFIED_DIRECT = "Verified direct substitute"
CLASS_ORDERING_EQUIVALENT = "Same-manufacturer ordering-code equivalent"
CLASS_SPEC_MATCHED = "Spec-matched alternative — engineering review required"
CLASS_CATALOG_INSUFFICIENT = "Catalog candidate — insufficient evidence for compatibility"

SUITABILITY_PREFERRED = "Preferred for new designs"
SUITABILITY_LIFECYCLE_VERIFY = "Lifecycle verification required"
SUITABILITY_SUSTAINING = "Sustaining-design review required"
SUITABILITY_SOURCE_DISCONTINUATION = "Source discontinuation risk"

EVIDENCE_DISTRIBUTOR_SUBSTITUTE = "distributor-listed substitute"
EVIDENCE_DISTRIBUTOR_CATALOG = "distributor catalog match"

CLASSIFICATION_TIER = {
    CLASS_VERIFIED_DIRECT: 0,
    CLASS_ORDERING_EQUIVALENT: 1,
    CLASS_SPEC_MATCHED: 2,
    CLASS_CATALOG_INSUFFICIENT: 3,
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


def classify_from_supplier_evidence(
    result: dict,
    *,
    original_mpn: str,
    original_manufacturer: str = "",
) -> str:
    """Initial classification from supplier/manufacturer relationship evidence only."""
    evidence = str(result.get("evidence_type") or "").strip().casefold()
    substitute_type = str(result.get("substitute_type") or "").strip().casefold()

    if evidence == EVIDENCE_DISTRIBUTOR_SUBSTITUTE and substitute_type == "direct":
        return CLASS_VERIFIED_DIRECT

    if evidence == EVIDENCE_DISTRIBUTOR_SUBSTITUTE:
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
    """Adjust catalog classifications using spec comparison without upgrading to verified direct."""
    if classification == CLASS_VERIFIED_DIRECT:
        return classification
    if classification == CLASS_ORDERING_EQUIVALENT:
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
    CLASS_ORDERING_EQUIVALENT,
})
LOWER_TIER_DISPLAY_CAP = 10


def apply_classification_result_cap(
    sorted_candidates: list[dict],
    *,
    lower_tier_cap: int = LOWER_TIER_DISPLAY_CAP,
) -> list[dict]:
    """Keep every high-confidence candidate; cap only spec-matched and catalog rows."""
    preserved: list[dict] = []
    lower_tier: list[dict] = []
    for candidate in sorted_candidates:
        classification = str(candidate.get("Classification") or CLASS_CATALOG_INSUFFICIENT)
        if classification in _PRESERVED_RESULT_TIERS:
            preserved.append(candidate)
        else:
            lower_tier.append(candidate)
    return preserved + lower_tier[: max(0, int(lower_tier_cap))]


def merge_discovery_candidates(
    explicit: list[dict],
    catalog: list[dict],
    *,
    original_mpn: str,
) -> list[dict]:
    """Merge explicit substitutes and catalog rows; explicit evidence is never replaced."""
    merged: list[dict] = []
    seen: set[str] = set()
    orig_key = normalize_mpn_for_comparison(original_mpn)
    explicit_keys: set[str] = set()

    for row in explicit:
        mpn = str(row.get("manufacturer_part_number") or "").strip()
        key = normalize_mpn_for_comparison(mpn)
        if not mpn or key == orig_key or key in seen:
            continue
        seen.add(key)
        explicit_keys.add(key)
        merged.append(dict(row))

    for row in catalog:
        mpn = str(row.get("manufacturer_part_number") or "").strip()
        key = normalize_mpn_for_comparison(mpn)
        if not mpn or key == orig_key or key in seen:
            continue
        if key in explicit_keys:
            continue
        seen.add(key)
        merged.append(dict(row))

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
    if classification == CLASS_VERIFIED_DIRECT:
        if resolved_suitability == SUITABILITY_SOURCE_DISCONTINUATION:
            source_label = str(source or "the reporting distributor").strip() or "the reporting distributor"
            return (
                f"Supplier lists this as a direct substitute ({substitute_type or 'Direct'}), "
                f"but {source_label} reports discontinuation for this listing. "
                "It may be useful for sustaining an existing design, but should not be "
                "prioritized for a new design without review. This is distributor sourcing "
                "status, not automatic manufacturer end-of-life."
            )
        if resolved_suitability == SUITABILITY_SUSTAINING:
            return (
                f"Supplier lists this as a direct substitute ({substitute_type or 'Direct'}), "
                "but lifecycle status is Not For New Designs. "
                "It may be useful for sustaining an existing design, but should not be "
                "prioritized for a new design without review."
            )
        if resolved_suitability == SUITABILITY_LIFECYCLE_VERIFY:
            return (
                f"Supplier lists this as a direct substitute ({substitute_type or 'Direct'}), "
                "but lifecycle evidence is missing or unknown. "
                "Complete lifecycle verification before new-design approval. "
                "Do not treat this candidate as preferred for a new design until lifecycle is confirmed."
            )
        return (
            f"Supplier lists this as a direct substitute ({substitute_type or 'Direct'}). "
            "Confirm footprint, qualification, and datasheet compatibility before approval."
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

/** Pure checks for Find Replacement outcome + catalog vs explicit provider labels. */

const AUTHORITATIVE_FIT_MARKERS = [
  "manufacturer-datasheet",
  "uploaded-manufacturer-datasheet",
  "datasheet-backed",
  "engineering-verified",
  "authoritative fit",
  "authoritative-fit",
];

function candidateHasAuthoritativeFitEvidence(row) {
  if (
    row.authoritative_fit_evidence === true
    || row.engineering_fit_verified === true
    || row.datasheet_fit_verified === true
  ) {
    return true;
  }
  const evidenceText = [
    "evidence_class",
    "Evidence Class",
    "fit_evidence",
    "Fit Evidence",
    "fit",
    "Fit",
    "Evidence Source",
    "evidence_source",
    "Recommendation",
    "rationale",
  ]
    .map((key) => String(row[key] || ""))
    .join(" ")
    .toLowerCase();
  return AUTHORITATIVE_FIT_MARKERS.some((marker) => evidenceText.includes(marker));
}

function candidateHasVerifiedFit(row) {
  const fitText = ["fit", "Fit", "disposition", "Candidate Disposition"]
    .map((key) => String(row[key] || ""))
    .join(" ")
    .toLowerCase();
  if (fitText.includes("not qualified") || fitText.includes("qualification required")) {
    return false;
  }
  let claimsCompatible = false;
  for (const key of ["classification", "Classification", "category", "Category", "fit", "Fit"]) {
    const value = String(row[key] || "").trim().toLowerCase();
    if (!value) continue;
    if (value === "compatible" || value === "verified direct substitute") {
      claimsCompatible = true;
      break;
    }
    if (value.startsWith("compatible ")) {
      claimsCompatible = true;
      break;
    }
  }
  return claimsCompatible && candidateHasAuthoritativeFitEvidence(row);
}

function searchOutcomeLabel(outcome, explicitLabel, candidates) {
  const provided = String(explicitLabel || "").trim();
  const verified = Array.isArray(candidates)
    ? candidates.some((row) => candidateHasVerifiedFit(row))
    : false;
  if (
    provided
    && /verified replacements found/i.test(provided)
    && Array.isArray(candidates)
    && !verified
  ) {
    return "Supplier-listed candidates found — fit unverified";
  }
  if (provided) return provided;
  const key = String(outcome || "").trim();
  if (key === "success" || key === "candidates_found") {
    return verified
      ? "Verified replacements found"
      : "Supplier-listed candidates found — fit unverified";
  }
  if (key === "partial_success") {
    return verified
      ? "Partial success — verified replacements found"
      : "Partial success — fit unverified";
  }
  return key;
}

function providerRawCatalogCount(state) {
  if (state.catalog_raw_count !== undefined && state.catalog_raw_count !== null) {
    const raw = Number(state.catalog_raw_count);
    return Number.isFinite(raw) && raw >= 0 ? raw : null;
  }
  if (state.catalog_count !== undefined && state.catalog_count !== null) {
    const raw = Number(state.catalog_count);
    return Number.isFinite(raw) && raw >= 0 ? raw : null;
  }
  return null;
}

function providerRetainedCatalogCount(state) {
  if (state.catalog_retained_count === undefined || state.catalog_retained_count === null) {
    return null;
  }
  const retained = Number(state.catalog_retained_count);
  return Number.isFinite(retained) && retained >= 0 ? retained : null;
}

function providerExplicitSubstitutionCount(state) {
  if (state.explicit_retained_count !== undefined && state.explicit_retained_count !== null) {
    const retained = Number(state.explicit_retained_count);
    return Number.isFinite(retained) && retained >= 0 ? retained : null;
  }
  const explicit = Number(state.explicit_count);
  return Number.isFinite(explicit) && explicit >= 0 ? explicit : null;
}

function providerOutcomeLabel(state) {
  const values = ["lookup", "catalog", "substitutions", "family_search", "parametric_search"].map(
    (key) => String(state[key] || "").toLowerCase(),
  );
  const rawCount = providerRawCatalogCount(state);
  const retainedCount = providerRetainedCatalogCount(state);
  const explicitCount = providerExplicitSubstitutionCount(state);
  if (values.some((value) => value === "not_configured")) return "Not configured";
  if (values.some((value) => value === "timeout")) return "Timed out";
  if (values.some((value) => value === "error" || value === "rate_limited")) return "Failed";
  if (values.some((value) => value === "part_not_found" || value === "no_results")) {
    return "No results";
  }
  const parts = [];
  if (rawCount !== null && rawCount > 0) {
    if (retainedCount !== null && retainedCount !== rawCount) {
      parts.push(`${rawCount} raw catalog matches · ${retainedCount} retained`);
    } else {
      parts.push(`${rawCount} raw catalog matches`);
    }
  }
  if (explicitCount !== null && explicitCount > 0) {
    parts.push(
      `${explicitCount} supplier substitution${explicitCount === 1 ? "" : "s"}`,
    );
  } else if (explicitCount === 0 && Number(state.explicit_count) > 0) {
    parts.push("0 retained supplier substitutions");
  }
  if (parts.length) return parts.join("; ");
  if (
    values.some(
      (value) =>
        value === "ok" || value === "available" || value === "searched" || value === "partial",
    )
  ) {
    return "Searched — no results";
  }
  return "Searched";
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const lm358Rows = Array.from({ length: 10 }, (_, idx) => ({
  mpn: `ALT-${idx}`,
  classification: "Needs verification",
  fit: "supplier-listed candidate; qualification required",
}));

assert(
  searchOutcomeLabel("success", "Verified replacements found", lm358Rows)
    === "Supplier-listed candidates found — fit unverified",
  "LM358N-style verified banner must be corrected when no Compatible row exists",
);

assert(
  searchOutcomeLabel("success", "", [{ classification: "Compatible" }])
    === "Supplier-listed candidates found — fit unverified",
  "Compatible classification alone must not claim Verified without authoritative evidence",
);

assert(
  searchOutcomeLabel("success", "", [{
    classification: "Compatible",
    fit: "compatible",
    authoritative_fit_evidence: true,
    evidence_class: "manufacturer-datasheet",
  }]) === "Verified replacements found",
  "Authoritative datasheet fit evidence may keep verified wording",
);

assert(
  searchOutcomeLabel("success", "Verified replacements found", [{
    classification: "Compatible",
    fit: "supplier-listed candidate; qualification required",
  }]) === "Supplier-listed candidates found — fit unverified",
  "Compatible classification with qualification-required fit must not stay Verified",
);

assert(
  providerOutcomeLabel({
    catalog: "ok",
    catalog_count: 19,
    catalog_raw_count: 19,
    catalog_retained_count: 1,
  }) === "19 raw catalog matches · 1 retained",
  "AM29-style raw vs retained must both appear",
);

assert(
  providerOutcomeLabel({
    catalog: "ok",
    substitutions: "ok",
    catalog_raw_count: 0,
    catalog_count: 0,
    catalog_retained_count: 0,
    explicit_count: 2,
    explicit_retained_count: 2,
  }) === "2 supplier substitutions",
  "Explicit-only DigiKey must never say raw catalog matches",
);

assert(
  providerOutcomeLabel({
    catalog: "ok",
    substitutions: "ok",
    catalog_raw_count: 3,
    catalog_retained_count: 1,
    explicit_retained_count: 2,
  }) === "3 raw catalog matches · 1 retained; 2 supplier substitutions",
  "Mixed catalog + explicit must keep categories separate",
);

assert(
  providerOutcomeLabel({
    catalog: "ok",
    substitutions: "ok",
    catalog_raw_count: 0,
    explicit_count: 2,
    explicit_retained_count: 0,
  }) === "0 retained supplier substitutions",
  "Zero retained substitutions must not fall back to raw explicit_count",
);

assert(
  providerExplicitSubstitutionCount({
    explicit_count: 5,
    explicit_retained_count: 0,
  }) === 0,
  "explicit_retained_count=0 must be honored",
);

assert(
  providerRawCatalogCount({
    explicit_count: 2,
    lead_count: 5,
    result_count: 7,
  }) === null,
  "Absent catalog fields must not fall back to explicit/lead/result counts",
);

assert(
  providerOutcomeLabel({
    catalog: "ok",
    catalog_count: 0,
    catalog_raw_count: 0,
  }) === "Searched — no results",
  "Zero-hit provider stays no-results",
);

console.log("findReplacementOutcomeCounts checks OK");

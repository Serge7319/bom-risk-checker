/** Pure checks for Find Replacement outcome + raw/retained provider labels. */

function candidateHasVerifiedFit(row) {
  for (const key of ["classification", "Classification", "category", "Category", "fit", "Fit"]) {
    const value = String(row[key] || "").trim().toLowerCase();
    if (!value) continue;
    if (value === "compatible" || value === "verified direct substitute") return true;
    if (value.startsWith("compatible ")) return true;
  }
  return false;
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

function providerOutcomeLabel(state) {
  const values = ["lookup", "catalog", "substitutions", "family_search", "parametric_search"].map(
    (key) => String(state[key] || "").toLowerCase(),
  );
  const raw = Number(state.catalog_raw_count ?? state.catalog_count ?? 0);
  const retained =
    state.catalog_retained_count === undefined || state.catalog_retained_count === null
      ? null
      : Number(state.catalog_retained_count);
  if (values.some((value) => value === "ok" || value === "available" || value === "searched")) {
    if (raw > 0) {
      if (retained !== null && Number.isFinite(retained) && retained !== raw) {
        return `${raw} raw catalog matches · ${retained} retained`;
      }
      return `${raw} raw catalog matches`;
    }
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
    === "Verified replacements found",
  "Compatible evidence may keep verified wording",
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
    catalog_count: 0,
    catalog_raw_count: 0,
  }) === "Searched — no results",
  "Zero-hit provider stays no-results",
);

console.log("findReplacementOutcomeCounts checks OK");

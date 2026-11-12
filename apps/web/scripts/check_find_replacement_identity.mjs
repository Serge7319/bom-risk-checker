/** Deterministic checks for Find Replacement identity UI helpers. */
import assert from "node:assert/strict";

function shouldShowIdentityDisambiguation(result) {
  if (!result) return false;
  if (Boolean(result.identity_review_only)) return true;
  const status = String(
    result.status || result.outcome || result.identity_status || "",
  ).toLowerCase();
  if (status.includes("ambiguous")) return true;
  const choices = result.identity_choices;
  return Array.isArray(choices) && choices.length > 0;
}

function shouldShowIdentityRetryButton(opts) {
  const choice = String(opts.choiceManufacturer || "").trim();
  if (!choice) return false;
  if (!opts.identityReviewOnly) return true;
  const typed = String(opts.typedManufacturer || "").trim();
  return typed.length === 0 || choice.toLowerCase() !== typed.toLowerCase();
}

assert.equal(
  shouldShowIdentityDisambiguation({ identity_choices: [] }),
  false,
  "empty choices must not show banner",
);
assert.equal(
  shouldShowIdentityDisambiguation({
    identity_review_only: true,
    identity_choices: [],
  }),
  true,
);
assert.equal(
  shouldShowIdentityDisambiguation({
    status: "identity_ambiguous",
    identity_choices: [{ manufacturer: "TI" }],
  }),
  true,
);
assert.equal(
  shouldShowIdentityRetryButton({
    identityReviewOnly: true,
    typedManufacturer: "AMD",
    choiceManufacturer: "AMD",
  }),
  false,
  "must not re-offer same unverified typed brand",
);
assert.equal(
  shouldShowIdentityRetryButton({
    identityReviewOnly: true,
    typedManufacturer: "AMD",
    choiceManufacturer: "Infineon",
  }),
  true,
  "must offer retry as other lineage brand",
);
assert.equal(
  shouldShowIdentityRetryButton({
    identityReviewOnly: false,
    typedManufacturer: "",
    choiceManufacturer: "TI",
  }),
  true,
);

console.log("findReplacementIdentity checks OK");

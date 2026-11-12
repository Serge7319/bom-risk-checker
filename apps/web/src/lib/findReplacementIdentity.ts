/** Pure helpers for Find Replacement identity UI (unit-testable without React). */

export function shouldShowIdentityDisambiguation(
  result: Record<string, unknown> | null | undefined,
): boolean {
  if (!result) return false;
  if (Boolean(result.identity_review_only)) return true;
  const status = String(
    result.status || result.outcome || result.identity_status || "",
  ).toLowerCase();
  if (status.includes("ambiguous")) return true;
  const choices = result.identity_choices;
  return Array.isArray(choices) && choices.length > 0;
}

export function shouldShowIdentityRetryButton(opts: {
  identityReviewOnly: boolean;
  typedManufacturer: string;
  choiceManufacturer: string;
}): boolean {
  const choice = String(opts.choiceManufacturer || "").trim();
  if (!choice) return false;
  if (!opts.identityReviewOnly) return true;
  const typed = String(opts.typedManufacturer || "").trim();
  // Do not re-offer the same unverified typed brand (avoids identity prompt loop).
  return typed.length === 0 || choice.toLowerCase() !== typed.toLowerCase();
}

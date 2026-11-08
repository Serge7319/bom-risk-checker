/** Shared decision-form validation for Compare Parts approvals. */

export const OVERRIDE_RATIONALE_MIN_LEN = 20;

const TRIVIAL_OVERRIDE_RATIONALES = new Set([
  "ok",
  "okay",
  "yes",
  "y",
  "approved",
  "approve",
  "n/a",
  "na",
  "none",
  "same",
  "see above",
  "as above",
  "as discussed",
  ".",
  "..",
  "...",
]);

/** Return an error message when the override rationale is not meaningful. */
export function validateOverrideRationale(
  overrideRationale: string,
  generalRationale = "",
): string | null {
  const text = overrideRationale.trim();
  if (!text) {
    return "Provide a specific override rationale for approving despite comparison conflicts.";
  }
  if (text.length > 3000) {
    return "Override rationale must be 3,000 characters or fewer.";
  }
  const lowered = text.toLowerCase();
  if (TRIVIAL_OVERRIDE_RATIONALES.has(lowered)) {
    return "Override rationale must be a specific engineering explanation, not a placeholder.";
  }
  if (text.length < OVERRIDE_RATIONALE_MIN_LEN) {
    return `Override rationale must be at least ${OVERRIDE_RATIONALE_MIN_LEN} characters and explain why the conflicts are acceptable.`;
  }
  const general = generalRationale.trim();
  if (general && lowered === general.toLowerCase()) {
    return "Override rationale must differ from the general decision rationale.";
  }
  return null;
}

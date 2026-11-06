/** Convert internal evidence tags into labels that make sense to engineers. */
export function evidenceSourceLabel(
  value: unknown,
  fallback = "Synthetic analysis",
): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw) return fallback;
  if (/synthetic|preview/i.test(raw)) return "Synthetic analysis";
  return raw.replace(/\bapi\b/gi, "source").replace(/[-_]+/g, " ");
}

export function analysisModeLabel(value: unknown): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw || /synthetic|preview/i.test(raw)) return "Synthetic analysis";
  return raw.replace(/[-_]+/g, " ");
}

/** Hide internal deployment labels when they leak into an account workspace name. */
export function workspaceDisplayName(value: unknown): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw || /migration|sandbox|test(?:\s|$)/i.test(raw)) return "Engineering workspace";
  return raw;
}


/** Convert internal evidence tags into labels that make sense to engineers. */
const OPAQUE_IDENTIFIER = /^[0-9a-f]{8}-(?:[a-z0-9]{2,12}-){1,}[a-z0-9]{0,16}(?:\.{3,})?$/i;
const OPAQUE_IDENTIFIER_IN_TEXT = /\b[0-9a-f]{8}-(?:[a-z0-9]{2,12}-){1,}[a-z0-9]{0,16}(?:\.{3,})?(?=$|[^\w])/gi;

export function isOpaqueIdentifier(value: unknown): boolean {
  return typeof value === "string" && OPAQUE_IDENTIFIER.test(value.trim());
}

/** Remove UUID-like internal references from user-visible text. */
export function cleanUserText(value: unknown): string {
  return typeof value === "string"
    ? value.replace(OPAQUE_IDENTIFIER_IN_TEXT, "record reference").replace(/[ \t]{2,}/g, " ").trim()
    : "";
}

/** Recover visible field text from legacy KiCad IPC object stringifications. */
export function cleanKiCadFieldText(value: unknown): string {
  if (typeof value !== "string") return "";
  const raw = value.trim();
  const match = raw.match(/^BoardText\(value=([\s\S]*?),\s*position=Vector2\([^)]*\),\s*layer=.*\)$/);
  if (!match) return raw;
  let visible = match[1].trim();
  if (visible.length >= 2 && visible[0] === visible.at(-1) && (visible[0] === "'" || visible[0] === '"')) {
    visible = visible.slice(1, -1);
  }
  return visible;
}

/** Use a useful label when a missing name would otherwise expose a database key. */
export function userFacingLabel(value: unknown, fallback: string): string {
  const raw = typeof value === "string" ? value.trim() : "";
  return !raw || isOpaqueIdentifier(raw) ? fallback : cleanUserText(raw) || fallback;
}

/** Keep server errors useful while removing internal identifiers and field names. */
export function userFacingError(value: unknown, fallback: string): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw) return fallback;
  const safe = cleanUserText(raw.replace(/\b(?:analysis|workspace|project|report|request|trace)_?id\s*[:=]\s*[^\s,;]+/gi, "selected record"))
    .replace(/\s{2,}/g, " ")
    .trim();
  return safe || fallback;
}

export function evidenceSourceLabel(
  value: unknown,
  fallback = "Synthetic analysis",
): string {
  const raw = cleanUserText(value);
  if (!raw) return fallback;
  if (/synthetic|preview/i.test(raw)) return "Synthetic analysis";
  return raw.replace(/\bapi\b/gi, "source").replace(/[-_]+/g, " ");
}

export function analysisModeLabel(value: unknown): string {
  const raw = cleanUserText(value);
  if (!raw || /synthetic|preview/i.test(raw)) return "Synthetic analysis";
  return raw.replace(/[-_]+/g, " ");
}

/** Hide internal deployment labels when they leak into an account workspace name. */
export function workspaceDisplayName(value: unknown): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw || isOpaqueIdentifier(raw) || /migration|sandbox|test(?:\s|$)/i.test(raw)) return "Engineering workspace";
  return cleanUserText(raw) || "Engineering workspace";
}


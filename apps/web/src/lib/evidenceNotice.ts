/** Classify API gap/disclosure strings for restrained UI presentation. */

export type EvidenceNoticeTone = "critical" | "context" | "service" | "hide";

const SERVICE_RE =
  /monitoring email|billing checkout|design-tool connector|connectors are not connected|stripe checkout|alert email|scheduler/i;

const CONTEXT_RE =
  /based on saved|from saved analys|workspace'?s? saved|computed from saved|calculated from this workspace|needs saved analysis|analyze a bom first|no analyzed bom yet|parts from saved|current workspace|temporary file storage|local preview|durable storage/i;

const CRITICAL_RE =
  /synthetic|offline|estimate|not (a )?live|not distributor|not supplier|unverified|unable to confirm|incomplete|credentials|live supplier|drop-in|compatibility|sample evidence|preview unit price|not connected|manufacturer datasheet|fit is not confirmed/i;

export function classifyEvidenceNotice(text: unknown): EvidenceNoticeTone {
  const raw = typeof text === "string" ? text.trim() : "";
  if (!raw) return "hide";
  // Service availability belongs in Settings / the owning workflow, not as a page warning.
  if (SERVICE_RE.test(raw) && !/synthetic|estimate|offline catalog|drop-in/i.test(raw)) {
    return "service";
  }
  if (CRITICAL_RE.test(raw)) return "critical";
  if (CONTEXT_RE.test(raw)) return "context";
  // Default: keep visible but as context unless it looks like a hard limitation.
  if (/not |cannot |missing|disabled|unavailable/i.test(raw)) return "critical";
  return "context";
}

export function compactContextLabel(text: string): string {
  const t = text.trim();
  if (/saved analys/i.test(t) && /only|workspace/i.test(t)) {
    return "Based on saved analyses in this workspace";
  }
  if (/analyze a bom first|no analyzed bom|no saved analys/i.test(t)) {
    return "Requires a saved BOM analysis";
  }
  if (/impact is computed from saved/i.test(t)) {
    return "Based on saved analyses";
  }
  if (/portfolio is calculated/i.test(t)) {
    return "Based on saved analyses in this workspace";
  }
  return t.length > 120 ? `${t.slice(0, 117)}…` : t;
}

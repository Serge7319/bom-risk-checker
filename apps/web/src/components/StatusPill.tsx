type StatusKind = "risk" | "lifecycle" | "verification";
type StatusTone = "red" | "amber" | "green" | "blue" | "gray";

function statusTone(value: string, kind: StatusKind): StatusTone {
  const normalized = value.trim().toLowerCase();

  if (!normalized || /^(unknown|not recorded|not reported|not scored|—|-)$/.test(normalized)) {
    return "gray";
  }

  if (kind === "risk") {
    if (/critical|high|severe|urgent/.test(normalized)) return "red";
    if (/medium|moderate|elevated/.test(normalized)) return "amber";
    if (/low|none|no risk/.test(normalized)) return "green";
    return "gray";
  }

  if (kind === "lifecycle") {
    if (/obsolete|discontinued|end.of.life|\beol\b|withdrawn/.test(normalized)) return "red";
    if (/conflict|mismatch|nrnd|not recommended|last.time.buy|phase.out|limited/.test(normalized)) return "amber";
    if (/\b(inactive|not active)\b/.test(normalized)) return "gray";
    if (/\bactive\b|\bproduction\b|preliminary|mass.production/.test(normalized)) return "green";
    return "gray";
  }

  if (/verified|matched|confirmed/.test(normalized) && !/not verified|unverified|unmatched|mismatch/.test(normalized)) return "green";
  if (/not verified|unverified|needs verification|unmatched|mismatch|no.*match/.test(normalized)) return "amber";
  return "gray";
}

export function StatusPill({
  value,
  kind,
}: {
  value: unknown;
  kind: StatusKind;
}) {
  const label = value === null || value === undefined || String(value).trim() === ""
    ? "Unknown"
    : String(value);
  const tone = statusTone(label, kind);

  return <span className={`cv-status-pill cv-status-pill--${tone}`}>{label}</span>;
}

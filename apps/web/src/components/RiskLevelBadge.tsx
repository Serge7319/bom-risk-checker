/** Saved-evidence risk labels. Missing evidence stays Needs verification, never Low. */

export type RiskTone = "high" | "medium" | "low" | "verify";

export function classifyRiskLevel(value: unknown): { tone: RiskTone; label: string } {
  const raw = String(value ?? "").trim();
  const folded = raw.toLowerCase();
  if (
    !raw
    || /not (assessed|recorded|reported)|unknown|unassess|needs (verification|data|review)|unable to confirm/.test(folded)
  ) {
    return { tone: "verify", label: "Needs verification" };
  }
  if (folded === "high" || folded.startsWith("high ") || folded.startsWith("high-")) {
    return { tone: "high", label: "High" };
  }
  if (
    folded === "medium"
    || folded === "moderate"
    || folded.startsWith("medium ")
    || folded.startsWith("moderate ")
  ) {
    return { tone: "medium", label: "Medium" };
  }
  if (folded === "low" || folded === "healthy" || folded.startsWith("low ")) {
    return { tone: "low", label: "Low" };
  }
  return { tone: "verify", label: "Needs verification" };
}

export function RiskLevelBadge({ value }: { value: unknown }) {
  const risk = classifyRiskLevel(value);
  return (
    <span
      className={`cv-risk-badge cv-risk-badge--${risk.tone}`}
      data-testid="risk-level-badge"
      data-risk-tone={risk.tone}
    >
      {risk.label}
    </span>
  );
}

export function RiskLevelLegend() {
  return (
    <ul className="cv-risk-legend" aria-label="Risk level legend">
      <li><RiskLevelBadge value="High" /> Recorded high-priority risk in the saved evidence.</li>
      <li><RiskLevelBadge value="Medium" /> Recorded moderate risk in the saved evidence.</li>
      <li>
        <RiskLevelBadge value="Low" /> No high-priority risk was recorded in the saved evidence.
        This does not guarantee availability or suitability.
      </li>
      <li>
        <RiskLevelBadge value="Needs verification" /> Risk was not assessed from complete saved evidence.
        Missing or conflicting supplier data stays here and is not shown as Low.
      </li>
    </ul>
  );
}

import type { Report } from "@/lib/api";
import { cleanUserText, userFacingLabel } from "@/lib/display";

type RiskBucket = "high" | "medium" | "low" | "unassessed";
type RiskCounts = Record<RiskBucket, number>;
type RiskSlice = { key: RiskBucket; label: string; count: number; color: string };

const RISK_SLICES: Array<Omit<RiskSlice, "count">> = [
  { key: "high", label: "High risk", color: "#c43d4b" },
  { key: "medium", label: "Medium risk", color: "#d58a12" },
  { key: "low", label: "Low risk", color: "#19846a" },
  { key: "unassessed", label: "Needs verification", color: "#8190a5" },
];

function countValue(value: unknown): number | null {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? Math.floor(number) : null;
}

function rowRiskBucket(row: Record<string, unknown>): RiskBucket {
  const rawLevel = row["Risk Level"] ?? row.risk_level ?? row.risk_level_display ?? row.Risk;
  const level = String(rawLevel || "").trim().toLowerCase();
  const rawScore = row["Risk Score"] ?? row.risk_score;
  const scoreText = String(rawScore ?? "").trim().toLowerCase();
  const hasScore = rawScore !== null && rawScore !== undefined && scoreText !== "" &&
    !["none", "not assessed", "not scored"].includes(scoreText);

  // Keep this aligned with the report export contract: a low/blank level with
  // no score is unassessed, never silently counted as low risk.
  if (!hasScore && (!level || ["low", "healthy", "unknown", "none", "not assessed"].includes(level))) {
    return "unassessed";
  }
  if (level.includes("high") || level.includes("critical")) return "high";
  if (level.includes("medium")) return "medium";
  if (level === "low" || level === "healthy") return "low";
  return "unassessed";
}

function riskProfile(report: Report): {
  counts: RiskCounts;
  total: number;
  rowsAvailable: boolean;
  totalsMismatch: boolean;
} {
  const parts = Array.isArray(report.parts) ? report.parts : [];
  const totalReported = countValue(report.total_parts);
  const rowsHaveRiskFields = parts.some((part) =>
    ["Risk Level", "risk_level", "risk_level_display", "Risk"].some((key) =>
      part[key] !== null && part[key] !== undefined && String(part[key]).trim() !== "",
    ),
  );

  if (parts.length && rowsHaveRiskFields) {
    const counts: RiskCounts = { high: 0, medium: 0, low: 0, unassessed: 0 };
    for (const part of parts) counts[rowRiskBucket(part)] += 1;
    const rowCountDiffers = totalReported !== null && totalReported !== parts.length;
    if (totalReported !== null && totalReported > parts.length) {
      counts.unassessed += totalReported - parts.length;
    }
    const totalsMismatch = rowCountDiffers ||
      (countValue(report.high_risk_count) !== null && countValue(report.high_risk_count) !== counts.high) ||
      (countValue(report.medium_risk_count) !== null && countValue(report.medium_risk_count) !== counts.medium) ||
      (countValue(report.low_risk_count) !== null && countValue(report.low_risk_count) !== counts.low);
    return {
      counts,
      total: Object.values(counts).reduce((sum, value) => sum + value, 0),
      rowsAvailable: true,
      totalsMismatch,
    };
  }

  const counts: RiskCounts = {
    high: countValue(report.high_risk_count) ?? 0,
    medium: countValue(report.medium_risk_count) ?? 0,
    low: countValue(report.low_risk_count) ?? 0,
    unassessed: 0,
  };
  const ratedTotal = counts.high + counts.medium + counts.low;
  const total = Math.max(totalReported ?? ratedTotal, ratedTotal);
  counts.unassessed = Math.max(0, total - ratedTotal);
  return {
    counts,
    total,
    rowsAvailable: false,
    totalsMismatch: totalReported !== null && ratedTotal > totalReported,
  };
}

export function getReportRiskCounts(report: Report): RiskCounts {
  return riskProfile(report).counts;
}

function pieSlicePath(startAngle: number, endAngle: number): string {
  const radians = (angle: number) => (angle * Math.PI) / 180;
  const point = (angle: number) => ({
    x: 50 + 48 * Math.cos(radians(angle)),
    y: 50 + 48 * Math.sin(radians(angle)),
  });
  const start = point(startAngle);
  const end = point(endAngle);
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;
  return `M 50 50 L ${start.x} ${start.y} A 48 48 0 ${largeArc} 1 ${end.x} ${end.y} Z`;
}

function evidenceLine(report: Report): string {
  const evidence = report.evidence_summary || {};
  const parts = [
    evidence.live_count == null ? null : `${countValue(evidence.live_count) ?? 0} live authorized-supplier identity match${Number(evidence.live_count) === 1 ? "" : "es"}`,
    evidence.synthetic_count == null ? null : `${countValue(evidence.synthetic_count) ?? 0} synthetic/preview row${Number(evidence.synthetic_count) === 1 ? "" : "s"}`,
    evidence.missing_count == null ? null : `${countValue(evidence.missing_count) ?? 0} rows without a supplier match`,
  ].filter((value): value is string => Boolean(value));
  return parts.length
    ? `${parts.join(" · ")}. A live identity match does not make every price, stock, or lifecycle field live.`
    : "Supplier evidence coverage was not reported in this saved analysis.";
}

function nextStep(counts: RiskCounts, total: number): string {
  if (counts.high > 0) {
    return `Review the ${counts.high} high-risk component${counts.high === 1 ? "" : "s"} first and confirm each recorded driver against current source evidence.`;
  }
  if (counts.unassessed > 0) {
    return `Verify supplier and lifecycle evidence for the ${counts.unassessed} component${counts.unassessed === 1 ? "" : "s"} without a usable risk rating before relying on this report.`;
  }
  if (total > 0) return "Review component evidence and its retrieval dates before making a release or sourcing decision.";
  return "Add component data to this BOM, then run the analysis again.";
}

export function ReportOverview({ report }: { report: Report }) {
  const profile = riskProfile(report);
  const summary = cleanUserText(report.summary_message) ||
    (profile.total
      ? `${profile.total} BOM rows are recorded in this analysis. Use the risk distribution and evidence status below to decide what needs review.`
      : "This report does not contain BOM-row risk data yet.");
  const status = userFacingLabel(report.health_status, "Not reported");
  const statusTone = /high|critical|block/i.test(status)
    ? "red"
    : /healthy|low risk|clear/i.test(status)
      ? "green"
      : /unknown|not scored|not reported|no data/i.test(status)
        ? "gray"
        : "amber";
  const healthNumber = report.health_score == null ? Number.NaN : Number(report.health_score);
  const health = Number.isFinite(healthNumber) ? healthNumber : null;
  const slices: RiskSlice[] = RISK_SLICES.map((slice) => ({ ...slice, count: profile.counts[slice.key] }));
  const visibleSlices = slices.filter((slice) => slice.count > 0);
  let angle = -90;

  return (
    <section className="cv-report-overview-grid" aria-label="Report overview" data-testid="report-overview">
      <section className="cv-card pad cv-report-executive" aria-labelledby="report-executive-title">
        <div className="cv-eyebrow">Saved analysis</div>
        <div className="cv-report-executive-heading">
          <div>
            <h2 id="report-executive-title" className="cv-card-title">Executive summary</h2>
            <p className="cv-card-subtitle">A quick read of the recorded BOM risk and evidence.</p>
          </div>
          <span className={`cv-badge ${statusTone}`}>
            {status}
          </span>
        </div>
        <p className="cv-report-executive-lead">{summary}</p>
        <dl className="cv-report-summary-facts">
          <div>
            <dt>Health score</dt>
            <dd>{health === null ? "Not scored" : `${health}/100`}</dd>
          </div>
          <div>
            <dt>BOM rows</dt>
            <dd>{profile.total}</dd>
          </div>
          <div>
            <dt>Risk ratings</dt>
            <dd>{profile.total - profile.counts.unassessed} of {profile.total} rated</dd>
          </div>
        </dl>
        <div className="cv-report-summary-note">
          <strong>Evidence coverage</strong>
          <p>{evidenceLine(report)}</p>
        </div>
        <div className="cv-report-summary-next">
          <strong>Recommended next step</strong>
          <p>{nextStep(profile.counts, profile.total)}</p>
        </div>
        <p className="cv-small-note cv-report-saved-data-note">
          Based on this saved analysis. Opening the report does not refresh supplier data.
        </p>
      </section>

      <section className="cv-card pad cv-report-risk-distribution" aria-labelledby="risk-distribution-title" data-testid="risk-distribution">
        <div className="cv-eyebrow">Risk profile</div>
        <h2 id="risk-distribution-title" className="cv-card-title">Component risk distribution</h2>
        <p className="cv-card-subtitle">
          {profile.rowsAvailable
            ? report.hierarchy?.has_hierarchy
              ? "Each saved BOM row is counted once; assembly rows are included, with child risks also summarized in the hierarchy section."
              : "Each saved BOM row is counted once using its saved risk label."
            : "Only saved summary counts are available for this report."}
        </p>
        {profile.total > 0 ? (
          <div className="cv-report-pie-layout">
            <svg
              className="cv-report-pie"
              viewBox="0 0 100 100"
              role="img"
              aria-label={`Risk distribution across ${profile.total} saved BOM rows: ${slices.map((slice) => `${slice.label} ${slice.count}`).join(", ")}.`}
              data-testid="risk-distribution-pie"
            >
              <title>Risk distribution across {profile.total} saved BOM rows</title>
              {visibleSlices.length === 1 ? (
                <circle cx="50" cy="50" r="48" fill={visibleSlices[0].color} />
              ) : visibleSlices.map((slice) => {
                const start = angle;
                const end = angle + (slice.count / profile.total) * 360;
                angle = end;
                return <path key={slice.key} d={pieSlicePath(start, end)} fill={slice.color} stroke="white" strokeWidth="0.8" />;
              })}
            </svg>
            <ul className="cv-report-pie-legend" aria-label="Risk distribution counts">
              {slices.map((slice) => (
                <li key={slice.key}>
                  <span className="cv-report-legend-label"><i style={{ backgroundColor: slice.color }} />{slice.label}</span>
                  <strong>{slice.count}</strong>
                  <span className="cv-report-legend-percent">{profile.total ? Math.round((slice.count / profile.total) * 100) : 0}%</span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="cv-report-no-risk-data">No component risk ratings are available in this saved report.</p>
        )}
        {profile.totalsMismatch ? (
          <p className="cv-report-reconciliation-note" role="status">
            The component rows and saved totals do not match. This chart follows the visible component rows; review the report before acting.
          </p>
        ) : null}
      </section>
    </section>
  );
}

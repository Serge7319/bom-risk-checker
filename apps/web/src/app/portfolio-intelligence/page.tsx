"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import styles from "./portfolio.module.css";
import { fetchPortfolio, recalculatePortfolioHealth } from "@/lib/api";
import { userFacingLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

type ChipTone = "blue" | "amber" | "red" | "green" | "gray";

function numeric(value: unknown): number | null {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function displayCount(value: unknown): string {
  const parsed = numeric(value);
  return parsed === null ? "Not reported" : Math.max(0, Math.trunc(parsed)).toLocaleString();
}

function healthTone(score: number | null, status: string): ChipTone {
  if (score !== null) return score >= 85 ? "green" : score >= 60 ? "amber" : "red";
  const normalized = status.toLowerCase();
  if (/needs verification|partial|missing evidence/.test(normalized)) return "amber";
  if (/high risk/.test(normalized)) return "red";
  return "gray";
}

function healthLabel(score: number | null, status: string): string {
  if (score !== null) return score >= 85 ? "Healthy" : score >= 60 ? "Moderate risk" : "High risk";
  return userFacingLabel(status, "Not scored");
}

function projectRowsFromReports(reports: Array<Record<string, unknown>>) {
  const groups = new Map<string, {
    project: string;
    latestBoms: Map<string, Record<string, unknown>>;
  }>();

  // The reports API is newest-first. Keep the latest saved revision for each
  // BOM so project totals do not double-count older revisions.
  for (const report of reports) {
    const project = userFacingLabel(
      report.project_label || report.project_name || report.filename,
      "Unassigned project",
    );
    const projectId = String(report.project_id || "").trim();
    const key = projectId || project.toLocaleLowerCase();
    const group = groups.get(key) || { project, latestBoms: new Map<string, Record<string, unknown>>() };
    group.project = project;
    const bomKey = String(report.bom_id || report.analysis_id || report.id || "").trim();
    if (bomKey && !group.latestBoms.has(bomKey)) group.latestBoms.set(bomKey, report);
    groups.set(key, group);
  }

  return Array.from(groups.values()).map(({ project, latestBoms }) => {
    const boms = Array.from(latestBoms.values());
    const scored = boms
      .map((report) => ({ score: numeric(report.health_score), parts: numeric(report.total_parts) }))
      .filter((row): row is { score: number; parts: number | null } => row.score !== null);
    const weight = (row: { score: number; parts: number | null }) => Math.max(1, row.parts || 0);
    const weightedHealth = scored.length
      ? Math.round(scored.reduce((sum, row) => sum + row.score * weight(row), 0)
        / scored.reduce((sum, row) => sum + weight(row), 0))
      : null;
    const partCounts = boms.map((row) => numeric(row.total_parts));
    const highCounts = boms.map((row) => numeric(row.high_risk_count));
    const latest = boms[0] || {};
    return {
      project,
      bomCount: boms.length,
      components: partCounts.some((count) => count === null)
        ? null
        : partCounts.reduce<number>((sum, count) => sum + (count || 0), 0),
      highRisk: highCounts.some((count) => count === null)
        ? null
        : highCounts.reduce<number>((sum, count) => sum + (count || 0), 0),
      health: weightedHealth,
      scoredBomCount: scored.length,
      analysisId: String(latest.analysis_id || latest.id || ""),
    };
  }).sort((a, b) => a.project.localeCompare(b.project));
}

function StatusChip({ label, tone }: { label: string; tone: ChipTone }) {
  return <span className={`cv-status-pill cv-status-pill--${tone}`}>{label}</span>;
}

function HealthCell({
  row,
  note,
}: {
  row: Record<string, unknown>;
  note?: string;
}) {
  const score = numeric(row.health_score ?? row.Health);
  const status = String(row.health_status || row["Health Status"] || "");
  const tone = healthTone(score, status);
  return (
    <div className="cv-portfolio-health-cell">
      {score === null ? <span className="cv-portfolio-health-unscored">Not scored</span> : (
        <strong className="cv-portfolio-health-score">{Math.round(score)}<span>/100</span></strong>
      )}
      <StatusChip label={healthLabel(score, status)} tone={tone} />
      {note ? <small className="cv-portfolio-health-note">{note}</small> : null}
    </div>
  );
}

export default function PortfolioPage() {
  const session = useRequireSession();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(true);
  const [recalculating, setRecalculating] = useState("");
  const [healthNotes, setHealthNotes] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!session) return;
    let active = true;
    fetchPortfolio(session.access_token)
      .then((result) => { if (active) setData(result); })
      .catch((err) => { if (active) setError(err instanceof Error ? err.message : "Failed"); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [session]);

  if (!session) return null;
  const reports = (data?.reports || []) as Array<Record<string, unknown>>;
  const intel = (data?.intelligence || {}) as Record<string, unknown>;
  const leadership = (data?.leadership_metrics || {}) as Record<string, unknown>;
  const shared = (intel.shared_components || intel.shared || []) as Array<Record<string, unknown>>;
  const projectRows = projectRowsFromReports(reports);

  async function calculateHealth(analysisId: string) {
    if (!session || !analysisId || recalculating) return;
    setRecalculating(analysisId);
    setActionError("");
    try {
      const result = await recalculatePortfolioHealth(session.access_token, analysisId);
      const message = String(result.summary_message || result.source_label || "Health checked against saved evidence.");
      setHealthNotes((current) => ({ ...current, [analysisId]: message }));
      setData(await fetchPortfolio(session.access_token));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Health could not be recalculated.");
    } finally {
      setRecalculating("");
    }
  }

  const blockers = Number(leadership.open_blocker_alerts || 0);
  const awaiting = Number(leadership.decisions_awaiting_approval || 0);
  const monitored = Number(leadership.monitored_boms || 0);
  const totalParts = reports.reduce((sum, row) => sum + (numeric(row.total_parts) || 0), 0);
  const reportHighCounts = reports.map((row) => numeric(row.high_risk_count));
  const highRiskTotal = reportHighCounts.some((count) => count === null)
    ? null
    : reportHighCounts.reduce<number>((sum, count) => sum + (count || 0), 0);

  return (
    <Shell session={session}>
      <div className={styles.portfolioStyles}>
      <PageHeader meta={PAGE_META.portfolio} actions={<PrimaryLink href="/reports">Open saved analyses</PrimaryLink>} />
      {data ? <EvidenceNotice gap={data.gap} /> : null}
      {busy ? <LoadingCard label="Loading portfolio intelligence…" /> : null}
      {error ? <div className="cv-error" role="alert">Portfolio data could not load. {error}</div> : null}
      {actionError ? <div className="cv-error" role="alert">{actionError}</div> : null}
      {!busy && data ? (
        reports.length ? <>
          <p className="cv-portfolio-scope">Based on saved analyses in this workspace</p>
          <div className="cv-kpis cv-portfolio-kpis">
            <Link className="cv-portfolio-kpi-link" href="/monitoring" aria-label="View open blocker alerts in Monitoring">
              <KpiCard icon="risk" tone={blockers > 0 ? "red" : "green"} label="Open blocker alerts" value={blockers} status={{ label: blockers > 0 ? "Review alerts" : "No open blockers", tone: blockers > 0 ? "red" : "green" }} detail="High-severity, unacknowledged alerts" />
              <span className="cv-portfolio-kpi-action">View details <span aria-hidden="true">→</span></span>
            </Link>
            <Link className="cv-portfolio-kpi-link" href="/engineering-decisions" aria-label="View decisions awaiting approval">
              <KpiCard icon="clock" tone={awaiting > 0 ? "amber" : "blue"} label="Decisions awaiting approval" value={awaiting} status={{ label: awaiting > 0 ? "Approval needed" : "No pending requests", tone: awaiting > 0 ? "amber" : "green" }} detail="Active approver requests" />
              <span className="cv-portfolio-kpi-action">View details <span aria-hidden="true">→</span></span>
            </Link>
            <Link className="cv-portfolio-kpi-link" href="/monitoring" aria-label="View monitored BOMs">
              <KpiCard icon="bell" tone={monitored > 0 ? "green" : "blue"} label="Monitored BOMs" value={monitored} status={{ label: monitored > 0 ? "Monitoring on" : "Not enabled", tone: monitored > 0 ? "green" : "gray" }} detail="BOMs opted in to supplier checks" />
              <span className="cv-portfolio-kpi-action">View details <span aria-hidden="true">→</span></span>
            </Link>
            <Link className="cv-portfolio-kpi-link" href="/reports" aria-label="View saved analyses">
              <KpiCard icon="report" tone="blue" label="Saved analyses" value={reports.length} status={{ label: "Saved", tone: "blue" }} detail="Reports in this workspace" />
              <span className="cv-portfolio-kpi-action">View details <span aria-hidden="true">→</span></span>
            </Link>
            <Link className="cv-portfolio-kpi-link" href="#project-health" aria-label="View project health details">
              <KpiCard icon="portfolio" tone="blue" label="Projects represented" value={projectRows.length} status={{ label: "In portfolio", tone: "blue" }} detail="Projects with saved BOMs" />
              <span className="cv-portfolio-kpi-action">View details <span aria-hidden="true">→</span></span>
            </Link>
            <Link className="cv-portfolio-kpi-link" href="#shared-components" aria-label="View shared component details">
              <KpiCard icon="box" tone={shared.length > 0 ? "amber" : "blue"} label="Shared components" value={shared.length} status={{ label: shared.length > 0 ? "Across BOMs" : "None shared", tone: shared.length > 0 ? "amber" : "gray" }} detail="Parts appearing in multiple BOMs" />
              <span className="cv-portfolio-kpi-action">View details <span aria-hidden="true">→</span></span>
            </Link>
          </div>

          <div className="cv-portfolio-explainer">
            <strong>How portfolio health is calculated</strong>
            <p>Health scores use saved component risk and verification data. Older reports may have no score. Select <b>Calculate health</b> to recheck saved evidence; if required evidence is missing, the score stays unscored. This action does not query suppliers.</p>
            <p><b>High-risk parts</b> is a count of components classified High in the saved analysis, not a count of alerts. Zero means no High-rated component was recorded; “Not reported” means the saved summary did not provide that count.</p>
          </div>

          <section className="cv-card pad cv-card--table cv-portfolio-table-card" id="analyses">
            <div className="cv-portfolio-section-heading">
              <div>
                <h2 className="cv-card-title">Analyses</h2>
                <p className="cv-card-subtitle">Latest saved reports, with health and high-risk part counts.</p>
              </div>
              <span className="cv-portfolio-section-total">{reports.length.toLocaleString()} reports · {totalParts.toLocaleString()} parts · {highRiskTotal === null ? "Some high-risk counts unreported" : `${highRiskTotal.toLocaleString()} high-risk parts`}</span>
            </div>
            <div className="cv-table-wrap cv-table-wrap--fit" style={{ marginTop: 12 }}>
              <table className="cv-table cv-table--fit cv-table--mpn-safe cv-portfolio-table">
                <thead><tr><th>Saved BOM</th><th>Project</th><th>Health</th><th className="cv-num">Parts</th><th className="cv-num">High-risk parts</th><th>Action</th></tr></thead>
                <tbody>
                  {reports.map((row, i) => {
                    const analysisId = String(row.analysis_id || row.id || "");
                    const score = numeric(row.health_score);
                    const highCount = numeric(row.high_risk_count);
                    const label = userFacingLabel(row.bom_name || row.filename, "Saved analysis");
                    return (
                      <tr key={analysisId || i}>
                        <td data-label="Saved BOM"><Link className="cv-portfolio-row-link" href={analysisId ? `/reports/${encodeURIComponent(analysisId)}` : "/reports"}>{label}</Link><small>{userFacingLabel(row.revision, "Latest saved report")}</small></td>
                        <td data-label="Project">{userFacingLabel(row.project_label || row.project_name, "Unassigned project")}</td>
                        <td data-label="Health"><HealthCell row={row} note={score === null ? (
                          healthNotes[analysisId]
                          || String(row.summary_message || (row.health_status
                            ? `${userFacingLabel(row.health_status)}. Calculate health to check the saved evidence.`
                            : "Calculate health to check the saved evidence."))
                        ) : undefined} /></td>
                        <td className="cv-num" data-label="Parts">{displayCount(row.total_parts)}</td>
                        <td className="cv-num" data-label="High-risk parts"><StatusChip label={highCount === null ? "Not reported" : highCount === 0 ? "None" : `${Math.trunc(highCount)} ${highCount === 1 ? "part" : "parts"}`} tone={highCount === null ? "gray" : highCount > 0 ? "red" : "green"} /></td>
                        <td data-label="Action"><div className="cv-portfolio-row-actions">
                          <Link className="cv-button small" href={analysisId ? `/reports/${encodeURIComponent(analysisId)}` : "/reports"}>Open report</Link>
                          {score === null && analysisId ? <button className="cv-button small primary" type="button" disabled={Boolean(recalculating)} onClick={() => void calculateHealth(analysisId)}>{recalculating === analysisId ? "Checking…" : "Calculate health"}</button> : null}
                        </div></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <div className="cv-grid-2 cv-grid-2--tables cv-portfolio-detail-grid">
            <section className="cv-card pad cv-card--table cv-portfolio-table-card" id="project-health">
              <div className="cv-portfolio-section-heading">
                <div>
                  <h2 className="cv-card-title">Project health</h2>
                  <p className="cv-card-subtitle">Latest revision per BOM; health is weighted by component count.</p>
                </div>
              </div>
              {projectRows.length ? <div className="cv-table-wrap cv-table-wrap--fit" style={{ marginTop: 12 }}>
                <table className="cv-table cv-table--fit cv-table--mpn-safe cv-portfolio-table">
                  <thead><tr><th>Project</th><th className="cv-num">BOMs</th><th>Health</th><th className="cv-num">Components</th><th className="cv-num">High-risk parts</th></tr></thead>
                  <tbody>{projectRows.map((row, i) => {
                    const partial = row.scoredBomCount > 0 && row.scoredBomCount < row.bomCount;
                    const tone = row.health === null ? "gray" : row.health >= 85 ? "green" : row.health >= 60 ? "amber" : "red";
                    const healthText = row.health === null ? "Not scored" : `${row.health}/100`;
                    const statusText = row.health === null ? "No scored BOMs" : partial ? `${row.scoredBomCount}/${row.bomCount} BOMs scored` : healthLabel(row.health, "");
                    return <tr key={`${row.project}-${i}`}>
                      <td data-label="Project"><Link className="cv-portfolio-row-link" href={row.analysisId ? `/reports/${encodeURIComponent(row.analysisId)}` : "/reports"}>{row.project}</Link></td>
                      <td className="cv-num" data-label="BOMs">{row.bomCount}</td>
                      <td data-label="Health"><div className="cv-portfolio-health-cell"><strong className={row.health === null ? "cv-portfolio-health-unscored" : "cv-portfolio-health-score"}>{healthText}</strong><StatusChip label={statusText} tone={partial ? "amber" : tone} /></div></td>
                      <td className="cv-num" data-label="Components">{row.components === null ? "Not reported" : row.components.toLocaleString()}</td>
                      <td className="cv-num" data-label="High-risk parts"><StatusChip label={row.highRisk === null ? "Not reported" : row.highRisk === 0 ? "None" : `${row.highRisk} ${row.highRisk === 1 ? "part" : "parts"}`} tone={row.highRisk === null ? "gray" : row.highRisk > 0 ? "red" : "green"} /></td>
                    </tr>;
                  })}</tbody>
                </table>
              </div> : <EmptyState icon="portfolio" title="No project roll-up available" body="Project health appears after a BOM is saved with a project name." />}
            </section>

            <section className="cv-card pad cv-card--table cv-portfolio-table-card" id="shared-components">
              <div className="cv-portfolio-section-heading">
                <div>
                  <h2 className="cv-card-title">Shared components</h2>
                  <p className="cv-card-subtitle">Parts found in more than one saved BOM.</p>
                </div>
              </div>
              {shared.length ? <div className="cv-table-wrap cv-table-wrap--fit" style={{ marginTop: 12 }}>
                <table className="cv-table cv-table--fit cv-table--mpn-safe cv-portfolio-table">
                  <thead><tr><th>Part</th><th>Manufacturer</th><th>Lifecycle</th><th className="cv-num">BOMs</th><th className="cv-num">Highest risk score</th></tr></thead>
                  <tbody>{shared.slice(0, 20).map((row, i) => {
                    const mpn = userFacingLabel(row["Part Number"] || row.mpn, "Component");
                    const maker = userFacingLabel(row.Manufacturer || row.manufacturer, "Unknown");
                    const risk = numeric(row["Highest Risk Score"]);
                    const bomCount = numeric(row["BOMs Using Part"] ?? row["Projects Using Part"]);
                    return <tr key={`${mpn}-${i}`}>
                      <td data-label="Part"><Link className="cv-portfolio-row-link" href={`/design-impact?mpn=${encodeURIComponent(mpn)}`}>{mpn}</Link></td>
                      <td data-label="Manufacturer">{maker}</td>
                      <td data-label="Lifecycle"><StatusChip label={userFacingLabel(row.Lifecycle, "Unknown")} tone={/obsolete|eol|discontinued/i.test(String(row.Lifecycle || "")) ? "red" : /nrnd|not recommended|conflict/i.test(String(row.Lifecycle || "")) ? "amber" : /active/i.test(String(row.Lifecycle || "")) ? "green" : "gray"} /></td>
                      <td className="cv-num" data-label="BOMs">{bomCount === null ? "Not reported" : bomCount}</td>
                      <td className="cv-num" data-label="Highest risk score"><StatusChip label={risk === null ? "Not assessed" : `${Math.round(risk)}/100`} tone={risk === null ? "gray" : risk >= 60 ? "red" : risk >= 30 ? "amber" : "green"} /></td>
                    </tr>;
                  })}</tbody>
                </table>
              </div> : <EmptyState icon="box" title="No shared components found" body="A part appears here after it is recorded in more than one saved BOM." />}
              {shared.length > 20 ? <p className="cv-portfolio-table-footnote">Showing 20 of {shared.length.toLocaleString()} shared components. Open a part to explore its cross-BOM impact.</p> : null}
            </section>
          </div>
        </> : <EmptyState icon="portfolio" title="Your portfolio is ready for its first BOM" body="Portfolio insights appear after you save one or more BOM analyses to this workspace." action={<PrimaryLink href="/bom-analyzer">Start a BOM analysis</PrimaryLink>} />
      ) : null}
      </div>
    </Shell>
  );
}

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { LoadingCard } from "@/components/GapBanner";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { fetchWorkspaceHome } from "@/lib/api";
import { cleanUserText, evidenceSourceLabel, userFacingLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

type HomePayload = {
  ok: boolean;
  gap?: string;
  metrics: Record<string, number>;
  projects: Array<Record<string, unknown>>;
  recent_analyses: Array<Record<string, unknown>>;
  priority_risks: Array<Record<string, unknown>>;
  priority_severity_counts?: Record<string, number>;
  next_actions: Array<Record<string, unknown>>;
};

export default function HomePage() {
  const session = useRequireSession();
  const [data, setData] = useState<HomePayload | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [showAllProjects, setShowAllProjects] = useState(false);
  const [showAllPriorityRisks, setShowAllPriorityRisks] = useState(false);

  useEffect(() => {
    if (!session) return;
    setBusy(true);
    fetchWorkspaceHome(session.access_token)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"))
      .finally(() => setBusy(false));
  }, [session]);

  if (!session) return null;

  const metrics = data?.metrics || {};
  const projects = data?.projects || [];
  const priorityRisks = data?.priority_risks || [];
  const homeListPreviewLimit = 3;
  const visibleProjects = showAllProjects
    ? projects
    : projects.slice(0, homeListPreviewLimit);
  const visiblePriorityRisks = showAllPriorityRisks
    ? priorityRisks
    : priorityRisks.slice(0, homeListPreviewLimit);
  const hasSaved = Number(metrics.saved_analyses || 0) > 0;
  const latest = (data?.recent_analyses || [])[0] as
    | Record<string, unknown>
    | undefined;
  const health =
    latest?.health_score == null
      ? null
      : Math.round(Number(latest.health_score));
  const priorityTotal = Number(metrics.priority_items ?? priorityRisks.length);
  const prioritySeverityCounts = data?.priority_severity_counts || {};
  const severityLegend = [
    { key: "critical", label: "Critical" },
    { key: "high", label: "High" },
    { key: "medium", label: "Medium" },
    { key: "needs_verification", label: "Needs verification" },
  ].map((item) => ({ ...item, count: Number(prioritySeverityCounts[item.key] || 0) }));
  const severityTotal = severityLegend.reduce((sum, item) => sum + item.count, 0);

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.home}
        actions={
          <>
            <PrimaryLink href="/bom-analyzer">New BOM analysis</PrimaryLink>
            <SecondaryLink href="/reports">Reports</SecondaryLink>
          </>
        }
      />

      {busy ? <LoadingCard label="Loading workspace from saved analyses…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}

      {!busy && data ? (
        <>
          <section className={"cv-home-hero" + (latest ? " has-latest" : "")}>
            <div>
              <div className="cv-hero-kicker">
                <i aria-hidden />
                {hasSaved
                  ? "Projects in this workspace"
                  : "No saved BOMs in this workspace yet"}
              </div>
              <h2>
                {hasSaved
                  ? `${metrics.active_projects || 0} project${Number(metrics.active_projects) === 1 ? "" : "s"} · ${metrics.saved_boms || 0} BOM${Number(metrics.saved_boms) === 1 ? "" : "s"} · ${metrics.priority_items || 0} priority risk item${Number(metrics.priority_items) === 1 ? "" : "s"}.`
                  : "Save a project BOM to populate this engineering dashboard."}
              </h2>
              <p>
                Review saved BOMs, follow priority signals to their evidence, and
                reopen the report whenever you need it.
              </p>
              <div className="cv-hero-actions">
                <PrimaryLink href="/bom-analyzer">
                  {hasSaved ? "Analyze another BOM" : "Open BOM Analyzer"}
                </PrimaryLink>
                {latest?.id ? (
                  <SecondaryLink href={`/reports/${String(latest.id)}`}>
                    Open latest report
                  </SecondaryLink>
                ) : (
                  <SecondaryLink href="/engineering-decisions">
                    Decision queue
                  </SecondaryLink>
                )}
              </div>
            </div>
            {latest ? <div className="cv-hero-side">
              <div className="cv-hero-side-label">Latest analysis health</div>
              <div className="cv-readiness">
                <div className="cv-score">
                  {health == null ? "Not scored" : health}
                  {health != null ? <small> / 100</small> : null}
                </div>
              </div>
              <div className="cv-hero-side-copy">
                {latest
                  ? `${userFacingLabel(latest.bom_name || latest.project_name || latest.filename, "BOM")} · rev ${String(latest.revision || "—")} · ${String(latest.total_parts ?? 0)} parts`
                  : "No saved analysis yet."}
              </div>
              <div className="cv-hero-source">Data: saved to this workspace</div>
            </div> : null}
          </section>

          <div className="cv-section-heading">
            <div>
              <h2>At a glance</h2>
              <p>Click a metric to open its related workspace details.</p>
            </div>
            <span className="cv-data-note">Current workspace</span>
          </div>
          <div className="cv-kpis cv-home-kpis">
            <Link
              className="cv-home-kpi-link is-red"
              href="#priority-queue"
              aria-label={`View ${Number(metrics.open_blockers || 0)} open blockers in the priority queue`}
            >
              <KpiCard
                icon="risk"
                label="Open blockers"
                value={metrics.open_blockers ?? 0}
                detail="Critical and high priority findings"
              />
            </Link>
            <Link
              className="cv-home-kpi-link"
              href={hasSaved ? "#home-active-projects-list" : "/bom-analyzer"}
              aria-label={`View ${Number(metrics.saved_boms || 0)} saved BOMs`}
            >
              <KpiCard
                icon="box"
                label="Saved BOMs"
                value={metrics.saved_boms ?? 0}
                detail={hasSaved ? "Saved in this workspace" : "Analyze a BOM to get started"}
              />
            </Link>
            <Link
              className="cv-home-kpi-link is-blue"
              href="/engineering-decisions"
              aria-label={`Review ${Number(metrics.awaiting_approvals || 0)} approvals awaiting a response`}
            >
              <KpiCard
                icon="check"
                label="Awaiting approvals"
                value={metrics.awaiting_approvals ?? 0}
                detail="Pending approver decisions"
              />
            </Link>
          </div>

          <div className="cv-home-grid">
            <section className="cv-card pad">
              <div className="cv-home-panel-heading">
                <div className="cv-home-panel-copy">
                  <h3 className="cv-card-title">Active projects</h3>
                  <p className="cv-card-subtitle">
                    Projects and BOMs saved with the latest analysis link.
                  </p>
                </div>
                {projects.length > homeListPreviewLimit ? (
                  <button
                    type="button"
                    className="cv-button small cv-home-view-toggle"
                    aria-expanded={showAllProjects}
                    aria-controls="home-active-projects-list"
                    onClick={() => setShowAllProjects((showAll) => !showAll)}
                  >
                    {showAllProjects ? "Show fewer" : `View all ${projects.length}`}
                  </button>
                ) : null}
              </div>
              {projects.length ? (
                <>
                  <div className="cv-table-wrap cv-table-wrap--actions" id="home-active-projects-list">
                    <table className="cv-table cv-table-actions">
                      <thead>
                        <tr>
                          <th>Project</th>
                          <th>BOMs</th>
                          <th>Latest health</th>
                          <th className="cv-table-action">Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {visibleProjects.map((project) => {
                          const boms = (project.boms || []) as Array<
                            Record<string, unknown>
                          >;
                          const first = boms[0];
                          const analysisId = first?.latest_analysis_id;
                          return (
                            <tr key={String(project.id)}>
                              <td>
                                <strong>{userFacingLabel(project.name, "Project")}</strong>
                              </td>
                              <td>{String(project.bom_count ?? boms.length)}</td>
                              <td>
                                {first?.health_score == null
                                  ? "—"
                                  : String(first.health_score)}
                                {first?.top_rolled_risk
                                  ? ` · ${String(first.top_rolled_risk)}`
                                  : ""}
                              </td>
                              <td className="cv-table-action">
                                {analysisId ? (
                                  <Link
                                    className="cv-table-open"
                                    href={`/reports/${String(analysisId)}`}
                                  >
                                    Open
                                  </Link>
                                ) : (
                                  "—"
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <p className="cv-home-list-summary" aria-live="polite">
                    Showing {visibleProjects.length} of {projects.length} project{projects.length === 1 ? "" : "s"}
                  </p>
                </>
              ) : (
                <div className="cv-empty" style={{ border: 0, padding: 0 }}>
                  No projects yet.{" "}
                  <Link href="/bom-analyzer">Analyze a BOM</Link> with a project
                  name to create one.
                </div>
              )}
            </section>

            <section className="cv-card pad cv-priority-panel" id="priority-queue">
              <div className="cv-priority-heading">
                <div className="cv-home-panel-copy">
                  <h3 className="cv-card-title">Priority queue</h3>
                  <p className="cv-card-subtitle">
                    Ranked, evidence-linked risks from saved analyses in this workspace.
                  </p>
                </div>
                <div className="cv-priority-actions">
                  <span className="cv-priority-count">
                    {priorityTotal} active {priorityTotal === 1 ? "signal" : "signals"}
                  </span>
                  {priorityRisks.length > homeListPreviewLimit ? (
                    <button
                      type="button"
                      className="cv-button small cv-home-view-toggle"
                      aria-expanded={showAllPriorityRisks}
                      aria-controls="home-priority-risks-list"
                      onClick={() => setShowAllPriorityRisks((showAll) => !showAll)}
                    >
                      {showAllPriorityRisks ? "Show fewer" : `View all ${priorityRisks.length}`}
                    </button>
                  ) : null}
                </div>
              </div>
              {severityTotal > 0 ? (
                <div className="cv-priority-summary" aria-label="Priority queue severity breakdown">
                  <div className="cv-priority-bar" aria-hidden="true">
                    {severityLegend.map((item) => (
                      <span
                        className={`cv-priority-segment ${item.key}`}
                        key={item.key}
                        style={{ flexBasis: `${(item.count / severityTotal) * 100}%` }}
                      />
                    ))}
                  </div>
                  <div className="cv-priority-legend">
                    {severityLegend.filter((item) => item.count > 0).map((item) => (
                      <span className={item.key} key={item.key}>
                        {item.label} <strong>{item.count}</strong>
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
              {priorityRisks.length ? (
                <>
                  <div className="cv-priority-list" id="home-priority-risks-list">
                    {visiblePriorityRisks.map((item, index) => {
                      const level = String(item.risk_level || "Needs verification");
                      const normalizedLevel = level.toLowerCase();
                      const severity = normalizedLevel.includes("critical")
                        ? "critical"
                        : normalizedLevel.includes("high")
                          ? "high"
                          : normalizedLevel.includes("medium")
                            ? "medium"
                            : "needs_verification";
                      return (
                        <div className="cv-priority-row" key={index}>
                          <span className={`cv-priority-severity ${severity}`}>
                            {level}
                          </span>
                          <div>
                            <div className="cv-priority-title">
                              {item.why
                                ? cleanUserText(item.why)
                                : userFacingLabel(item.bom_name, "BOM")}
                            </div>
                            <div className="cv-priority-meta">
                              {item.mpn ? `${String(item.mpn)} · ` : ""}
                              {userFacingLabel(item.project_name, "")}
                              {item.bom_path ? ` · ${cleanUserText(item.bom_path)}` : ""}
                            </div>
                            <div className="cv-evidence-chips">
                              <span className="cv-evidence-chip">
                                {evidenceSourceLabel(item.evidence_source)}
                              </span>
                              <span className="cv-evidence-chip">
                                {String(item.risk_level || "—")} priority
                              </span>
                            </div>
                          </div>
                          {item.analysis_id ? (
                            <Link
                              className="cv-button small"
                              href={`/reports/${String(item.analysis_id)}`}
                            >
                              Review evidence
                            </Link>
                          ) : (
                            <span className="cv-badge gray">No report link</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  <p className="cv-home-list-summary" aria-live="polite">
                    Showing {visiblePriorityRisks.length} of {priorityRisks.length} priority item{priorityRisks.length === 1 ? "" : "s"}
                  </p>
                </>
              ) : (
                <div className="cv-empty" style={{ border: 0, minHeight: 120, padding: 18 }}>
                  <h3 style={{ fontSize: 14 }}>{hasSaved ? "No priority risks identified" : "No analysis to review yet"}</h3>
                  <p>{hasSaved ? "Your saved analyses did not produce high or medium priority items." : "Save a BOM analysis to populate this queue."}</p>
                </div>
              )}
            </section>
          </div>

          <div className="cv-section-heading" style={{ marginTop: 28 }}>
            <div>
              <h2>Next actions</h2>
              <p>Live steps vs staged roadmap items (clearly labeled).</p>
            </div>
          </div>
          <div className="cv-home-grid">
            {(data.next_actions || []).map((action, index) => {
              const live = Boolean(action.live);
              const href =
                action.href_kind === "report"
                  ? `/reports/${String(action.href)}`
                  : String(action.href || "/");
              return (
                <section className="cv-card pad" key={index}>
                  <div className="cv-eyebrow">
                    {live ? "Available now" : "Staged — not live"}
                  </div>
                  <h3 className="cv-card-title" style={{ fontSize: 16 }}>
                    {String(action.title)}
                  </h3>
                  <p className="cv-card-subtitle">{cleanUserText(action.detail)}</p>
                  {live ? (
                    <div style={{ marginTop: 12 }}>
                      <SecondaryLink href={href}>Open</SecondaryLink>
                    </div>
                  ) : (
                    <p className="cv-small-note" style={{ marginTop: 12 }}>
                      Shown for roadmap visibility only.
                    </p>
                  )}
                </section>
              );
            })}
          </div>
        </>
      ) : null}
    </Shell>
  );
}


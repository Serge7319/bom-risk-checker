"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { fetchWorkspaceHome } from "@/lib/api";
import { evidenceSourceLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

type HomePayload = {
  ok: boolean;
  gap?: string;
  metrics: Record<string, number>;
  projects: Array<Record<string, unknown>>;
  recent_analyses: Array<Record<string, unknown>>;
  priority_risks: Array<Record<string, unknown>>;
  next_actions: Array<Record<string, unknown>>;
};

export default function HomePage() {
  const session = useRequireSession();
  const [data, setData] = useState<HomePayload | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

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
  const hasSaved = Number(metrics.saved_analyses || 0) > 0;
  const latest = (data?.recent_analyses || [])[0] as
    | Record<string, unknown>
    | undefined;
  const health =
    latest?.health_score == null
      ? null
      : Math.round(Number(latest.health_score));

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

      {typeof data?.gap === "string" ? <GapBanner>{data.gap}</GapBanner> : null}
      {busy ? <LoadingCard label="Loading workspace from saved analyses…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}

      {!busy && data ? (
        <>
          <section className="cv-home-hero">
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
                Home brings together saved projects, rolled-up risks, and next
                actions. Scheduled monitoring, billing, and design-tool
                integrations are not connected yet.
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
            <div className="cv-hero-side">
              <div className="cv-hero-side-label">Latest analysis health</div>
              <div className="cv-readiness">
                <div className="cv-score">
                  {health == null ? "—" : health}
                  <small> / 100</small>
                </div>
              </div>
              <div className="cv-hero-side-copy">
                {latest
                  ? `${String(latest.project_name || latest.filename || "BOM")} · rev ${String(latest.revision || "—")} · ${String(latest.total_parts ?? 0)} parts`
                  : "No saved analysis yet."}
              </div>
              <div className="cv-hero-source">Data: saved to this workspace</div>
            </div>
          </section>

          <div className="cv-section-heading">
            <div>
              <h2>At a glance</h2>
              <p>Counts from saved projects and analyses in this workspace.</p>
            </div>
            <span className="cv-data-note">
              {hasSaved ? "Current workspace" : "Empty until first save"}
            </span>
          </div>
          <div className="cv-kpis">
            <KpiCard
              icon="portfolio"
              tone="blue"
              label="Active projects"
              value={hasSaved ? metrics.active_projects ?? 0 : "—"}
              detail={hasSaved ? "Reopenable after reload" : "Upload a BOM"}
            />
            <KpiCard
              icon="box"
              label="Saved BOMs"
              value={hasSaved ? metrics.saved_boms ?? 0 : "—"}
              detail={hasSaved ? "With revisions" : "Awaiting data"}
            />
            <KpiCard
              icon="risk"
              tone="amber"
              label="Priority risks"
              value={hasSaved ? metrics.priority_items ?? 0 : "—"}
              detail={hasSaved ? "From roll-up / high-risk" : "—"}
            />
            <KpiCard
              icon="insight"
              label="Analyses"
              value={hasSaved ? metrics.saved_analyses ?? 0 : "—"}
              detail={hasSaved ? "Saved to this workspace" : "—"}
            />
          </div>

          <div className="cv-home-grid">
            <section className="cv-card pad">
              <div style={{ marginBottom: 12 }}>
                <h3 className="cv-card-title">Active projects</h3>
                <p className="cv-card-subtitle">
                  Projects and BOMs saved with the latest analysis link.
                </p>
              </div>
              {(data.projects || []).length ? (
                <div className="cv-table-wrap cv-table-wrap--actions">
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
                      {data.projects.map((project) => {
                        const boms = (project.boms || []) as Array<
                          Record<string, unknown>
                        >;
                        const first = boms[0];
                        const analysisId = first?.latest_analysis_id;
                        return (
                          <tr key={String(project.id)}>
                            <td>
                              <strong>{String(project.name)}</strong>
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
              ) : (
                <div className="cv-empty" style={{ border: 0, padding: 0 }}>
                  No projects yet.{" "}
                  <Link href="/bom-analyzer">Analyze a BOM</Link> with a project
                  name to create one.
                </div>
              )}
            </section>

            <section className="cv-card pad">
              <div style={{ marginBottom: 12 }}>
                <h3 className="cv-card-title">Priority queue</h3>
                <p className="cv-card-subtitle">
                  Ranked, evidence-linked risks from saved analyses in this
                  workspace.
                </p>
              </div>
              {(data.priority_risks || []).length ? (
                <div className="cv-priority-list">
                  {data.priority_risks.map((item, index) => {
                    const high =
                      String(item.risk_level || "").toLowerCase() === "high";
                    return (
                      <div className="cv-priority-row" key={index}>
                        <div
                          className={`cv-priority-index${high ? "" : " amber"}`}
                        >
                          {String(index + 1).padStart(2, "0")}
                        </div>
                        <div>
                          <div className="cv-priority-title">
                            {item.mpn
                              ? String(item.mpn)
                              : String(item.bom_name || "BOM")}
                            {item.why ? ` · ${String(item.why)}` : ""}
                          </div>
                          <div className="cv-priority-meta">
                            {String(item.project_name || "")}
                            {item.bom_path ? ` · ${String(item.bom_path)}` : ""}
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
              ) : (
                <div className="cv-empty" style={{ border: 0, minHeight: 120, padding: 18 }}>
                  <h3 style={{ fontSize: 14 }}>No priority risks yet</h3>
                  <p>Save a BOM analysis to populate this ranked queue.</p>
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
                  <p className="cv-card-subtitle">{String(action.detail)}</p>
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

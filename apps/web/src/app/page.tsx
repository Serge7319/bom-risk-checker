"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { fetchWorkspaceHome } from "@/lib/api";
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
                  ? "Active projects from workspace store"
                  : "Migration preview · awaiting first saved BOM"}
              </div>
              <h2>
                {hasSaved
                  ? `${metrics.active_projects || 0} project${Number(metrics.active_projects) === 1 ? "" : "s"} · ${metrics.saved_boms || 0} BOM${Number(metrics.saved_boms) === 1 ? "" : "s"} · ${metrics.priority_items || 0} priority risk item${Number(metrics.priority_items) === 1 ? "" : "s"}.`
                  : "Save a project BOM to populate this engineering dashboard."}
              </h2>
              <p>
                Home surfaces reopenable projects, rolled-up risks, and next
                actions from persisted analyses. Live monitoring email, plan
                metering, and PLM/ERP/CAD integrations remain staged — not shown
                as live.
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
              <div className="cv-hero-source">
                Persistence: migration workspace store
              </div>
            </div>
          </section>

          <div className="cv-section-heading">
            <div>
              <h2>At a glance</h2>
              <p>Counts from saved project / BOM / analysis records.</p>
            </div>
            <span className="cv-data-note">
              {hasSaved ? "Persisted workspace" : "Empty until first save"}
            </span>
          </div>
          <div className="cv-kpis">
            <div className="cv-kpi tone-blue">
              <span>Active projects</span>
              <strong>{hasSaved ? metrics.active_projects ?? 0 : "—"}</strong>
              <em>{hasSaved ? "Reopenable after reload" : "Upload a BOM"}</em>
            </div>
            <div className="cv-kpi">
              <span>Saved BOMs</span>
              <strong>{hasSaved ? metrics.saved_boms ?? 0 : "—"}</strong>
              <em>{hasSaved ? "With revisions" : "Awaiting data"}</em>
            </div>
            <div className="cv-kpi tone-amber">
              <span>Priority risks</span>
              <strong>{hasSaved ? metrics.priority_items ?? 0 : "—"}</strong>
              <em>{hasSaved ? "From roll-up / high-risk" : "—"}</em>
            </div>
            <div className="cv-kpi">
              <span>Analyses</span>
              <strong>{hasSaved ? metrics.saved_analyses ?? 0 : "—"}</strong>
              <em>{hasSaved ? "Durable in sandbox store" : "—"}</em>
            </div>
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
                <div className="cv-table-wrap">
                  <table className="cv-table">
                    <thead>
                      <tr>
                        <th>Project</th>
                        <th>BOMs</th>
                        <th>Latest health</th>
                        <th></th>
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
                            <td>
                              {analysisId ? (
                                <Link href={`/reports/${String(analysisId)}`}>
                                  Open →
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
                <h3 className="cv-card-title">Priority risks</h3>
                <p className="cv-card-subtitle">
                  Assembly roll-up contributors or high-risk counts — with
                  evidence sources labeled.
                </p>
              </div>
              {(data.priority_risks || []).length ? (
                <ul className="cv-action-list">
                  {data.priority_risks.map((item, index) => (
                    <li key={index}>
                      <div>
                        <strong>
                          {item.mpn
                            ? String(item.mpn)
                            : String(item.bom_name || "BOM")}
                        </strong>
                        <div className="cv-priority-meta">
                          {String(item.project_name || "")}
                          {item.bom_path ? ` · ${String(item.bom_path)}` : ""}
                          {item.why ? ` — ${String(item.why)}` : ""}
                        </div>
                        <div className="cv-small-note">
                          Evidence: {String(item.evidence_source || "synthetic-preview")}
                        </div>
                      </div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <span
                          className={`cv-badge ${String(item.risk_level).toLowerCase() === "high" ? "red" : "amber"}`}
                        >
                          {String(item.risk_level || "—")}
                        </span>
                        {item.analysis_id ? (
                          <Link href={`/reports/${String(item.analysis_id)}`}>
                            Evidence →
                          </Link>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="cv-empty" style={{ border: 0, padding: 0 }}>
                  No priority risks yet.
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

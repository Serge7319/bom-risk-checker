"use client";

import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { fetchPortfolio } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

export default function PortfolioPage() {
  const session = useRequireSession();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    if (!session) return;
    fetchPortfolio(session.access_token)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"))
      .finally(() => setBusy(false));
  }, [session]);

  if (!session) return null;
  const reports = (data?.reports || []) as Array<Record<string, unknown>>;
  const intel = (data?.intelligence || {}) as Record<string, unknown>;
  const projects = (intel.project_health || intel.projects || []) as Array<Record<string, unknown>>;
  const shared = (intel.shared_components || intel.shared || []) as Array<Record<string, unknown>>;

  return (
    <Shell session={session}>
      <PageHeader meta={PAGE_META.portfolio} actions={<PrimaryLink href="/reports">Open saved analyses</PrimaryLink>} />
      {typeof data?.gap === "string" ? <GapBanner>{String(data.gap)}</GapBanner> : null}
      {busy ? <LoadingCard label="Loading portfolio intelligence…" /> : null}
      {error ? <div className="cv-error" role="alert">Portfolio data could not load. {error}</div> : null}
      {!busy && data ? (
        reports.length ? <>
          <div className="cv-kpis">
            <KpiCard icon="report" tone="blue" label="Saved analyses" value={reports.length} detail="Reports in this workspace" />
            <KpiCard icon="portfolio" label="Projects represented" value={projects.length} detail="Projects with saved BOM records" />
            <KpiCard icon="box" tone="amber" label="Shared components" value={shared.length} detail="Parts appearing in multiple BOMs" />
          </div>
          <div className="cv-grid-2">
            <section className="cv-card pad">
              <h3 className="cv-card-title">Analyses</h3>
              {reports.length ? <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead><tr><th>File</th><th>Health</th><th>Parts</th><th>High</th></tr></thead>
                  <tbody>
                    {reports.map((r, i) => (
                      <tr key={i}>
                        <td><strong>{String(r.filename || "")}</strong></td>
                        <td>{String(r.health_score ?? "—")}</td>
                        <td>{String(r.total_parts ?? "—")}</td>
                        <td>{String(r.high_risk_count ?? "—")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div> : <EmptyState icon="report" title="No analyses to summarize" body="Save a BOM analysis to see it included in the portfolio." action={<PrimaryLink href="/bom-analyzer">New BOM analysis</PrimaryLink>} />}
            </section>
            <section className="cv-card pad">
              <h3 className="cv-card-title">Project health</h3>
              {projects.length ? <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead><tr><th>Project</th><th>Health</th><th>Components</th><th>High-risk</th></tr></thead>
                  <tbody>
                    {projects.slice(0, 20).map((r, i) => (
                      <tr key={i}>
                        <td><strong>{String(r.Project || r.project || "")}</strong></td>
                        <td>{String(r.Health ?? r.health ?? "—")}</td>
                        <td>{String(r.Components ?? r.components ?? "—")}</td>
                        <td>{String(r["High-Risk"] ?? r.high_risk ?? "—")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div> : <EmptyState icon="portfolio" title="No project roll-up available" body="Project health appears after a BOM is saved with a project name." />}
            </section>
          </div>
        </> : <EmptyState icon="portfolio" title="Your portfolio is ready for its first BOM" body="Portfolio insights appear after you save one or more BOM analyses to this workspace." action={<PrimaryLink href="/bom-analyzer">Start a BOM analysis</PrimaryLink>} />
      ) : null}
    </Shell>
  );
}


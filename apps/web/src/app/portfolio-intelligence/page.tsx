"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
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
      <PageHeader meta={PAGE_META.portfolio} actions={<PrimaryLink href="/bom-analyzer">New analysis</PrimaryLink>} />
      {typeof data?.gap === "string" ? <GapBanner>{String(data.gap)}</GapBanner> : null}
      {busy ? <LoadingCard label="Loading portfolio intelligence…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}
      {!busy && data ? (
        <>
          <div className="cv-kpis">
            <div className="cv-kpi tone-blue"><span>Saved analyses</span><strong>{reports.length}</strong><em>From this workspace</em></div>
            <div className="cv-kpi"><span>Project rows</span><strong>{projects.length}</strong><em>From saved analyses</em></div>
            <div className="cv-kpi tone-amber"><span>Shared components</span><strong>{shared.length}</strong><em>Across analyses</em></div>
            <div className="cv-kpi"><span>Data scope</span><strong style={{ fontSize: 14 }}>This workspace</strong><em>Current app history is not included</em></div>
          </div>
          <div className="cv-grid-2">
            <section className="cv-card pad">
              <h3 className="cv-card-title">Analyses</h3>
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
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
              </div>
            </section>
            <section className="cv-card pad">
              <h3 className="cv-card-title">Project health</h3>
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
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
              </div>
            </section>
          </div>
        </>
      ) : null}
    </Shell>
  );
}

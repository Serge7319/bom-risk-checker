"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { Shell } from "@/components/Shell";
import { listReports } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

export default function ReportsIndexPage() {
  const session = useRequireSession();
  const [reports, setReports] = useState<Array<Record<string, unknown>>>([]);
  const [gap, setGap] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    if (!session) return;
    listReports(session.access_token)
      .then((payload) => {
        setReports(payload.reports || []);
        setGap(payload.gap || "");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"))
      .finally(() => setBusy(false));
  }, [session]);

  if (!session) return null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.reports}
        actions={<PrimaryLink href="/bom-analyzer">New BOM analysis</PrimaryLink>}
      />
      {gap ? <GapBanner>{gap}</GapBanner> : null}
      {busy ? <LoadingCard label="Loading saved reports…" /> : null}
      {error ? <div className="cv-error" role="alert">Reports could not load. {error}</div> : null}
      {!busy && !error ? (
        reports.length ? (
          <section className="cv-card pad">
            <div className="cv-section-heading cv-section-heading--card">
              <div>
                <h2>Saved analyses</h2>
                <p>Open a report to inspect component signals and evidence.</p>
              </div>
              <span className="cv-data-note">{reports.length} report{reports.length === 1 ? "" : "s"}</span>
            </div>
            <div className="cv-table-wrap">
              <table className="cv-table">
                <thead>
                  <tr>
                    <th>Analysis</th>
                    <th>Health</th>
                    <th>Components</th>
                    <th>High risk</th>
                    <th>Saved</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {reports.map((row) => {
                    const id = String(row.id || row.analysis_id || "");
                    return (
                      <tr key={id}>
                        <td><strong>{String(row.filename || row.bom_name || id)}</strong></td>
                        <td>{row.health_score == null ? "Not scored" : `${String(row.health_score)}/100`}</td>
                        <td>{String(row.total_parts ?? "—")}</td>
                        <td>{String(row.high_risk_count ?? "—")}</td>
                        <td>{row.created_at ? new Date(String(row.created_at)).toLocaleDateString() : "—"}</td>
                        <td><Link className="cv-button small" href={`/reports/${encodeURIComponent(id)}`}>Open report</Link></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        ) : (
          <EmptyState
            icon="report"
            title="No saved reports yet"
            body="Completed BOM analyses are saved to this workspace and appear here for you to reopen."
            action={<PrimaryLink href="/bom-analyzer">Start a BOM analysis</PrimaryLink>}
          />
        )
      ) : null}
    </Shell>
  );
}

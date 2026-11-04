"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { listReports } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

export default function ReportsIndexPage() {
  const session = useRequireSession();
  const [reports, setReports] = useState<Array<Record<string, unknown>>>([]);
  const [gap, setGap] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const last = typeof window !== "undefined" ? readLastAnalysis() : null;

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
        actions={<PrimaryLink href="/bom-analyzer">New analysis</PrimaryLink>}
      />
      {gap ? <GapBanner>{gap}</GapBanner> : null}
      {busy ? <LoadingCard label="Loading in-memory reports…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}
      {!busy ? (
        <>
          <div className="cv-kpis">
            <div className="cv-kpi tone-blue">
              <span>API reports</span>
              <strong>{reports.length}</strong>
              <em>Current sandbox process</em>
            </div>
            <div className="cv-kpi">
              <span>Browser latest</span>
              <strong>{last ? 1 : 0}</strong>
              <em>localStorage pointer</em>
            </div>
            <div className="cv-kpi tone-amber">
              <span>Persistence</span>
              <strong style={{ fontSize: 14 }}>Gap</strong>
              <em>Not durable yet</em>
            </div>
            <div className="cv-kpi">
              <span>Auth</span>
              <strong style={{ fontSize: 14 }}>Smoke</strong>
              <em>Sandbox only</em>
            </div>
          </div>
          {reports.length ? (
            <section className="cv-card pad">
              <div className="cv-table-wrap">
                <table className="cv-table">
                  <thead>
                    <tr>
                      <th>Analysis</th>
                      <th>Health</th>
                      <th>Parts</th>
                      <th>High</th>
                      <th>Created</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {reports.map((row) => {
                      const id = String(row.id || row.analysis_id || "");
                      return (
                        <tr key={id}>
                          <td>
                            <strong>{String(row.filename || id)}</strong>
                          </td>
                          <td>{String(row.health_score ?? "—")}</td>
                          <td>{String(row.total_parts ?? "—")}</td>
                          <td>{String(row.high_risk_count ?? "—")}</td>
                          <td>
                            {row.created_at
                              ? new Date(String(row.created_at)).toLocaleString()
                              : "—"}
                          </td>
                          <td>
                            <Link className="cv-button small" href={`/reports/${id}`}>
                              Open
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          ) : (
            <section className="cv-empty">
              No in-memory reports yet.{" "}
              <Link href="/bom-analyzer">Analyze a BOM</Link> to create one.
            </section>
          )}
        </>
      ) : null}
    </Shell>
  );
}

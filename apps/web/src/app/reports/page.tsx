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
  const [persistence, setPersistence] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const last = typeof window !== "undefined" ? readLastAnalysis() : null;

  useEffect(() => {
    if (!session) return;
    listReports(session.access_token)
      .then((payload) => {
        setReports(payload.reports || []);
        setGap(payload.gap || "");
        setPersistence(payload.persistence || "");
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
      {busy ? <LoadingCard label="Loading saved reports…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}
      {!busy && !error ? (
        <>
          <div className="cv-kpis">
            <div className="cv-kpi tone-blue">
              <span>Saved analyses</span>
              <strong>{reports.length}</strong>
              <em>Saved to this workspace</em>
            </div>
            <div className="cv-kpi">
              <span>Recent shortcut</span>
              <strong>{last ? 1 : 0}</strong>
              <em>{last ? "Saved on this device" : "None on this device"}</em>
            </div>
            <div className="cv-kpi tone-amber">
              <span>Storage</span>
              <strong style={{ fontSize: 14 }}>
                {persistence === "postgres" ? "Workspace" : "Local preview"}
              </strong>
              <em>
                {persistence === "postgres"
                  ? "Saved in your workspace"
                  : "Temporary local data"}
              </em>
            </div>
            <div className="cv-kpi">
              <span>Record access</span>
              <strong style={{ fontSize: 14 }}>Workspace</strong>
              <em>Scoped to this account</em>
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
              No saved reports yet.{" "}
              <Link href="/bom-analyzer">Analyze a BOM</Link> to create one.
            </section>
          )}
        </>
      ) : null}
    </Shell>
  );
}

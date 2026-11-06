"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { LoadingCard } from "@/components/GapBanner";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { listReports, type AnalyzeSummary } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

export default function EngineeringDecisionsPage() {
  const session = useRequireSession();
  const [last, setLast] = useState<
    (AnalyzeSummary & { filename?: string; saved_at?: string }) | null
  >(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    if (!session) return;
    listReports(session.access_token)
      .then(({ reports }) => {
        const row = reports[0];
        setLast(row ? {
          analysis_id: String(row.analysis_id || row.id || ""),
          total_parts: Number(row.total_parts || 0),
          health_score: row.health_score == null ? null : Number(row.health_score),
          health_status: String(row.health_status || "—"),
          high_risk_count: Number(row.high_risk_count || 0),
          medium_risk_count: Number(row.medium_risk_count || 0),
          low_risk_count: Number(row.low_risk_count || 0),
          mode: String(row.mode || "synthetic-preview"),
          filename: String(row.filename || "Saved BOM analysis"),
          saved_at: String(row.created_at || ""),
        } : null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unable to load saved analyses."))
      .finally(() => setBusy(false));
  }, [session]);

  if (!session) return null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.decisions}
        actions={
          <>
            <PrimaryLink href="/bom-analyzer">New BOM analysis</PrimaryLink>
            <SecondaryLink href="/reports">Reports</SecondaryLink>
          </>
        }
      />

      <div className="cv-decision-banner">
        <div>
          <strong>Signals are evidence prompts</strong>
          <span>
            They are not automatic approval or fit verdicts. Counts below come
            from the latest saved analysis when available.
          </span>
        </div>
      </div>

      {busy ? <LoadingCard label="Loading the latest saved analysis…" /> : null}
      {error ? <div className="cv-error" role="alert">The decision queue could not load. {error}</div> : null}

      {last ? (
        <div className="cv-kpis">
          <KpiCard icon="risk" tone="amber" label="High priority" value={last.high_risk_count} detail="Engineering review recommended" />
          <KpiCard icon="clock" tone="blue" label="Medium priority" value={last.medium_risk_count} detail="Confirm the evidence is current" />
          <KpiCard icon="check" label="Low priority" value={last.low_risk_count} detail="Lower risk signals in this BOM" />
        </div>
      ) : null}

      {!busy && !error && last?.analysis_id ? (
        <section className="cv-card pad">
          <div style={{ marginBottom: 12 }}>
            <h3 className="cv-card-title">Decision queue from latest analysis</h3>
            <p className="cv-card-subtitle">
              {last.filename || "BOM"} · {last.total_parts} parts. Open the report
              for part-level evidence. Supplier prices and fit approvals require verified
              source data, so this report does not infer them.
            </p>
          </div>
          <div className="cv-table-wrap">
            <table className="cv-table">
              <thead>
                <tr>
                  <th>Priority</th>
                  <th>Signal</th>
                  <th>Count</th>
                  <th>Next step</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>
                    <span className="cv-badge red">High</span>
                  </td>
                  <td>
                    <strong>High-risk components</strong>
                    <div className="cv-muted">Needs engineering review</div>
                  </td>
                  <td>{last.high_risk_count}</td>
                  <td>
                    <Link
                      className="cv-button small"
                      href={`/reports/${last.analysis_id}`}
                    >
                      Open report
                    </Link>
                  </td>
                </tr>
                <tr>
                  <td>
                    <span className="cv-badge amber">Medium</span>
                  </td>
                  <td>
                    <strong>Medium-risk follow-ups</strong>
                    <div className="cv-muted">Confirm evidence freshness</div>
                  </td>
                  <td>{last.medium_risk_count}</td>
                  <td>
                    <Link
                      className="cv-button small"
                      href={`/reports/${last.analysis_id}`}
                    >
                      Inspect rows
                    </Link>
                  </td>
                </tr>
                <tr>
                  <td>
                    <span className="cv-badge gray">Not available yet</span>
                  </td>
                  <td>
                    <strong>Saved decision records</strong>
                    <div className="cv-muted">
                      Historical multi-BOM decision records are not included in this workspace.
                    </div>
                  </td>
                  <td>—</td>
                  <td>
                    <span className="cv-small-note">Unavailable in this build</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      ) : !busy && !error ? (
        <EmptyState
          icon="decisions"
          title="No decision signals yet"
          body="Analyze a BOM to see its highest priority component signals and open the supporting report."
          action={<PrimaryLink href="/bom-analyzer">Start a BOM analysis</PrimaryLink>}
        />
      ) : null}
    </Shell>
  );
}


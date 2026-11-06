"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { listReports } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

type LatestReport = {
  analysis_id: string;
  filename: string;
  health_score: number | null;
  health_status: string;
  total_parts: number;
  high_risk_count: number;
  medium_risk_count: number;
  created_at?: string;
};

export default function EngineeringIntelligencePage() {
  const session = useRequireSession();
  const [last, setLast] = useState<LatestReport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    if (!session) return;
    listReports(session.access_token)
      .then(({ reports }) => {
        const row = reports[0];
        if (!row) {
          setLast(null);
          return;
        }
        setLast({
          analysis_id: String(row.analysis_id || row.id || ""),
          filename: String(row.filename || "Saved BOM analysis"),
          health_score: row.health_score == null ? null : Number(row.health_score),
          health_status: String(row.health_status || "—"),
          total_parts: Number(row.total_parts || 0),
          high_risk_count: Number(row.high_risk_count || 0),
          medium_risk_count: Number(row.medium_risk_count || 0),
          created_at: String(row.created_at || ""),
        });
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unable to load saved analyses."))
      .finally(() => setBusy(false));
  }, [session]);

  if (!session) return null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.ei}
        actions={
          <>
            <PrimaryLink href="/bom-analyzer">BOM Analyzer</PrimaryLink>
            <SecondaryLink href="/">Home</SecondaryLink>
          </>
        }
      />

      {last?.analysis_id ? (
        <section className="cv-card pad cv-record-header">
          <div className="cv-eyebrow">Latest saved engineering report</div>
          <h2 className="cv-card-title" style={{ fontSize: 22, marginTop: 8 }}>
            {last.filename || "BOM analysis"}
          </h2>
          <p className="cv-card-subtitle">
            Health {last.health_score ?? "—"}/100 · {last.health_status} ·{" "}
            {last.total_parts} components · {last.high_risk_count} high /{" "}
            {last.medium_risk_count} medium risk
          </p>
          <dl className="cv-record-meta" style={{ marginTop: 16 }}>
            <div className="cv-record-field">
              <dt>Record</dt>
              <dd style={{ fontSize: 11 }}>{last.analysis_id}</dd>
            </div>
            <div className="cv-record-field">
              <dt>Saved</dt>
              <dd>
                {last.created_at
                  ? new Date(last.created_at).toLocaleString()
                  : "—"}
              </dd>
            </div>
            <div className="cv-record-field">
              <dt>Evidence</dt>
              <dd>Synthetic analysis</dd>
            </div>
          </dl>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <Link
              className="cv-button primary"
              href={`/reports/${last.analysis_id}`}
            >
              Open full decision record
            </Link>
            <Link className="cv-button" href="/engineering-decisions">
              Decision queue
            </Link>
          </div>
        </section>
      ) : null}
      {busy ? <LoadingCard label="Loading saved engineering reports…" /> : null}
      {error ? <div className="cv-error" role="alert">Saved engineering reports could not load. {error}</div> : null}
      {!busy && !error && !last ? (
        <EmptyState
          icon="insight"
          title="No engineering report yet"
          body="Run a BOM analysis to create a report with component signals, risk roll-up, and evidence links."
          action={<PrimaryLink href="/bom-analyzer">Start a BOM analysis</PrimaryLink>}
        />
      ) : null}
    </Shell>
  );
}


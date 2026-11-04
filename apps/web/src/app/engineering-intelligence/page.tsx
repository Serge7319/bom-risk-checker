"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import type { AnalyzeSummary } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

export default function EngineeringIntelligencePage() {
  const session = useRequireSession();
  const [last, setLast] = useState<
    (AnalyzeSummary & { filename?: string; saved_at?: string }) | null
  >(null);

  useEffect(() => {
    setLast(readLastAnalysis());
  }, []);

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
          <div className="cv-eyebrow">Latest engineering report · API backed</div>
          <h2 className="cv-card-title" style={{ fontSize: 22, marginTop: 8 }}>
            {last.filename || "Synthetic BOM analysis"}
          </h2>
          <p className="cv-card-subtitle">
            Health {last.health_score ?? "—"}/100 · {last.health_status} ·{" "}
            {last.total_parts} components · {last.high_risk_count} high /{" "}
            {last.medium_risk_count} medium risk
          </p>
          <dl className="cv-record-meta" style={{ marginTop: 16 }}>
            <div className="cv-record-field">
              <dt>Analysis id</dt>
              <dd style={{ fontSize: 11 }}>{last.analysis_id}</dd>
            </div>
            <div className="cv-record-field">
              <dt>Mode</dt>
              <dd>{last.mode}</dd>
            </div>
            <div className="cv-record-field">
              <dt>Saved locally</dt>
              <dd>
                {last.saved_at
                  ? new Date(last.saved_at).toLocaleString()
                  : "—"}
              </dd>
            </div>
            <div className="cv-record-field">
              <dt>Evidence</dt>
              <dd>Synthetic preview</dd>
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
      ) : (
        <section className="cv-empty">
          No engineering intelligence record in this browser yet. Run{" "}
          <Link href="/bom-analyzer">BOM Analyzer</Link> against the sandbox API,
          then return here or open <code>/reports/[id]</code>.
        </section>
      )}

      <section className="cv-card pad" style={{ marginTop: 14 }}>
        <h3 className="cv-card-title">Preview limit</h3>
        <p className="cv-card-subtitle">
          Cross-BOM portfolio intelligence and Streamlit-saved EI packs are not
          mirrored here. Only synthetic analyses created in this Next preview are
          available.
        </p>
      </section>
    </Shell>
  );
}

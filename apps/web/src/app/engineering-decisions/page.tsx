"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import type { AnalyzeSummary } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

export default function EngineeringDecisionsPage() {
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
            from the latest synthetic analysis in this browser when available.
          </span>
        </div>
      </div>

      <div className="cv-kpis">
        <div className="cv-kpi tone-amber">
          <span>High priority</span>
          <strong>{last ? last.high_risk_count : "—"}</strong>
          <em>{last ? "From latest API analysis" : "No analysis yet"}</em>
        </div>
        <div className="cv-kpi tone-blue">
          <span>Medium</span>
          <strong>{last ? last.medium_risk_count : "—"}</strong>
          <em>{last ? "Review recommended" : "Upload a BOM first"}</em>
        </div>
        <div className="cv-kpi">
          <span>Low</span>
          <strong>{last ? last.low_risk_count : "—"}</strong>
          <em>{last ? "Within latest BOM" : "Awaiting data"}</em>
        </div>
        <div className="cv-kpi">
          <span>Health</span>
          <strong>
            {last?.health_score == null ? "—" : `${last.health_score}/100`}
          </strong>
          <em>{last?.health_status || "—"}</em>
        </div>
      </div>

      {last?.analysis_id ? (
        <section className="cv-card pad">
          <div style={{ marginBottom: 12 }}>
            <h3 className="cv-card-title">Decision queue from latest analysis</h3>
            <p className="cv-card-subtitle">
              {last.filename || "BOM"} · {last.total_parts} parts · mode{" "}
              {last.mode}. Open the report for part-level evidence; this preview
              does not invent supplier prices or fit approvals.
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
                    <span className="cv-badge gray">Preview limit</span>
                  </td>
                  <td>
                    <strong>Saved decision records</strong>
                    <div className="cv-muted">
                      Multi-BOM decision history is not mirrored from Streamlit
                    </div>
                  </td>
                  <td>—</td>
                  <td>
                    <span className="cv-small-note">Unsupported in preview</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        <section className="cv-empty">
          No decision queue yet.{" "}
          <Link href="/bom-analyzer">Analyze a BOM</Link> through the sandbox
          API to populate priorities from real risk counts.
        </section>
      )}
    </Shell>
  );
}

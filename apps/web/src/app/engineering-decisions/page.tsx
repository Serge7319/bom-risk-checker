"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { LoadingCard } from "@/components/GapBanner";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import {
  listDecisionRecords,
  listReports,
  type AnalyzeSummary,
  type DecisionRecord,
} from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

export default function EngineeringDecisionsPage() {
  const session = useRequireSession();
  const [last, setLast] = useState<
    (AnalyzeSummary & { filename?: string; saved_at?: string }) | null
  >(null);
  const [error, setError] = useState("");
  const [decisionError, setDecisionError] = useState("");
  const [records, setRecords] = useState<DecisionRecord[]>([]);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    if (!session) return;
    Promise.all([
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
        .catch((err) => setError(err instanceof Error ? err.message : "Unable to load saved analyses.")),
      listDecisionRecords(session.access_token)
        .then(({ records: savedRecords }) => setRecords(savedRecords || []))
        .catch((err) => setDecisionError(err instanceof Error ? err.message : "Unable to load decision records.")),
    ])
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

      {busy ? <LoadingCard label="Loading saved analyses and decision records…" /> : null}
      {error ? <div className="cv-error" role="alert">Engineering decisions could not load. {error}</div> : null}

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

      {!busy ? (
        <section className="cv-card pad cv-decision-history">
          <div className="cv-decision-history-heading">
            <div>
              <div className="cv-eyebrow">Workspace history</div>
              <h2 className="cv-card-title">Recorded engineering decisions</h2>
              <p className="cv-card-subtitle">Human review records include the comparison snapshot available when they were saved. Cadivor does not qualify alternates or change a BOM.</p>
            </div>
            <PrimaryLink href="/compare-parts">Compare parts</PrimaryLink>
          </div>
          {records.length ? (
            <div className="cv-table-wrap" style={{ marginTop: 14 }}>
              <table className="cv-table">
                <thead>
                  <tr>
                    <th>Saved</th>
                    <th>Project / BOM</th>
                    <th>Parts</th>
                    <th>Decision / reviewer</th>
                    <th>Rationale and evidence status</th>
                    <th>Record</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((record) => (
                    <tr key={record.id}>
                      <td>{record.created_at ? new Date(record.created_at).toLocaleDateString() : "—"}</td>
                      <td>
                        <strong>{record.project_name || "Workspace"}</strong>
                        <div className="cv-muted">{record.bom_name || "No BOM linked"}{record.revision ? ` · rev ${record.revision}` : ""}</div>
                      </td>
                      <td><strong>{record.part_a} → {record.part_b}</strong></td>
                      <td>
                        <span className="cv-badge blue">{record.decision_label}</span>
                        <div className="cv-muted">{record.reviewer}</div>
                      </td>
                      <td>
                        <div>{record.rationale}</div>
                        {record.validation_checks?.length ? (
                          <div className="cv-small-note">
                            Checks completed: {record.validation_checks.map((item) => item.replaceAll("_", " ")).join(" · ")}
                          </div>
                        ) : null}
                        {record.follow_up_action ? (
                          <div className="cv-small-note">
                            Follow-up: {record.follow_up_action}
                            {record.follow_up_owner ? ` · ${record.follow_up_owner}` : ""}
                            {record.follow_up_due_date ? ` · due ${record.follow_up_due_date}` : ""}
                          </div>
                        ) : null}
                        <div className="cv-small-note">Residual risk: {record.residual_risk || "not assessed"}</div>
                        <div className="cv-small-note">{record.qualification_note}</div>
                      </td>
                      <td>
                        {record.analysis_id ? (
                          <Link className="cv-button small" href={`/reports/${encodeURIComponent(record.analysis_id)}`}>Open report</Link>
                        ) : <span className="cv-small-note">Workspace record</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            decisionError ? (
              <div className="cv-error" role="alert">Saved decisions could not load. {decisionError}</div>
            ) : <EmptyState
              icon="decisions"
              title="No decisions recorded yet"
              body="Compare two parts, choose Record a decision, and save a reviewer, rationale, and evidence snapshot here."
              action={<PrimaryLink href="/compare-parts">Open Compare Parts</PrimaryLink>}
            />
          )}
        </section>
      ) : null}
    </Shell>
  );
}


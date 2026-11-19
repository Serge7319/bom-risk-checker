"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AnalysisStageNavigation } from "@/components/AnalysisStageNavigation";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { LoadingCard } from "@/components/GapBanner";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import {
  createDecisionRecordShare,
  inviteDecisionApprover,
  listDecisionRecords,
  listReports,
  type AnalyzeSummary,
  type DecisionRecord,
} from "@/lib/api";
import { cleanUserText, userFacingLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

function EngineeringDecisionsPageInner() {
  const searchParams = useSearchParams();
  const requestedAnalysisId = (searchParams.get("analysis_id") || "").trim();
  const session = useRequireSession();
  const [last, setLast] = useState<
    (AnalyzeSummary & { filename?: string; saved_at?: string }) | null
  >(null);
  const [error, setError] = useState("");
  const [decisionError, setDecisionError] = useState("");
  const [records, setRecords] = useState<DecisionRecord[]>([]);
  const [shareBusy, setShareBusy] = useState("");
  const [shareLinks, setShareLinks] = useState<Record<string, string>>({});
  const [shareCopied, setShareCopied] = useState("");
  const [shareError, setShareError] = useState("");
  const [approverEmails, setApproverEmails] = useState<Record<string, string>>({});
  const [approverBusy, setApproverBusy] = useState("");
  const [approverNotice, setApproverNotice] = useState("");
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    if (!session) return;
    let active = true;
    setBusy(true);
    setLast(null);
    setRecords([]);
    setError("");
    setDecisionError("");
    Promise.all([
      listReports(session.access_token)
        .then(({ reports }) => {
          if (!active) return;
          const row = requestedAnalysisId
            ? reports.find((report) => String(report.analysis_id || report.id || "") === requestedAnalysisId)
            : reports[0];
          if (requestedAnalysisId && !row) {
            setLast(null);
            setError("The selected saved analysis could not be found in this workspace.");
            return;
          }
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
      listDecisionRecords(session.access_token, requestedAnalysisId || undefined)
        .then(({ records: savedRecords }) => {
          if (active) setRecords(savedRecords || []);
        })
        .catch((err) => {
          if (active) setDecisionError(err instanceof Error ? err.message : "Unable to load decision records.");
        }),
    ])
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [session, requestedAnalysisId]);

  if (!session) return null;

  async function createShareLink(record: DecisionRecord) {
    const id = String(record.id || record.decision_id || "");
    const accessToken = session?.access_token;
    if (!id || !accessToken) return;
    setShareBusy(id);
    setShareError("");
    try {
      const result = await createDecisionRecordShare(accessToken, id);
      setShareLinks((current) => ({
        ...current,
        [id]: `${window.location.origin}/decision-share/${encodeURIComponent(result.token)}`,
      }));
    } catch (err) {
      setShareError(err instanceof Error ? err.message : "Could not create a share link.");
    } finally {
      setShareBusy("");
    }
  }

  async function copyShareLink(id: string) {
    const link = shareLinks[id];
    if (!link) return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard access is unavailable.");
      await navigator.clipboard.writeText(link);
      setShareCopied(id);
      setShareError("");
    } catch {
      setShareError("Copy was unavailable. Select the share link field and copy it manually.");
    }
  }

  async function sendApproverInvite(record: DecisionRecord) {
    const id = String(record.id || record.decision_id || "");
    const email = String(approverEmails[id] || "").trim();
    const accessToken = session?.access_token;
    if (!id || !email || !accessToken || approverBusy) return;
    setApproverBusy(id);
    setApproverNotice("");
    setShareError("");
    try {
      await inviteDecisionApprover(accessToken, id, email);
      setApproverEmails((current) => ({ ...current, [id]: "" }));
      setApproverNotice(`Approval invitation sent to ${email}. It grants access to this decision only and expires in seven days.`);
    } catch (err) {
      setShareError(err instanceof Error ? err.message : "Could not send the approval invitation.");
    } finally {
      setApproverBusy("");
    }
  }

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

      <AnalysisStageNavigation
        analysisId={last?.analysis_id || requestedAnalysisId}
        current="decision"
      />

      <p className="cv-evidence-context" role="note">
        Signals are evidence prompts, not automatic approvals. {requestedAnalysisId
          ? "Counts and records are scoped to the selected saved analysis."
          : "Counts reflect the latest saved analysis when available."}
      </p>

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
            <h3 className="cv-card-title">Decision queue from {requestedAnalysisId ? "selected analysis" : "latest analysis"}</h3>
            <p className="cv-card-subtitle">
              {userFacingLabel(last.filename, "BOM")} · {last.total_parts} parts. Open the report
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
              <p className="cv-card-subtitle">User review records include the comparison snapshot available when they were saved. Cadivor does not qualify alternates or change a BOM.</p>
            </div>
            <PrimaryLink href="/compare-parts">Compare parts</PrimaryLink>
          </div>
          {shareError ? <div className="cv-error" role="alert">{shareError}</div> : null}
          {approverNotice ? <div className="cv-evidence-context" role="status">{approverNotice}</div> : null}
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
                        <strong>{userFacingLabel(record.project_name, "Workspace")}</strong>
                        <div className="cv-muted">
                          {record.analysis_id
                            ? `${userFacingLabel(record.bom_name, "Saved BOM")}${record.revision ? ` · rev ${cleanUserText(record.revision)}` : ""}`
                            : "No BOM — workspace-level decision"}
                        </div>
                      </td>
                      <td>
                        <strong>
                          {record.part_a}
                          {record.manufacturer_a ? ` (${record.manufacturer_a})` : ""}
                          {" → "}
                          {record.part_b}
                          {record.manufacturer_b ? ` (${record.manufacturer_b})` : ""}
                        </strong>
                        {(() => {
                          const snapshot = (record.comparison_snapshot || {}) as Record<string, unknown>;
                          const multiMpns = Array.isArray(snapshot.multi_candidate_mpns)
                            ? (snapshot.multi_candidate_mpns as unknown[]).map((item) => String(item || "").trim()).filter(Boolean)
                            : [];
                          const brands = (snapshot.multi_candidate_manufacturers || {}) as Record<string, unknown>;
                          if (multiMpns.length < 2) return null;
                          return (
                            <div className="cv-small-note" data-testid="decision-multi-manufacturers">
                              {multiMpns.map((mpn) => {
                                const brand = String(brands[mpn] || "").trim();
                                return brand ? `${mpn} · ${brand}` : mpn;
                              }).join(" · ")}
                            </div>
                          );
                        })()}
                      </td>
                      <td>
                        <span className="cv-badge blue">{record.decision_label}</span>
                        <div className="cv-muted">{record.reviewer}</div>
                      </td>
                      <td>
                        <div>{cleanUserText(record.rationale)}</div>
                        {record.validation_checks?.length ? (
                          <div className="cv-small-note">
                            Checks completed: {record.validation_checks.map((item) => item.replaceAll("_", " ")).join(" · ")}
                          </div>
                        ) : null}
                        {record.follow_up_action ? (
                          <div className="cv-small-note">
                            Follow-up: {cleanUserText(record.follow_up_action)}
                            {record.follow_up_owner ? ` · ${cleanUserText(record.follow_up_owner)}` : ""}
                            {record.follow_up_due_date ? ` · due ${record.follow_up_due_date}` : ""}
                          </div>
                        ) : null}
                        <div className="cv-small-note">Residual risk: {record.residual_risk || "not assessed"}</div>
                        {(() => {
                          const snapshot = (record.comparison_snapshot || {}) as Record<string, unknown>;
                          const finding = snapshot.finding ? String(snapshot.finding) : "";
                          const evidenceStatus = String(
                            snapshot.engineering_evidence_status
                            || (record.verified_primary_evidence ? "verified" : "unverified"),
                          );
                          const sourceA = cleanUserText(snapshot.source_a);
                          const sourceB = cleanUserText(snapshot.source_b);
                          return (
                            <>
                              {finding ? <div className="cv-small-note">Compare finding: {finding}</div> : null}
                              <div className="cv-small-note">Snapshot evidence: {evidenceStatus}</div>
                              {sourceA || sourceB ? (
                                <div className="cv-small-note">
                                  Sources: {sourceA || "unverified"} → {sourceB || "unverified"}
                                </div>
                              ) : null}
                            </>
                          );
                        })()}
                        <div className="cv-small-note">{record.qualification_note}</div>
                      </td>
                      <td>
                        {record.analysis_id ? (
                          <Link className="cv-button small" href={`/reports/${encodeURIComponent(record.analysis_id)}`}>Open report</Link>
                        ) : <span className="cv-small-note">Workspace record</span>}
                        <div style={{ marginTop: 8 }}>
                          <button
                            className="cv-button small"
                            type="button"
                            disabled={shareBusy === (record.id || record.decision_id)}
                            onClick={() => void createShareLink(record)}
                          >
                            {shareBusy === (record.id || record.decision_id)
                              ? "Creating link…"
                              : shareLinks[record.id || record.decision_id]
                                ? "Create new link"
                                : "Share read-only"}
                          </button>
                        </div>
                        {shareLinks[record.id || record.decision_id] ? (
                          <div className="cv-decision-share-link">
                            <input
                              aria-label="Read-only decision share link"
                              readOnly
                              value={shareLinks[record.id || record.decision_id]}
                              onFocus={(event) => event.currentTarget.select()}
                            />
                            <button className="cv-button small" type="button" onClick={() => void copyShareLink(record.id || record.decision_id)}>
                              {shareCopied === (record.id || record.decision_id) ? "Copied" : "Copy link"}
                            </button>
                            <span className="cv-small-note">Anyone with this link can view it for 7 days.</span>
                          </div>
                        ) : null}
                        <div className="cv-decision-approver-invite">
                          <label htmlFor={`approver-email-${record.id || record.decision_id}`}>Invite an approver</label>
                          <input
                            id={`approver-email-${record.id || record.decision_id}`}
                            type="email"
                            placeholder="approver@company.com"
                            value={approverEmails[record.id || record.decision_id] || ""}
                            onChange={(event) => setApproverEmails((current) => ({
                              ...current,
                              [record.id || record.decision_id]: event.target.value,
                            }))}
                          />
                          <button
                            className="cv-button small"
                            type="button"
                            disabled={!approverEmails[record.id || record.decision_id]?.trim() || approverBusy === (record.id || record.decision_id)}
                            onClick={() => void sendApproverInvite(record)}
                          >
                            {approverBusy === (record.id || record.decision_id) ? "Sending…" : "Send approval request"}
                          </button>
                          <span className="cv-small-note">The recipient can approve or reject this record without joining your workspace.</span>
                        </div>
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

export default function EngineeringDecisionsPage() {
  return (
    <Suspense fallback={null}>
      <EngineeringDecisionsPageInner />
    </Suspense>
  );
}


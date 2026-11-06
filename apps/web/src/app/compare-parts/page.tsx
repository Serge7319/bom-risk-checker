"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { EmptyState } from "@/components/EmptyState";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { Shell } from "@/components/Shell";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import {
  compareParts,
  listReports,
  recordDecision,
  type DecisionRecord,
} from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

type Row = Record<string, unknown>;

function text(value: unknown, fallback = "—") {
  const valueText = String(value ?? "").trim();
  return valueText || fallback;
}

function getAnalysisId(row: Row) {
  return String(row.analysis_id || row.id || "");
}

function reportLabel(row: Row) {
  const bom = text(row.bom_name || row.filename || row.project_name, "Saved analysis");
  const revision = row.revision ? ` · rev ${String(row.revision)}` : "";
  const project = row.project_name && row.project_name !== bom ? `${String(row.project_name)} · ` : "";
  return `${project}${bom}${revision}`;
}

function isUnknown(row: Row) {
  const assessment = text(row.Assessment || row.assessment || row.Status || "").toLowerCase();
  return assessment.includes("unable to confirm") || assessment.includes("needs data") || assessment.includes("needs validation");
}

function evidenceLabel(source: unknown) {
  const value = String(source || "").toLowerCase();
  if (value.includes("verified")) return "Verified source evidence";
  if (value.includes("analysis")) return "Saved analysis fields · synthetic";
  return "Offline identity catalog · synthetic";
}

function reportDate(value: unknown) {
  if (!value) return "recently";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime())
    ? "recently"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function replacementHref(partNumber: string, analysisId: string) {
  const query = new URLSearchParams();
  if (partNumber.trim()) query.set("mpn", partNumber.trim());
  if (analysisId) query.set("analysis_id", analysisId);
  const suffix = query.toString();
  return suffix ? `/find-replacement?${suffix}` : "/find-replacement";
}

function ComparePartsInner() {
  const session = useRequireSession();
  const search = useSearchParams();
  const dialogRef = useRef<HTMLDivElement>(null);
  const [partA, setPartA] = useState("");
  const [partB, setPartB] = useState("");
  const [analysisId, setAnalysisId] = useState("");
  const [reports, setReports] = useState<Row[]>([]);
  const [reportsError, setReportsError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Row | null>(null);
  const [decisionOpen, setDecisionOpen] = useState(false);
  const [decisionAnalysisId, setDecisionAnalysisId] = useState("");
  const [decisionPartA, setDecisionPartA] = useState("");
  const [decisionPartB, setDecisionPartB] = useState("");
  const [decision, setDecision] = useState("hold_for_review");
  const [reviewer, setReviewer] = useState("");
  const [rationale, setRationale] = useState("");
  const [verifiedPrimaryEvidence, setVerifiedPrimaryEvidence] = useState(false);
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [decisionError, setDecisionError] = useState("");
  const [decisionSuccess, setDecisionSuccess] = useState<DecisionRecord | null>(null);

  useEffect(() => {
    const a = (search.get("part_a") || search.get("a") || "").trim();
    const b = (search.get("part_b") || search.get("b") || "").trim();
    if (a) setPartA(a);
    if (b) setPartB(b);
  }, [search]);

  useEffect(() => {
    if (!session) return;
    let active = true;
    const queryAnalysis = (search.get("analysis_id") || "").trim();
    const last = readLastAnalysis(session);
    const preferredAnalysis = queryAnalysis || last?.analysis_id || "";
    setAnalysisId(preferredAnalysis);
    setReviewer(session.email || "");
    listReports(session.access_token)
      .then(({ reports: rows }) => {
        if (active) {
          setReports(rows || []);
          if (!preferredAnalysis && rows?.[0]) {
            const defaultAnalysis = getAnalysisId(rows[0]);
            setAnalysisId(defaultAnalysis);
            setDecisionAnalysisId((current) => current || defaultAnalysis);
          }
        }
      })
      .catch((err) => {
        if (active) setReportsError(err instanceof Error ? err.message : "Saved BOMs could not load.");
      });
    return () => {
      active = false;
    };
  }, [session, search]);

  useEffect(() => {
    if (!decisionOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !decisionBusy) setDecisionOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    dialogRef.current?.querySelector<HTMLElement>("select, input, textarea, button")?.focus();
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [decisionOpen, decisionBusy]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    setBusy(true);
    setError("");
    setResult(null);
    setDecisionSuccess(null);
    try {
      const last = readLastAnalysis(session);
      const selectedAnalysis = analysisId || last?.analysis_id;
      const data = await compareParts(session.access_token, partA, partB, selectedAnalysis);
      setResult(data);
      if (data.analysis_id) setAnalysisId(String(data.analysis_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Compare failed");
    } finally {
      setBusy(false);
    }
  }

  function openDecisionDialog() {
    setDecisionAnalysisId(String(result?.analysis_id || analysisId || ""));
    setDecisionPartA(String(result?.part_a || partA || ""));
    setDecisionPartB(String(result?.part_b || partB || ""));
    setDecision("hold_for_review");
    setReviewer(session?.email || "");
    setRationale("");
    setVerifiedPrimaryEvidence(false);
    setDecisionError("");
    setDecisionSuccess(null);
    setDecisionOpen(true);
  }

  async function changeDecisionAnalysis(nextAnalysisId: string) {
    if (!session) return;
    const previousAnalysisId = decisionAnalysisId;
    setDecisionAnalysisId(nextAnalysisId);
    if (!result) return;
    setDecisionBusy(true);
    setDecisionError("");
    try {
      const data = await compareParts(
        session.access_token,
        decisionPartA || String(result.part_a || partA),
        decisionPartB || String(result.part_b || partB),
        nextAnalysisId || undefined,
      );
      setResult(data);
      setAnalysisId(String(data.analysis_id || ""));
      setDecisionAnalysisId(String(data.analysis_id || nextAnalysisId || ""));
    } catch (err) {
      setDecisionAnalysisId(previousAnalysisId);
      setDecisionError(err instanceof Error ? err.message : "Could not refresh the comparison for that BOM.");
    } finally {
      setDecisionBusy(false);
    }
  }

  async function onRecordDecision(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    if (!decisionPartA.trim() || !decisionPartB.trim()) {
      setDecisionError("Enter both manufacturer part numbers before recording this decision.");
      return;
    }
    setDecisionBusy(true);
    setDecisionError("");
    try {
      const resultMatchesDraft =
        result &&
        String(result.part_a || "").trim().toLowerCase() === decisionPartA.trim().toLowerCase() &&
        String(result.part_b || "").trim().toLowerCase() === decisionPartB.trim().toLowerCase() &&
        String(result.analysis_id || "") === String(decisionAnalysisId || "");
      const comparison = resultMatchesDraft
        ? result
        : await compareParts(
            session.access_token,
            decisionPartA.trim(),
            decisionPartB.trim(),
            decisionAnalysisId || undefined,
          );
      setResult(comparison);
      const response = await recordDecision(session.access_token, {
        analysis_id: String(comparison.analysis_id || decisionAnalysisId || "") || null,
        part_a: decisionPartA.trim(),
        part_b: decisionPartB.trim(),
        decision,
        reviewer,
        rationale,
        verified_primary_evidence: verifiedPrimaryEvidence,
      });
      setDecisionSuccess(response.record);
      setDecisionOpen(false);
    } catch (err) {
      setDecisionError(err instanceof Error ? err.message : "Decision could not be recorded.");
    } finally {
      setDecisionBusy(false);
    }
  }

  if (!session) return null;

  const rows = (result?.rows || []) as Row[];
  const knownRows = rows.filter((row) => !isUnknown(row));
  const unknownRows = rows.filter(isUnknown);
  const cards = (result?.part_cards || {}) as { a?: Row; b?: Row };
  const evidenceSources = (result?.evidence_sources || {}) as { part_a?: unknown[]; part_b?: unknown[] };
  const resultFinding = text(result?.finding, "No compatibility conclusion");
  const evidenceCounts = (result?.counts || {}) as Record<string, unknown>;
  const reportOptions = [...reports];
  if (decisionAnalysisId && !reportOptions.some((row) => getAnalysisId(row) === decisionAnalysisId)) {
    reportOptions.unshift({ id: decisionAnalysisId, project_name: "Current comparison", bom_name: "Saved analysis context" });
  }

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.compare}
        actions={
          <>
            <span className={`cv-compare-state${result ? " preview" : ""}`}>
              <i aria-hidden="true" />
              {result ? "Sample / offline evidence" : "Ready to compare"}
            </span>
            <SecondaryLink href={replacementHref(String(result?.part_a || partA), String(result?.analysis_id || analysisId))}>Find a replacement</SecondaryLink>
            <button
              type="button"
              className="cv-button primary"
              onClick={openDecisionDialog}
              aria-describedby="record-decision-help"
            >
              +&nbsp; Record a decision
            </button>
          </>
        }
      />

      <form className="cv-card pad cv-compare-input-card" onSubmit={onSubmit}>
        <div className="cv-form-grid">
          <div className="cv-field">
            <label htmlFor="part-a">Part A · current design</label>
            <input
              id="part-a"
              value={partA}
              onChange={(e) => setPartA(e.target.value)}
              placeholder="Manufacturer part number"
              autoComplete="off"
              required
            />
          </div>
          <div className="cv-field">
            <label htmlFor="part-b">Part B · candidate</label>
            <input
              id="part-b"
              value={partB}
              onChange={(e) => setPartB(e.target.value)}
              placeholder="Manufacturer part number"
              autoComplete="off"
              required
            />
          </div>
        </div>
        <div className="cv-compare-form-footer">
          <div>
            {reports.length ? (
              <p className="cv-small-note">
                Comparing against {reportLabel(reports.find((row) => getAnalysisId(row) === analysisId) || reports[0])}.
              </p>
            ) : reportsError ? (
              <p className="cv-small-note">{reportsError} You can still compare without a saved BOM.</p>
            ) : (
              <p className="cv-small-note">BOM context is optional. Source data stays labeled.</p>
            )}
            <span className="cv-small-note" id="record-decision-help">
              {result ? "The recorded decision will include this comparison snapshot." : "Compare two parts to enable decision recording."}
            </span>
          </div>
          <button className="cv-button primary" type="submit" disabled={busy || !partA.trim() || !partB.trim()}>
            {busy ? "Comparing…" : "Compare parts"}
          </button>
        </div>
      </form>

      {busy ? <LoadingCard label="Comparing available part attributes and evidence…" /> : null}
      {error ? <div className="cv-error" role="alert">The comparison could not complete. {error}</div> : null}
      {decisionSuccess ? (
        <div className="cv-success" role="status">
          <span>Decision recorded for {decisionSuccess.part_a} → {decisionSuccess.part_b}.</span>
          <Link href={decisionSuccess.analysis_id ? `/engineering-decisions?analysis_id=${encodeURIComponent(decisionSuccess.analysis_id)}` : "/engineering-decisions"}>
            Open Engineering Decisions →
          </Link>
        </div>
      ) : null}

      {result ? (
        <>
          {typeof result.gap === "string" ? <GapBanner>{String(result.gap)}</GapBanner> : null}

          <div className="cv-compare-screening" role="status">
            <span className="cv-compare-screening-icon" aria-hidden="true">!</span>
            <div>
              <strong>{resultFinding}</strong>
              <p>{text(result.engineering_evidence_summary, "No primary manufacturer evidence was retrieved for this comparison.")}</p>
            </div>
          </div>

          <div className="cv-compare-parts-grid">
            {([
              ["a", "Part A · current design", result.part_a],
              ["b", "Part B · candidate", result.part_b],
            ] as Array<[string, string, unknown]>).map(([key, heading, mpn]) => {
              const card = (key === "a" ? cards.a : cards.b) || {};
              const source = key === "a" ? result.source_a : result.source_b;
              const sourceRows = (key === "a" ? evidenceSources.part_a : evidenceSources.part_b) || [];
              const manufacturer = text(card.manufacturer, "Manufacturer not confirmed");
              const description = text(card.description, "No verified description available.");
              const lifecycle = text(card.lifecycle_status, "Not confirmed");
              return (
                <section className="cv-card pad cv-compare-part-card" key={key}>
                  <div className="cv-compare-part-top">
                    <div>
                      <span className="cv-compare-part-label">{heading}</span>
                      <h2>{text(mpn)}</h2>
                      <p>{manufacturer}{description !== "No verified description available." ? ` · ${description}` : ""}</p>
                    </div>
                    <span className="cv-badge gray">{lifecycle}</span>
                  </div>
                  <div className="cv-compare-part-foot">
                    <span className="cv-badge blue">{evidenceLabel(source)}</span>
                    <span className="cv-small-note">
                      {sourceRows.length ? `${sourceRows.length} source reference${sourceRows.length === 1 ? "" : "s"}` : "No primary source cited"}
                    </span>
                  </div>
                </section>
              );
            })}
          </div>

          <section className="cv-card pad cv-compare-spec-card">
            <div className="cv-compare-section-heading">
              <div>
                <div className="cv-eyebrow">Specification comparison</div>
                <h2 className="cv-card-title">Differences that affect fit</h2>
                <p className="cv-card-subtitle">
                  Each listed attribute is labeled as a match or review item. Missing source data stays unknown; it does not establish drop-in compatibility.
                </p>
              </div>
              <div className="cv-compare-counts" aria-label="Comparison attribute counts">
                <span><strong>{text(evidenceCounts.compatible, "0")}</strong> attributes align</span>
                <span><strong>{text(evidenceCounts.material_difference, "0")}</strong> differences</span>
                <span><strong>{text(evidenceCounts.needs_data, String(unknownRows.length))}</strong> unknown</span>
              </div>
            </div>
            {knownRows.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 14 }}>
                <table className="cv-table cv-compare-table">
                  <thead><tr><th>Property</th><th>Current part</th><th>Candidate</th><th>Assessment</th><th>Evidence / review note</th></tr></thead>
                  <tbody>
                    {knownRows.map((row, index) => (
                      <tr key={`${String(row.Attribute || "attr")}-${index}`}>
                        <td><strong>{text(row.Attribute || row.attribute)}</strong></td>
                        <td>{text(row["Part A"] || row.part_a)}</td>
                        <td>{text(row["Part B"] || row.part_b)}</td>
                        <td>{text(row.Assessment || row.assessment || row.Status)}</td>
                        <td>{text(row.Evidence || row.evidence || row.Note, "No source note supplied.")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState
                icon="compare"
                title="No source-backed attributes to compare"
                body="This result cannot determine whether the candidate fits. Add manufacturer or datasheet evidence before using it to make a substitution decision."
              />
            )}
            {unknownRows.length ? (
              <details className="cv-compare-unknown">
                <summary>Unverified attributes ({unknownRows.length})</summary>
                <div className="cv-table-wrap" style={{ marginTop: 10 }}>
                  <table className="cv-table cv-compare-table">
                    <thead><tr><th>Property</th><th>Current part</th><th>Candidate</th><th>Why it remains open</th></tr></thead>
                    <tbody>
                      {unknownRows.map((row, index) => (
                        <tr key={`unknown-${index}`}>
                          <td><strong>{text(row.Attribute || row.attribute)}</strong></td>
                          <td>{text(row["Part A"] || row.part_a, "Not confirmed")}</td>
                          <td>{text(row["Part B"] || row.part_b, "Not confirmed")}</td>
                          <td>{text(row.Evidence || row.evidence || row.Note, "Primary source evidence is missing.")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            ) : null}
          </section>

          <section className="cv-card pad cv-compare-evidence-card">
            <div>
              <div className="cv-eyebrow">Evidence</div>
              <h2 className="cv-card-title">Source records</h2>
              <p className="cv-card-subtitle">Review the source basis before documenting a component decision.</p>
            </div>
            <div className="cv-compare-evidence-grid">
              {([
                ["Part A", result.source_a, evidenceSources.part_a],
                ["Part B", result.source_b, evidenceSources.part_b],
              ] as Array<[string, unknown, unknown[] | undefined]>).map(([name, source, sourceRows]) => (
                <div className="cv-compare-evidence-item" key={name}>
                  <span className="cv-compare-part-label">{name} · {evidenceLabel(source)}</span>
                  {sourceRows?.length ? (
                    <ul>
                      {sourceRows.map((item, index) => {
                        const row = (item || {}) as Row;
                        const href = String(row.url || row.source_url || "");
                        return (
                          <li key={`${href}-${index}`}>
                            {href ? <a href={href} target="_blank" rel="noreferrer">{text(row.label || row.name || href)}</a> : text(row.label || row.name || row.source)}
                            {row.retrieved_at ? <small> · retrieved {reportDate(row.retrieved_at)}</small> : null}
                          </li>
                        );
                      })}
                    </ul>
                  ) : (
                    <p>No manufacturer datasheet or live supplier source was retrieved.</p>
                  )}
                </div>
              ))}
            </div>
          </section>
        </>
      ) : !busy && !error ? (
        <section className="cv-compare-empty">
          <div>
            <div className="cv-eyebrow">Side-by-side comparison</div>
            <h2>Start with two manufacturer part numbers</h2>
            <p>Cadivor will show the attributes it can support and make missing evidence visible. It will not turn unknown values into a match.</p>
          </div>
          <Link href="/find-replacement" className="cv-button secondary">Find a replacement</Link>
        </section>
      ) : null}

      {decisionOpen ? (
        <div
          className="cv-modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !decisionBusy) setDecisionOpen(false);
          }}
        >
          <section
            className="cv-modal-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="decision-dialog-title"
            ref={dialogRef}
          >
            <div className="cv-modal-heading">
              <div>
                <div className="cv-eyebrow">Engineering decision record</div>
                <h2 id="decision-dialog-title">Record an engineering decision</h2>
                <p>Save your reviewer choice and the comparison snapshot to this workspace.</p>
              </div>
              <span className="cv-badge blue">Human review</span>
            </div>

            <form onSubmit={onRecordDecision}>
              {reportOptions.length ? (
                <>
                  <label className="cv-field cv-modal-project">
                    <span>Project / BOM</span>
                    <select
                      value={decisionAnalysisId}
                      onChange={(event) => void changeDecisionAnalysis(event.target.value)}
                      disabled={decisionBusy}
                    >
                      {reportOptions.map((row) => (
                        <option key={getAnalysisId(row)} value={getAnalysisId(row)}>{reportLabel(row)}</option>
                      ))}
                    </select>
                  </label>
                  <div className="cv-modal-component-pair">
                    <label className="cv-field">
                      <span>Current part</span>
                      <input
                        value={decisionPartA}
                        onChange={(event) => setDecisionPartA(event.target.value)}
                        maxLength={160}
                        placeholder="Current manufacturer part number"
                        autoComplete="off"
                        required
                      />
                    </label>
                    <label className="cv-field">
                      <span>Candidate part</span>
                      <input
                        value={decisionPartB}
                        onChange={(event) => setDecisionPartB(event.target.value)}
                        maxLength={160}
                        placeholder="Candidate manufacturer part number"
                        autoComplete="off"
                        required
                      />
                    </label>
                  </div>
                </>
              ) : (
                <>
                  <div className="cv-modal-context">
                    <strong>Workspace-level decision</strong>
                    <span>Not linked to a saved BOM. The comparison will be captured with the decision.</span>
                  </div>
                  <div className="cv-modal-component-pair">
                    <label className="cv-field">
                      <span>Current part</span>
                      <input
                        value={decisionPartA}
                        onChange={(event) => setDecisionPartA(event.target.value)}
                        maxLength={160}
                        placeholder="Current manufacturer part number"
                        autoComplete="off"
                        required
                      />
                    </label>
                    <label className="cv-field">
                      <span>Candidate part</span>
                      <input
                        value={decisionPartB}
                        onChange={(event) => setDecisionPartB(event.target.value)}
                        maxLength={160}
                        placeholder="Candidate manufacturer part number"
                        autoComplete="off"
                        required
                      />
                    </label>
                  </div>
                </>
              )}

              <div className="cv-form-grid cv-form-grid-two cv-modal-grid">
                <label className="cv-field">
                  <span>Decision</span>
                  <select
                    value={decision}
                    onChange={(event) => {
                      setDecision(event.target.value);
                      setVerifiedPrimaryEvidence(false);
                    }}
                    disabled={decisionBusy}
                  >
                    <option value="hold_for_review">Hold for review</option>
                    <option value="approve_alternate">Approve alternate</option>
                    <option value="retain_current_part">Retain current part</option>
                  </select>
                </label>
                <label className="cv-field">
                  <span>Reviewer</span>
                  <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} maxLength={120} required />
                </label>
              </div>

              <label className="cv-field cv-modal-rationale">
                <span>Rationale</span>
                <textarea
                  value={rationale}
                  onChange={(event) => setRationale(event.target.value)}
                  placeholder="Document what was reviewed, why this decision was selected, and any follow-up required."
                  maxLength={3000}
                  required
                  rows={4}
                />
              </label>

              {decision === "approve_alternate" ? (
                <label className="cv-modal-confirm">
                  <input
                    type="checkbox"
                    checked={verifiedPrimaryEvidence}
                    onChange={(event) => setVerifiedPrimaryEvidence(event.target.checked)}
                  />
                  <span>I reviewed the candidate manufacturer&apos;s datasheet and verified package/footprint requirements.</span>
                </label>
              ) : null}

              <div className="cv-decision-evidence-note">
                This comparison currently uses synthetic or offline evidence. The record captures your human decision; it does not qualify a drop-in replacement or change the BOM.
              </div>
              {decisionError ? <div className="cv-error" role="alert">{decisionError}</div> : null}

              <div className="cv-modal-actions">
                <button type="button" className="cv-button" onClick={() => setDecisionOpen(false)} disabled={decisionBusy}>Cancel</button>
                <button
                  type="submit"
                  className="cv-button primary"
                  disabled={decisionBusy || !decisionPartA.trim() || !decisionPartB.trim() || !reviewer.trim() || !rationale.trim() || (decision === "approve_alternate" && !verifiedPrimaryEvidence)}
                >
                  {decisionBusy ? "Saving comparison and decision…" : "Record decision"}
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}
    </Shell>
  );
}

export default function ComparePartsPage() {
  return (
    <Suspense fallback={null}>
      <ComparePartsInner />
    </Suspense>
  );
}

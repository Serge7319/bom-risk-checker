"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchDecisionApproval, getDecisionCandidates, respondToDecisionApproval, type DecisionRecord } from "@/lib/api";
import { cleanUserText } from "@/lib/display";

export default function DecisionApprovalPage() {
  const params = useParams<{ token: string }>();
  const token = String(params?.token || "");
  const [record, setRecord] = useState<Partial<DecisionRecord> | null>(null);
  const [status, setStatus] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const alternatives = getDecisionCandidates(record);

  useEffect(() => {
    let cancelled = false;
    fetchDecisionApproval(token)
      .then((payload) => {
        if (cancelled) return;
        setRecord(payload.record);
        setStatus(payload.status || "pending");
        setExpiresAt(payload.expires_at || "");
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "This approval link is unavailable.");
      });
    return () => { cancelled = true; };
  }, [token]);

  async function respond(decision: "approved" | "rejected") {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await respondToDecisionApproval(token, decision, rationale);
      setStatus(result.status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save your response.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="cv-decision-share-page">
      <header className="cv-stress-site-header">
        <a className="cv-stress-brand" href="https://www.cadivor.com/" aria-label="Cadivor home">
          <span className="cv-stress-brand-mark" aria-hidden>C</span>
          <span><span className="cv-stress-brand-name">Cadivor</span><span className="cv-stress-brand-line">Engineering Decision Intelligence</span></span>
        </a>
        <span className="cv-stress-header-note">Decision approval</span>
      </header>
      <section className="cv-decision-share-card">
        {error && !record ? <div className="cv-error" role="alert">{error}</div> : null}
        {!record && !error ? <p role="status">Loading decision for review…</p> : null}
        {record ? (
          <>
            <p className="cv-kicker">SINGLE RECORD · APPROVER ACCESS</p>
            <h1>Review engineering decision</h1>
            <p className="cv-decision-share-context">
              {record.project_name || "Workspace decision"}{record.bom_name ? ` · ${record.bom_name}` : ""}
              {record.revision ? ` · revision ${record.revision}` : ""}
            </p>
            <dl className="cv-decision-share-grid">
              <div><dt>Decision</dt><dd>{cleanUserText(record.decision_label || record.decision || "—")}</dd></div>
              <div><dt>Reviewer</dt><dd>{cleanUserText(record.reviewer || "—")}</dd></div>
              <div><dt>Current part</dt><dd>{cleanUserText(record.part_a || "—")}{record.manufacturer_a ? ` · ${cleanUserText(record.manufacturer_a)}` : ""}</dd></div>
              <div><dt>Replacement alternatives</dt><dd>{cleanUserText(alternatives.map((candidate) => candidate.manufacturer ? `${candidate.mpn} · ${candidate.manufacturer}` : candidate.mpn).join("; ") || "—")}</dd></div>
              <div><dt>Residual risk</dt><dd>{cleanUserText(record.residual_risk || "Not assessed")}</dd></div>
              <div><dt>Review status</dt><dd>{cleanUserText(status.replaceAll("_", " "))}</dd></div>
            </dl>
            <section className="cv-decision-share-section"><h2>Rationale</h2><p>{cleanUserText(record.rationale || "No rationale was included.")}</p></section>
            {record.validation_checks?.length ? (
              <section className="cv-decision-share-section"><h2>Review checks</h2><ul>{record.validation_checks.map((item) => <li key={item}>{cleanUserText(item.replaceAll("_", " "))}</li>)}</ul></section>
            ) : null}
            {record.follow_up_action ? <section className="cv-decision-share-section"><h2>Follow-up</h2><p>{cleanUserText(record.follow_up_action)}</p></section> : null}
            {expiresAt ? <p className="cv-small-note">This invitation expires {new Date(expiresAt).toLocaleString()}.</p> : null}
            {error ? <div className="cv-error" role="alert">{error}</div> : null}
            {status === "pending" ? (
              <section className="cv-decision-share-section">
                <h2>Your response</h2>
                <label className="cv-field" htmlFor="approval-rationale">Notes for the decision owner (optional)</label>
                <textarea id="approval-rationale" value={rationale} maxLength={3000} onChange={(event) => setRationale(event.target.value)} rows={4} />
                <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                  <button className="cv-button primary" type="button" disabled={busy} onClick={() => void respond("approved")}>{busy ? "Saving…" : "Approve"}</button>
                  <button className="cv-button" type="button" disabled={busy} onClick={() => void respond("rejected")}>{busy ? "Saving…" : "Reject"}</button>
                </div>
              </section>
            ) : (
              <p className="cv-evidence-context" role="status">Your response has been recorded as {status.replaceAll("_", " ")}.</p>
            )}
            <p className="cv-decision-share-caution">This access is limited to the selected decision record. It does not grant workspace membership or access to BOM reports.</p>
          </>
        ) : null}
      </section>
    </main>
  );
}

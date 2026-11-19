"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchSharedDecisionRecord, type DecisionRecord } from "@/lib/api";

export default function SharedDecisionRecordPage() {
  const params = useParams<{ token: string }>();
  const token = String(params?.token || "");
  const [record, setRecord] = useState<Partial<DecisionRecord> | null>(null);
  const [expiresAt, setExpiresAt] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchSharedDecisionRecord(token)
      .then((payload) => {
        if (cancelled) return;
        setRecord(payload.record);
        setExpiresAt(payload.expires_at || "");
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "This share link is unavailable.");
      });
    return () => { cancelled = true; };
  }, [token]);

  const snapshot = (record?.comparison_snapshot || {}) as Record<string, unknown>;

  return (
    <main className="cv-decision-share-page">
      <header className="cv-stress-site-header">
        <a className="cv-stress-brand" href="https://www.cadivor.com/" aria-label="Cadivor home">
          <span className="cv-stress-brand-mark" aria-hidden>C</span>
          <span><span className="cv-stress-brand-name">Cadivor</span><span className="cv-stress-brand-line">Engineering Decision Intelligence</span></span>
        </a>
        <span className="cv-stress-header-note">Shared decision · read only</span>
      </header>
      <section className="cv-decision-share-card">
        {error ? (
          <div className="cv-error" role="alert">{error}</div>
        ) : !record ? (
          <p role="status">Loading shared decision…</p>
        ) : (
          <>
            <p className="cv-kicker">READ ONLY · BEARER LINK</p>
            <h1>Engineering decision record</h1>
            <p className="cv-decision-share-context">
              {record.project_name || "Workspace decision"}
              {record.bom_name ? " · " + record.bom_name : ""}
              {record.revision ? " · revision " + record.revision : ""}
            </p>
            <dl className="cv-decision-share-grid">
              <div><dt>Decision</dt><dd>{record.decision_label || record.decision || "—"}</dd></div>
              <div><dt>Reviewer</dt><dd>{record.reviewer || "—"}</dd></div>
              <div><dt>Parts reviewed</dt><dd>{record.part_a || "—"} → {record.part_b || "—"}</dd></div>
              <div><dt>Manufacturers</dt><dd>{[record.manufacturer_a, record.manufacturer_b].filter(Boolean).join(" → ") || "Not recorded"}</dd></div>
              <div><dt>Residual risk</dt><dd>{record.residual_risk || "Not assessed"}</dd></div>
              <div><dt>Evidence status</dt><dd>{String(snapshot.engineering_evidence_status || (record.verified_primary_evidence ? "verified" : "unverified"))}</dd></div>
            </dl>
            <section className="cv-decision-share-section">
              <h2>Rationale</h2>
              <p>{record.rationale || "No rationale was included."}</p>
            </section>
            {record.validation_checks?.length ? (
              <section className="cv-decision-share-section">
                <h2>Review checks</h2>
                <ul>{record.validation_checks.map((check) => <li key={check}>{check.replaceAll("_", " ")}</li>)}</ul>
              </section>
            ) : null}
            {record.follow_up_action ? (
              <section className="cv-decision-share-section">
                <h2>Follow-up</h2>
                <p>{record.follow_up_action}{record.follow_up_owner ? " · " + record.follow_up_owner : ""}{record.follow_up_due_date ? " · due " + record.follow_up_due_date : ""}</p>
              </section>
            ) : null}
            {snapshot.finding ? <p className="cv-small-note">Comparison finding: {String(snapshot.finding)}</p> : null}
            {snapshot.source_a || snapshot.source_b ? <p className="cv-small-note">Evidence sources: {String(snapshot.source_a || "Not specified")} → {String(snapshot.source_b || "Not specified")}</p> : null}
            {record.qualification_note ? <p className="cv-small-note">{record.qualification_note}</p> : null}
            <p className="cv-small-note">Created {record.created_at ? new Date(record.created_at).toLocaleString() : "date unavailable"}. {expiresAt ? "This link expires " + new Date(expiresAt).toLocaleString() + "." : "This link expires after 7 days."}</p>
            <p className="cv-decision-share-caution">This is a read-only snapshot. It does not grant access to the workspace or report, and it does not constitute an approval beyond the reviewer’s saved decision.</p>
            <Link className="cv-button primary" href="https://www.cadivor.com/">Learn about Cadivor</Link>
          </>
        )}
      </section>
    </main>
  );
}

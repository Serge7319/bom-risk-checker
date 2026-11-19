"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  fetchPublicBomSharedSummary,
  type PublicBomSharedSummary,
} from "@/lib/publicBomStress";

export default function SharedAuditSummaryPage() {
  const params = useParams<{ token: string }>();
  const token = String(params?.token || "");
  const [summary, setSummary] = useState<PublicBomSharedSummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchPublicBomSharedSummary(token)
      .then((payload) => {
        if (!cancelled) setSummary(payload);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "This link is unavailable.");
      });
    return () => { cancelled = true; };
  }, [token]);

  return (
    <main className="cv-audit-share-page">
      <header className="cv-stress-site-header">
        <a className="cv-stress-brand" href="https://www.cadivor.com/" aria-label="Cadivor home">
          <span className="cv-stress-brand-mark" aria-hidden>C</span>
          <span><span className="cv-stress-brand-name">Cadivor</span><span className="cv-stress-brand-line">Engineering Decision Intelligence</span></span>
        </a>
        <span className="cv-stress-header-note">Shared audit summary</span>
      </header>
      <section className="cv-public-stress-panel cv-audit-share-panel">
        {error ? (
          <div className="cv-error" role="alert">{error}</div>
        ) : !summary ? (
          <p className="cv-small-note" role="status">Loading shared summary…</p>
        ) : (
          <>
            <p className="cv-kicker">READ-ONLY · PRELIMINARY</p>
            <h1>Free BOM audit summary</h1>
            <p className="cv-small-note">
              {summary.component_count} components in the uploaded BOM · {summary.checked_components} components checked in the free preview
            </p>
            <div className="cv-public-audit-metrics" aria-label="Checked findings">
              <div><strong>{summary.checked_summary.blockers}</strong><span>Blockers</span></div>
              <div><strong>{summary.checked_summary.lifecycle_alerts}</strong><span>Lifecycle alerts</span></div>
              <div><strong>{summary.checked_summary.single_source_parts}</strong><span>Single-source parts</span></div>
              <p>{summary.scope_note}</p>
            </div>
            {summary.created_at ? (
              <p className="cv-small-note">Audit created {new Date(summary.created_at).toLocaleString()}</p>
            ) : null}
            <p className="cv-small-note">
              The share contains aggregate counts only. It does not include part numbers, supplier records, or the original BOM.
            </p>
            <Link className="cv-button primary" href="/public-bom-audit">Run a free BOM audit</Link>
          </>
        )}
      </section>
    </main>
  );
}

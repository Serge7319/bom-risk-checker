"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AnalysisStageNavigation } from "@/components/AnalysisStageNavigation";
import { Shell } from "@/components/Shell";
import { LoadingCard } from "@/components/GapBanner";
import { PartThumbnail } from "@/components/PartThumbnail";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import { fetchReport, type Report } from "@/lib/api";
import { markReviewProgress, readReviewProgress } from "@/lib/bomDraft";
import { evidenceSourceLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

function EvidenceReviewPageInner() {
  const session = useRequireSession();
  const searchParams = useSearchParams();
  const analysisId = (searchParams.get("analysis_id") || "").trim();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [reviewed, setReviewed] = useState(false);

  useEffect(() => {
    if (!session) return;
    let active = true;
    setReport(null);
    setBusy(true);
    setError("");
    setReviewed(false);
    if (!analysisId) {
      setError("Choose a saved analysis to review its evidence.");
      setBusy(false);
      return () => {
        active = false;
      };
    }

    setReviewed(Boolean(readReviewProgress(analysisId, session).evidenceReviewedAt));
    fetchReport(analysisId, session.access_token)
      .then((payload) => {
        if (active) setReport(payload);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Evidence could not load.");
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [analysisId, session]);

  if (!session) return null;

  const markReviewed = () => {
    markReviewProgress(
      analysisId,
      { evidenceReviewedAt: new Date().toISOString() },
      session,
    );
    setReviewed(true);
  };

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.evidence}
        record
        actions={
          report ? (
            <SecondaryLink href={`/reports/${encodeURIComponent(analysisId)}`}>
              Saved report
            </SecondaryLink>
          ) : undefined
        }
      />

      <AnalysisStageNavigation analysisId={analysisId} current="evidence" />

      {report ? (
        <p className="cv-evidence-context" role="note">
          Evidence for <strong>{report.bom_name || report.filename || analysisId}</strong>. Source labels describe what was recorded with the analysis; missing fields remain unverified.
        </p>
      ) : null}
      {busy ? <LoadingCard label="Loading component evidence…" /> : null}
      {error ? (
        <div className="cv-error" role="alert">
          Evidence could not load. {error} <Link href="/reports">Choose a saved analysis</Link>.
        </div>
      ) : null}

      {!busy && report ? (
        <section className="cv-card pad" aria-labelledby="evidence-review-title">
          <div className="cv-section-heading cv-section-heading--card">
            <div>
              <h2 id="evidence-review-title">Component evidence</h2>
              <p>Review the recorded source and verification status for each BOM line.</p>
            </div>
            {reviewed ? (
              <span className="cv-badge green">Reviewed</span>
            ) : (
              <button type="button" className="cv-button primary" onClick={markReviewed}>
                Mark evidence reviewed
              </button>
            )}
          </div>
          <div className="cv-table-wrap">
            <table className="cv-table">
              <thead>
                <tr>
                  <th>Part</th>
                  <th>Manufacturer</th>
                  <th>Lifecycle</th>
                  <th>Risk</th>
                  <th>Evidence source</th>
                  <th>Supplier verification</th>
                </tr>
              </thead>
              <tbody>
                {report.parts.map((part, index) => {
                  const mpn = String(part.MPN || part.mpn || part.manufacturer_part_number || "—");
                  const rawSource = part.evidence_source ?? part["Evidence Source"] ?? part.source ?? part.source_type;
                  const sourceFallback = /synthetic|preview/i.test(report.mode)
                    ? "Synthetic analysis"
                    : "Not recorded";
                  const verified = part.supplier_data_verified === true || part["Supplier Data Verified"] === true;
                  return (
                    <tr key={`${mpn}-${index}`}>
                      <td>
                        <div className="cv-part-cell">
                          <PartThumbnail part={part} />
                          <strong>{mpn}</strong>
                        </div>
                      </td>
                      <td>{String(part.Manufacturer || part.manufacturer || "Not recorded")}</td>
                      <td>{String(part.Lifecycle || part.lifecycle || "Not recorded")}</td>
                      <td>{String(part["Risk Level"] || part.risk_level || "Not recorded")}</td>
                      <td>{evidenceSourceLabel(rawSource, sourceFallback)}</td>
                      <td>
                        <span className={`cv-badge ${verified ? "green" : "amber"}`}>
                          {verified ? "Verified supplier data" : "Not verified"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </Shell>
  );
}

export default function EvidenceReviewPage() {
  return (
    <Suspense fallback={null}>
      <EvidenceReviewPageInner />
    </Suspense>
  );
}

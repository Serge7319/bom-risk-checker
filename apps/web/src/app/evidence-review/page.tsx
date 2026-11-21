"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AnalysisStageNavigation } from "@/components/AnalysisStageNavigation";
import { Shell } from "@/components/Shell";
import { LoadingCard } from "@/components/GapBanner";
import { PartThumbnail } from "@/components/PartThumbnail";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { fetchReport, type Report } from "@/lib/api";
import { markReviewProgress, readReviewProgress } from "@/lib/bomDraft";
import { cleanKiCadFieldText, evidenceSourceLabel, userFacingLabel } from "@/lib/display";
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

  const verifiedParts = report?.parts.filter((part) =>
    part.supplier_data_verified === true || part["Supplier Data Verified"] === true,
  ).length || 0;
  const totalParts = report?.parts.length || 0;
  const unverifiedParts = totalParts - verifiedParts;
  const legacyKiCadMetadataCount = report?.parts.filter((part) =>
    [part.MPN, part.mpn, part.Manufacturer, part.manufacturer].some((value) =>
      /BoardText\(value=[\s\S]*?Vector2\(/.test(String(value || "")),
    ),
  ).length || 0;
  const verificationTone = totalParts === 0
    ? "blue"
    : verifiedParts === totalParts ? "green" : verifiedParts > 0 ? "amber" : "blue";
  const verificationStatus = totalParts === 0
    ? { label: "No parts", tone: "gray" as const }
    : verifiedParts === totalParts
      ? { label: "All matched", tone: "green" as const }
      : verifiedParts > 0
        ? { label: "Partially verified", tone: "amber" as const }
        : { label: "No matches", tone: "gray" as const };

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
          Evidence for <strong>{userFacingLabel(report.bom_name || report.filename, "Saved analysis")}</strong>. Source labels describe what was recorded with the analysis; missing fields remain unverified.
        </p>
      ) : null}
      {report && legacyKiCadMetadataCount > 0 ? (
        <div className="cv-notice" role="alert" style={{ marginBottom: 14, borderColor: "#f0bb72", background: "#fffaf1", color: "#805000" }}>
          <strong>{legacyKiCadMetadataCount} row(s) came from an older KiCad plugin format.</strong>
          {" "}Visible part text is shown here, but supplier checks in this saved report used the malformed field values. Open the saved report and create a new revision to verify the part numbers and rerun the checks.
          {" "}<Link href={"/reports/" + encodeURIComponent(analysisId)}>Review this report</Link>.
        </div>
      ) : null}
      {busy ? <LoadingCard label="Loading component evidence…" /> : null}
      {error ? (
        <div className="cv-error" role="alert">
          Evidence could not load. {error} <Link href="/reports">Choose a saved analysis</Link>.
        </div>
      ) : null}

      {!busy && report ? (
        <>
          <div className="cv-kpis" aria-label="Evidence summary">
            <KpiCard icon="box" tone="blue" label="Components assessed" value={totalParts} status={{ label: "In this report", tone: totalParts > 0 ? "blue" : "gray" }} detail="Parts available for review" />
            <KpiCard icon="check" tone={verificationTone} label="Verified supplier data" value={verifiedParts} status={verificationStatus} detail="Exact supplier matches recorded" />
            <KpiCard icon="shield" tone={unverifiedParts > 0 ? "amber" : "green"} label="Needs verification" value={unverifiedParts} status={unverifiedParts > 0 ? { label: "Review needed", tone: "amber" } : { label: "All verified", tone: "green" }} detail="Supplier records to review" />
          </div>
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
                    const mpn = cleanKiCadFieldText(part.MPN || part.mpn || part.manufacturer_part_number || "—");
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
                        <td>{cleanKiCadFieldText(part.Manufacturer || part.manufacturer || "Not recorded")}</td>
                        <td><StatusPill kind="lifecycle" value={part.Lifecycle || part.lifecycle || "Unknown"} /></td>
                        <td><StatusPill kind="risk" value={part["Risk Level"] || part.risk_level || "Unknown"} /></td>
                        <td><span className="cv-source-label">{evidenceSourceLabel(rawSource, sourceFallback)}</span></td>
                        <td><StatusPill kind="verification" value={verified ? "Verified" : "Not verified"} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
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

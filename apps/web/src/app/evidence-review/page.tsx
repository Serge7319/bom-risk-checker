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

type EvidenceField = { evidence_class?: string; source?: string };
type PartEvidence = {
  identity_verified?: boolean;
  evidence_class?: string;
  source?: string;
  fields?: Record<string, EvidenceField | undefined>;
};

function partEvidence(part: Record<string, unknown>): PartEvidence {
  const value = part.evidence;
  return value && typeof value === "object" ? value as PartEvidence : {};
}

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

  const totalParts = report?.parts.length || 0;
  const evidenceByPart = report?.parts.map(partEvidence) || [];
  const verifiedParts = evidenceByPart.filter((evidence) => evidence.identity_verified === true).length;
  const unverifiedSupplierParts = evidenceByPart.filter((evidence) => evidence.evidence_class === "unverified").length;
  const noSupplierMatchParts = evidenceByPart.filter((evidence) => evidence.evidence_class === "missing").length;
  const unresolvedParts = totalParts - verifiedParts;
  const legacyKiCadMetadataCount = report?.parts.filter((part) =>
    [part.MPN, part.mpn, part.Manufacturer, part.manufacturer].some((value) =>
      /BoardText\(value=[\s\S]*?Vector2\(/.test(String(value || "")),
    ),
  ).length || 0;
  const verificationTone = totalParts === 0
    ? "blue"
    : unresolvedParts === 0 ? "green" : verifiedParts > 0 ? "amber" : "blue";
  const verificationStatus = totalParts === 0
    ? { label: "No parts", tone: "gray" as const }
    : unresolvedParts === 0
      ? { label: "All identities verified", tone: "green" as const }
      : { label: `${verifiedParts} verified`, tone: "amber" as const };
  const unresolvedStatus = noSupplierMatchParts > 0 && unverifiedSupplierParts > 0
    ? `${unverifiedSupplierParts} unverified · ${noSupplierMatchParts} no match`
    : noSupplierMatchParts > 0
      ? `${noSupplierMatchParts} no exact supplier match`
      : unverifiedSupplierParts > 0
        ? `${unverifiedSupplierParts} need verification`
        : unresolvedParts > 0 ? "Supplier evidence is not verified" : "All identities verified";

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
          Evidence for <strong>{userFacingLabel(report.bom_name || report.filename, "Saved analysis")}</strong>. An exact match confirms part identity only; price, stock, lifecycle, and compliance are checked separately. Missing fields remain unverified.
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
            <KpiCard icon="check" tone={verificationTone} label="Verified identities" value={verifiedParts} status={verificationStatus} detail="Exact MPN and manufacturer identity" />
            <KpiCard icon="shield" tone={unresolvedParts > 0 ? "amber" : "green"} label="Needs verification" value={unresolvedParts} status={unresolvedParts > 0 ? { label: unresolvedStatus, tone: "amber" } : { label: "All identities verified", tone: "green" }} detail="Unverified supplier results or no exact match" />
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
                    <th>Part identity match</th>
                  </tr>
                </thead>
                <tbody>
                  {report.parts.map((part, index) => {
                    const mpn = cleanKiCadFieldText(part.MPN || part.mpn || part.manufacturer_part_number || "—");
                    const evidence = partEvidence(part);
                    const evidenceClass = evidence.evidence_class || "unverified";
                    const identityVerified = evidence.identity_verified === true;
                    const lifecycleEvidence = evidence.fields?.lifecycle;
                    const lifecycleRaw = part.Lifecycle || part.lifecycle || "Unknown";
                    const lifecycleHasValue = !/^(unknown|not reported|—|-)$/.test(String(lifecycleRaw).trim().toLowerCase());
                    const lifecycleVerification = lifecycleEvidence?.evidence_class === "live-authorized-supplier"
                      ? "Verified"
                      : lifecycleEvidence?.evidence_class === "synthetic-preview"
                        ? "Preview"
                        : lifecycleEvidence?.evidence_class === "missing" || !lifecycleHasValue
                          ? "Not reported"
                          : "Unverified";
                    const sourceLabel = evidenceClass === "live-authorized-supplier"
                      ? "Authorized supplier"
                      : evidenceClass === "unverified"
                        ? "Supplier result · needs verification"
                        : evidenceClass === "synthetic-preview"
                          ? "Synthetic preview"
                          : evidenceClass === "missing"
                            ? "No exact supplier match"
                            : evidenceSourceLabel(evidence.source ?? part.evidence_source ?? part["Evidence Source"] ?? part.source ?? part.source_type, "Not recorded");
                    const identityLabel = identityVerified
                      ? "Exact match"
                      : evidenceClass === "missing"
                        ? "No supplier match"
                        : evidenceClass === "synthetic-preview"
                          ? "Synthetic preview"
                          : "Needs verification";
                    return (                    return (
                      <tr key={`${mpn}-${index}`}>
                        <td>
                          <div className="cv-part-cell">
                            <PartThumbnail part={part} />
                            <strong>{mpn}</strong>
                          </div>
                        </td>
                        <td>{cleanKiCadFieldText(part.Manufacturer || part.manufacturer || "Not recorded")}</td>
                        <td>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                            <StatusPill kind="lifecycle" value={lifecycleRaw} />
                            <StatusPill kind="verification" value={lifecycleVerification} />
                          </div>
                        </td>
                        <td><StatusPill kind="risk" value={part["Risk Level"] || part.risk_level || "Unknown"} /></td>
                        <td><span className="cv-source-label">{sourceLabel}</span></td>
                        <td><StatusPill kind="verification" value={identityLabel} /></td>
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

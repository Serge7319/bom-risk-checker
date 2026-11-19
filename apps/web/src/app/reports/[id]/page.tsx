"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { useParams, useRouter } from "next/navigation";
import { AskCadivorPanel } from "@/components/AskCadivorPanel";
import { AnalysisStageNavigation } from "@/components/AnalysisStageNavigation";
import { Shell } from "@/components/Shell";
import { KpiCard } from "@/components/KpiCard";
import { Icon } from "@/components/Icons";
import { PartThumbnail } from "@/components/PartThumbnail";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import { getReportRiskCounts, ReportOverview } from "@/components/ReportOverview";
import {
  analyzeBom,
  downloadCompliancePack,
  downloadReportExport,
  fetchReport,
  listProjects,
  listReports,
  listDecisionRecords,
  validateBom,
  type DecisionRecord,
  type Report,
  type ReportExportFormat,
  type CompliancePackType,
} from "@/lib/api";
import {
  markReviewProgress,
  readReviewProgress,
  type BomReviewProgress,
} from "@/lib/bomDraft";
import { analysisModeLabel, cleanUserText, evidenceSourceLabel, userFacingLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { rememberAnalysis, useRequireSession } from "@/lib/session";
import { trackMarketingEventOnce } from "@/lib/marketingAnalytics";

type EditableBomRow = {
  mpn: string;
  manufacturer: string;
  description: string;
  parentMpn: string;
  lineType: string;
  quantity: string;
};

function editableRows(parts: Array<Record<string, unknown>>): EditableBomRow[] {
  return parts.map((part) => ({
    mpn: String(part.MPN || part.mpn || ""),
    manufacturer: String(part.Manufacturer || part.manufacturer || ""),
    description: String(part.Description || part.description || ""),
    parentMpn: String(part["Parent MPN"] || part.parent_mpn || ""),
    lineType: String(part["Line Type"] || part.line_type || ""),
    quantity: String(
      part.quantity_per_parent ?? part["Quantity per Parent"] ?? part.Quantity ?? part.quantity ?? "1",
    ),
  }));
}

function csvCell(value: string): string {
  return `"${value.replaceAll('"', '""')}"`;
}

function revisionCandidate(current: string, used: Set<string>): string {
  const base = current.trim() || "A";
  if (/^[A-Z]$/i.test(base)) {
    for (let code = base.toUpperCase().charCodeAt(0) + 1; code <= "Z".charCodeAt(0); code += 1) {
      const candidate = String.fromCharCode(code);
      if (!used.has(candidate.toLowerCase())) return candidate;
    }
  }
  if (/^\d+$/.test(base)) {
    let number = Number(base) + 1;
    while (used.has(String(number).toLowerCase())) number += 1;
    return String(number);
  }
  let suffix = 2;
  let candidate = `${base}-next`;
  while (used.has(candidate.toLowerCase())) {
    candidate = `${base}-next-${suffix}`;
    suffix += 1;
  }
  return candidate;
}

function riskBadge(level: string) {
  const normalized = level.toLowerCase();
  if (normalized.includes("high")) return "red";
  if (normalized.includes("medium")) return "amber";
  if (normalized.includes("low")) return "green";
  return "gray";
}

export default function ReportPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const session = useRequireSession();
  const [report, setReport] = useState<Report | null>(null);
  const [decisions, setDecisions] = useState<DecisionRecord[]>([]);
  const [decisionError, setDecisionError] = useState("");
  const [error, setError] = useState("");
  const [exportError, setExportError] = useState("");
  const [exporting, setExporting] = useState<ReportExportFormat | null>(null);
  const [complianceExporting, setComplianceExporting] = useState<CompliancePackType | null>(null);
  const [complianceExportError, setComplianceExportError] = useState("");
  const [review, setReview] = useState<BomReviewProgress | null>(null);
  const [bomEditorOpen, setBomEditorOpen] = useState(false);
  const [bomEditorRows, setBomEditorRows] = useState<EditableBomRow[]>([]);
  const [projectNameDraft, setProjectNameDraft] = useState("");
  const [bomNameDraft, setBomNameDraft] = useState("");
  const [revisionDraft, setRevisionDraft] = useState("");
  const [appliedDecisionIds, setAppliedDecisionIds] = useState<string[]>([]);
  const [usedDecisionIds, setUsedDecisionIds] = useState<string[]>([]);
  const [revisionBusy, setRevisionBusy] = useState(false);
  const [revisionError, setRevisionError] = useState("");

  useEffect(() => {
    if (!session) return;
    const analysisKey = String(params.id || "");
    setReview(readReviewProgress(analysisKey, session));
    fetchReport(params.id, session.access_token)
      .then((data) => {
        setReport(data);
        const riskCounts = getReportRiskCounts(data);
        if (riskCounts.high > 0) {
          trackMarketingEventOnce(
            "first_blocker_viewed",
            `first_blocker_viewed:${String(data.analysis_id || data.id || analysisKey)}`,
            { flow: "saved-bom-analysis" },
            "/reports",
          );
        }
        const id = String(data.analysis_id || data.id || analysisKey);
        markReviewProgress(id, { risksOpenedAt: new Date().toISOString() }, session);
        rememberAnalysis({
          analysis_id: data.analysis_id || data.id,
          total_parts: data.total_parts,
          health_score: data.health_score,
          health_status: data.health_status,
          high_risk_count: data.high_risk_count,
          medium_risk_count: data.medium_risk_count,
          low_risk_count: data.low_risk_count,
          mode: data.mode,
          filename: data.filename,
        }, session);
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load report"),
      );
    listDecisionRecords(session.access_token, params.id)
      .then(({ records }) => {
        setDecisions(records || []);
      })
      .catch((err) => setDecisionError(err instanceof Error ? err.message : "Decision history could not load."));
  }, [params.id, session]);

  async function onDownload(format: ReportExportFormat) {
    if (!session || !report) return;
    setExporting(format);
    setExportError("");
    try {
      await downloadReportExport(
        String(report.analysis_id || report.id),
        session.access_token,
        format,
      );
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "The report could not be downloaded.");
    } finally {
      setExporting(null);
    }
  }

  async function onDownloadCompliance(packType: CompliancePackType) {
    if (!session || !report) return;
    setComplianceExporting(packType);
    setComplianceExportError("");
    try {
      await downloadCompliancePack(
        session.access_token,
        String(report.analysis_id || report.id),
        packType,
      );
    } catch (err) {
      setComplianceExportError(err instanceof Error ? err.message : "The evidence pack could not be downloaded.");
    } finally {
      setComplianceExporting(null);
    }
  }

  async function openBomEditor() {
    if (!session || !report) return;
    setRevisionError("");
    try {
      const [{ reports }, { projects }] = await Promise.all([
        listReports(session.access_token),
        listProjects(session.access_token),
      ]);
      const bomId = String(report.bom_id || "");
      const used = new Set(
        (reports || [])
          .filter((row) => String(row.bom_id || "") === bomId)
          .map((row) => String(row.revision || "").trim().toLowerCase())
          .filter(Boolean),
      );
      const projectName = projects.find(
        (project) => String(project.id || "") === String(report.project_id || ""),
      )?.name;
      setProjectNameDraft(userFacingLabel(projectName || String(report.project_name || "").split(" — ")[0], "General"));
      setBomNameDraft(userFacingLabel(report.bom_name || report.filename, "Saved BOM"));
      setRevisionDraft(revisionCandidate(String(report.revision || "A"), used));
      setBomEditorRows(editableRows(report.parts || []));
      setAppliedDecisionIds([]);
      setUsedDecisionIds([]);
      setBomEditorOpen(true);
    } catch (err) {
      setRevisionError(err instanceof Error ? err.message : "Saved BOM details could not be loaded.");
    }
  }

  function applyDecisionCandidate(decision: DecisionRecord) {
    const currentMpn = decision.part_a.trim().toLowerCase();
    const candidateMpn = decision.part_b.trim();
    if (!candidateMpn || candidateMpn.toLowerCase() === currentMpn) {
      setRevisionError("This decision does not contain a distinct replacement part number.");
      return;
    }
    if (!bomEditorRows.some((row) => row.mpn.trim().toLowerCase() === currentMpn)) {
      setRevisionError(`The current part ${decision.part_a} is not present in this saved BOM revision.`);
      return;
    }
    setBomEditorRows((current) => current.map((row) => row.mpn.trim().toLowerCase() !== currentMpn
      ? row
      : {
          ...row,
          mpn: candidateMpn,
          manufacturer: String(decision.manufacturer_b || row.manufacturer),
        }));
    setRevisionError("");
    const decisionsForPart = new Set(
      decisions
        .filter((item) => item.part_a.trim().toLowerCase() === currentMpn)
        .map((item) => item.id),
    );
    setAppliedDecisionIds((current) => {
      const next = current.filter((id) => !decisionsForPart.has(id));
      return decision.decision === "approve_alternate"
        ? [...next, decision.id]
        : next;
    });
    setUsedDecisionIds((current) => [
      ...current.filter((id) => !decisionsForPart.has(id)),
      decision.id,
    ]);
  }

  async function saveBomRevision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !report) return;
    const cleanRows = bomEditorRows.filter((row) => row.mpn.trim());
    if (!cleanRows.length) {
      setRevisionError("Keep at least one part with a manufacturer part number.");
      return;
    }
    if (!projectNameDraft.trim() || !bomNameDraft.trim() || !revisionDraft.trim()) {
      setRevisionError("Enter a new revision label before saving.");
      return;
    }
    setRevisionBusy(true);
    setRevisionError("");
    try {
      const header = ["MPN", "Manufacturer", "Description", "Parent MPN", "Line Type", "Quantity"];
      const lines = [
        header.map(csvCell).join(","),
        ...cleanRows.map((row) => [
          row.mpn,
          row.manufacturer,
          row.description,
          row.parentMpn,
          row.lineType,
          row.quantity,
        ].map(csvCell).join(",")),
      ];
      const filename = `${bomNameDraft.trim().replace(/[^a-z0-9-_]+/gi, "-")}-rev-${revisionDraft.trim()}.csv`;
      const file = new File([lines.join("\r\n")], filename, { type: "text/csv" });
      const preview = await validateBom(file, session.access_token);
      if (!preview.can_analyze) {
        throw new Error(preview.errors?.[0] || "The edited BOM did not pass validation.");
      }
      const created = await analyzeBom(file, session.access_token, {
        projectName: projectNameDraft.trim(),
        bomName: bomNameDraft.trim(),
        revision: revisionDraft.trim(),
        sourceAnalysisId: String(report.analysis_id || report.id),
        appliedDecisionIds,
        usedDecisionIds,
      });
      setBomEditorOpen(false);
      router.push(`/reports/${encodeURIComponent(created.analysis_id)}`);
    } catch (err) {
      setRevisionError(err instanceof Error ? err.message : "The new BOM revision could not be analyzed.");
    } finally {
      setRevisionBusy(false);
    }
  }

  if (!session) return null;

  const meta = {
    ...PAGE_META.ei,
    title: report?.filename && userFacingLabel(report.filename, "")
      ? `EI · ${userFacingLabel(report.filename, "Saved analysis")}`
      : PAGE_META.ei.title,
  };
  const evidenceSummary = (report?.evidence_summary || {}) as Record<string, unknown>;
  const verifiedSupplierRows = Number(
    evidenceSummary.live_count
      ?? (report?.parts || []).filter((part) => {
        const evidence = (part.evidence || {}) as Record<string, unknown>;
        return String(evidence.evidence_class || "") === "live-authorized-supplier";
      }).length,
  );
  const syntheticSupplierRows = Number(evidenceSummary.synthetic_count ?? 0);
  const missingSupplierRows = Number(evidenceSummary.missing_count ?? 0);
  const reportRiskCounts = report ? getReportRiskCounts(report) : null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={meta}
        record
        actions={
          <>
            <SecondaryLink href="/bom-analyzer">New analysis</SecondaryLink>
            <button
              type="button"
              className="cv-button secondary"
              onClick={() => void openBomEditor()}
              disabled={!report}
            >
              Edit BOM / new revision
            </button>
            <SecondaryLink href="/engineering-decisions">
              Decision queue
            </SecondaryLink>
            <SecondaryLink href={`/compare-parts?analysis_id=${encodeURIComponent(params.id)}`}>
              Compare parts
            </SecondaryLink>
          </>
        }
      />

      {error ? (
        <div className="cv-error" role="alert">
          This saved report could not be opened. {error} <Link href="/reports">Return to saved reports</Link>
        </div>
      ) : null}

      <AnalysisStageNavigation
        analysisId={String(report?.analysis_id || report?.id || params.id)}
        current="risks"
      />

      {bomEditorOpen ? (
        <div
          className="cv-modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !revisionBusy) setBomEditorOpen(false);
          }}
        >
          <section className="cv-modal-card" role="dialog" aria-modal="true" aria-labelledby="bom-editor-title" style={{ width: "min(1100px, 100%)" }}>
            <div className="cv-modal-heading">
              <div>
                <div className="cv-eyebrow">BOM revision editor</div>
                <h2 id="bom-editor-title">Edit BOM and create a new revision</h2>
                <p>The current saved report stays unchanged. Cadivor validates and re-analyzes the edited part list as a new revision on this saved BOM.</p>
              </div>
              <span className="cv-badge blue">New revision</span>
            </div>
            <form onSubmit={saveBomRevision}>
              <div className="cv-form-grid cv-form-grid-two">
                <div className="cv-field">
                  <span>Project</span>
                  <input value={projectNameDraft} readOnly aria-label="Project for this revision" />
                </div>
                <div className="cv-field">
                  <span>BOM</span>
                  <input value={bomNameDraft} readOnly aria-label="BOM for this revision" />
                </div>
                <label className="cv-field">
                  <span>New revision</span>
                  <input value={revisionDraft} onChange={(event) => setRevisionDraft(event.target.value)} maxLength={80} required />
                </label>
              </div>
              <p className="cv-small-note" style={{ margin: "8px 0 12px" }}>
                Rename or move this BOM from Manage saved BOMs. New revisions stay attached to the same project and BOM history.
              </p>

              {decisions.some((decision) => decision.decision !== "reject_alternate") ? (
                <section className="cv-card pad" style={{ margin: "14px 0", background: "#f8fbff" }}>
                  <h3 className="cv-card-title">Replacement candidates from this BOM</h3>
                  <p className="cv-card-subtitle">Use a candidate in the draft to update the new report. This does not modify the source report or qualify the part; only an approved decision is linked as approval evidence.</p>
                  <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                    {decisions
                      .filter((decision) => decision.decision !== "reject_alternate")
                      .map((decision) => {
                        const sourcePartPresent = bomEditorRows.some(
                          (row) => row.mpn.trim().toLowerCase() === decision.part_a.trim().toLowerCase(),
                        );
                        const candidateInDraft = bomEditorRows.some(
                          (row) => row.mpn.trim().toLowerCase() === decision.part_b.trim().toLowerCase(),
                        );
                        const candidateUsed = usedDecisionIds.includes(decision.id);
                        return (
                          <div key={decision.id} style={{ display: "flex", gap: 10, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
                            <span><strong>{decision.part_a}</strong> → <strong>{decision.part_b}</strong> · {decision.reviewer} · {decision.decision === "approve_alternate" ? "Approved" : "Not approved"}</span>
                            <button type="button" className="cv-button small secondary" onClick={() => applyDecisionCandidate(decision)} disabled={candidateUsed || !sourcePartPresent}>
                              {candidateUsed && decision.decision === "approve_alternate" ? "Applied with approval" : candidateUsed ? "In draft · not approved" : !sourcePartPresent && candidateInDraft ? "In draft" : !sourcePartPresent ? "Source part missing" : "Use candidate in draft"}
                            </button>
                          </div>
                        );
                      })}
                  </div>
                </section>
              ) : null}

              <div className="cv-small-note" style={{ margin: "10px 0" }}>
                Creating a revision runs a new analysis and counts toward your workspace plan. If a one-time report is required, Cadivor will show that requirement before saving the analysis.
              </div>
              <div className="cv-table-wrap" style={{ maxHeight: "48vh", overflow: "auto" }}>
                <table className="cv-table">
                  <thead><tr><th>MPN</th><th>Manufacturer</th><th>Description</th><th>Parent MPN</th><th>Line type</th><th>Quantity</th><th>Action</th></tr></thead>
                  <tbody>
                    {bomEditorRows.map((row, index) => (
                      <tr key={`bom-edit-${index}`}>
                        <td><input aria-label={`Part number row ${index + 1}`} value={row.mpn} onChange={(event) => setBomEditorRows((current) => current.map((item, i) => i === index ? { ...item, mpn: event.target.value } : item))} /></td>
                        <td><input aria-label={`Manufacturer row ${index + 1}`} value={row.manufacturer} onChange={(event) => setBomEditorRows((current) => current.map((item, i) => i === index ? { ...item, manufacturer: event.target.value } : item))} /></td>
                        <td><input aria-label={`Description row ${index + 1}`} value={row.description} onChange={(event) => setBomEditorRows((current) => current.map((item, i) => i === index ? { ...item, description: event.target.value } : item))} /></td>
                        <td><input aria-label={`Parent MPN row ${index + 1}`} value={row.parentMpn} onChange={(event) => setBomEditorRows((current) => current.map((item, i) => i === index ? { ...item, parentMpn: event.target.value } : item))} /></td>
                        <td><input aria-label={`Line type row ${index + 1}`} value={row.lineType} onChange={(event) => setBomEditorRows((current) => current.map((item, i) => i === index ? { ...item, lineType: event.target.value } : item))} /></td>
                        <td><input aria-label={`Quantity row ${index + 1}`} type="number" min="0" step="1" value={row.quantity} onChange={(event) => setBomEditorRows((current) => current.map((item, i) => i === index ? { ...item, quantity: event.target.value } : item))} /></td>
                        <td><button type="button" className="cv-button small" onClick={() => setBomEditorRows((current) => current.filter((_, i) => i !== index))}>Remove</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
                <button type="button" className="cv-button secondary" onClick={() => setBomEditorRows((current) => [...current, { mpn: "", manufacturer: "", description: "", parentMpn: "", lineType: "", quantity: "1" }])}>Add a part</button>
                <span className="cv-small-note">{bomEditorRows.filter((row) => row.mpn.trim()).length} parts · editing creates a separate saved analysis</span>
              </div>
              {revisionError ? <div className="cv-error" role="alert" style={{ marginTop: 12 }}>{revisionError}</div> : null}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 18 }}>
                <button type="button" className="cv-button secondary" disabled={revisionBusy} onClick={() => setBomEditorOpen(false)}>Cancel</button>
                <button type="submit" className="cv-button primary" disabled={revisionBusy || !bomEditorRows.some((row) => row.mpn.trim())}>
                  {revisionBusy ? "Validating and analyzing…" : "Create new revision and report"}
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}

      {report ? (
        <>
          <dl className="cv-record-meta">
            <div className="cv-record-field">
              <dt>Health</dt>
              <dd>
                {report.health_score == null
                  || String(report.health_score).trim().toLowerCase() === "not scored"
                  || String(report.health_score).trim().toLowerCase() === "unknown"
                  ? "Not scored"
                  : `${report.health_score}/100`}
              </dd>
            </div>
            <div className="cv-record-field">
              <dt>Status</dt>
              <dd>{userFacingLabel(report.health_status, "Not reported")}</dd>
            </div>
            <div className="cv-record-field">
              <dt>Components</dt>
              <dd>{report.total_parts}</dd>
            </div>
            <div className="cv-record-field">
              <dt>Evidence basis</dt>
              <dd>{analysisModeLabel(report.mode)}</dd>
            </div>
          </dl>

          <ReportOverview report={report} />

          {report.derived_from_analysis_id ? (
            <section className="cv-card pad" style={{ marginBottom: 14 }} data-testid="revision-provenance">
              <strong>Revision created from an earlier saved BOM</strong>
              <p className="cv-small-note" style={{ margin: "6px 0 0" }}>
                Source report: <Link href={`/reports/${encodeURIComponent(report.derived_from_analysis_id)}`}>open original analysis</Link>
                {report.used_decision_ids?.length
                  ? ` · ${report.used_decision_ids.length} replacement decision candidate${report.used_decision_ids.length === 1 ? "" : "s"} used${report.applied_decision_ids?.length ? ` (${report.applied_decision_ids.length} approved)` : " (none approved)"}`
                  : " · BOM contents edited by the user"}
              </p>
            </section>
          ) : null}

          <section className="cv-card pad cv-report-export" aria-labelledby="report-export-title">
            <div>
              <h2 id="report-export-title" className="cv-card-title">Download this report</h2>
              <p className="cv-card-subtitle">
                Export the saved component risk, hierarchy, and evidence labels for review.
              </p>
            </div>
            <div className="cv-report-export-controls">
              <button type="button" className="cv-button" onClick={() => onDownload("pdf")} disabled={exporting !== null}>
                <Icon name="download" /> {exporting === "pdf" ? "Preparing PDF…" : "Download PDF"}
              </button>
              <button type="button" className="cv-button" onClick={() => onDownload("xlsx")} disabled={exporting !== null}>
                <Icon name="download" /> {exporting === "xlsx" ? "Preparing Excel…" : "Download Excel"}
              </button>
              <button type="button" className="cv-button" onClick={() => onDownload("csv")} disabled={exporting !== null}>
                <Icon name="download" /> {exporting === "csv" ? "Preparing CSV…" : "Download CSV audit"}
              </button>
              <button type="button" className="cv-button" onClick={() => onDownload("plm-csv")} disabled={exporting !== null}>
                <Icon name="download" /> {exporting === "plm-csv" ? "Preparing CSV…" : "Download PLM / ERP CSV"}
              </button>
            </div>
            {exportError ? <div className="cv-error" role="alert">{exportError}</div> : null}
            {report.mode === "synthetic-preview" ? (
              <p className="cv-small-note">This report uses synthetic preview evidence. Stock, prices, and lifecycle estimates are not live supplier verification.</p>
            ) : null}
          </section>

          <section className="cv-card pad cv-report-export" aria-labelledby="compliance-export-title">
            <div>
              <h2 id="compliance-export-title" className="cv-card-title">Compliance and lifecycle evidence</h2>
              <p className="cv-card-subtitle">
                Download component-level RoHS, REACH, PFAS, PCN, or combined evidence data for this BOM. Missing or unverified fields remain unknown; Cadivor does not assert compliance.
              </p>
            </div>
            <div className="cv-report-export-controls">
              {(["rohs", "reach", "pfas", "pcn", "audit"] as CompliancePackType[]).map((packType) => (
                <button
                  key={packType}
                  type="button"
                  className="cv-button"
                  onClick={() => void onDownloadCompliance(packType)}
                  disabled={complianceExporting !== null}
                >
                  {complianceExporting === packType
                    ? "Preparing JSON…"
                    : packType === "audit" ? "Evidence bundle" : `${packType.toUpperCase()} pack`}
                </button>
              ))}
            </div>
            {complianceExportError ? <div className="cv-error" role="alert">{complianceExportError}</div> : null}
          </section>

          <div className="cv-kpis">
            <KpiCard
              icon="risk"
              tone="amber"
              label="High risk"
              value={reportRiskCounts?.high ?? report.high_risk_count}
              detail="Needs review"
            />
            <KpiCard
              icon="bell"
              tone="blue"
              label="Medium risk"
              value={reportRiskCounts?.medium ?? report.medium_risk_count}
              detail="Follow up"
            />
            <KpiCard
              icon="check"
              label="Low risk"
              value={reportRiskCounts?.low ?? report.low_risk_count}
              detail="Within BOM"
            />
          </div>

          <AskCadivorPanel
            token={session.access_token}
            analysisId={String(report.analysis_id || report.id)}
          />

          <section className="cv-card pad" style={{ marginBottom: 14 }}>
            <div className="cv-eyebrow">Engineering decision record</div>
            <h2 className="cv-card-title" style={{ fontSize: 20, marginTop: 8 }}>
              {userFacingLabel(report.project_name || report.filename, "Saved analysis")}
            </h2>
            <p className="cv-card-subtitle">
              {[
                report.bom_name ? `BOM ${userFacingLabel(report.bom_name, "Saved BOM")}` : null,
                report.revision ? `rev ${userFacingLabel(report.revision, "—")}` : null,
                report.persisted ? "Saved to this workspace" : null,
              ]
                .filter(Boolean)
                .join(" · ") ||
                cleanUserText(report.summary_message) ||
                "Synthetic analysis; live supplier data is not included."}
            </p>
            {verifiedSupplierRows > 0 || syntheticSupplierRows > 0 || missingSupplierRows > 0 || report.mode === "synthetic-preview" ? (
              <p className="cv-small-note" style={{ marginTop: 8 }}>
                Evidence is recorded per field. A live identity match does not make synthetic prices, stock, or lifecycle values live.
              </p>
            ) : null}
          </section>

          <section className="cv-card pad cv-report-decisions" style={{ marginBottom: 14 }}>
            <div className="cv-eyebrow">Comparison history</div>
            <h2 className="cv-card-title" style={{ marginTop: 8 }}>Engineering decisions for this BOM</h2>
            <p className="cv-card-subtitle">Each entry preserves the reviewer’s rationale and the comparison evidence snapshot used at the time.</p>
            {decisionError ? <div className="cv-error" role="alert">Decision history could not load. {decisionError}</div> : null}
            {decisions.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead>
                    <tr>
                      <th>Saved</th>
                      <th>Current</th>
                      <th>Candidate</th>
                      <th>Decision</th>
                      <th>Reviewer / rationale</th>
                      <th>Approval details</th>
                      <th>Evidence status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {decisions.map((decision) => {
                      const snapshot = (decision.comparison_snapshot || {}) as Record<string, unknown>;
                      const evidenceStatus = String(
                        snapshot.engineering_evidence_status
                        || (decision.verified_primary_evidence ? "verified" : "unverified")
                      );
                      return (
                      <tr key={decision.id}>
                        <td>{decision.created_at ? new Date(decision.created_at).toLocaleDateString() : "—"}</td>
                        <td><strong>{decision.part_a}</strong></td>
                        <td><strong>{decision.part_b}</strong></td>
                        <td><span className="cv-badge blue">{decision.decision_label}</span></td>
                        <td>
                          {decision.reviewer}
                          <div className="cv-muted">{cleanUserText(decision.rationale)}</div>
                        </td>
                        <td>
                          {decision.validation_checks?.length ? (
                            <div className="cv-small-note">
                              Checks: {decision.validation_checks.map((item) => item.replaceAll("_", " ")).join(" · ")}
                            </div>
                          ) : (
                            <div className="cv-small-note">No validation checks recorded</div>
                          )}
                          {decision.follow_up_action ? (
                            <div className="cv-small-note">
                              Follow-up: {decision.follow_up_action}
                              {decision.follow_up_owner ? ` · ${decision.follow_up_owner}` : ""}
                              {decision.follow_up_due_date ? ` · due ${decision.follow_up_due_date}` : ""}
                            </div>
                          ) : null}
                          <div className="cv-small-note">Residual risk: {decision.residual_risk || "not assessed"}</div>
                          {snapshot.finding ? (
                            <div className="cv-small-note">Compare finding: {String(snapshot.finding)}</div>
                          ) : null}
                        </td>
                        <td>
                          <span className="cv-badge amber">Not qualified by Cadivor</span>
                          <div className="cv-small-note">Snapshot evidence: {evidenceStatus}</div>
                          <div className="cv-small-note">{decision.qualification_note}</div>
                        </td>
                      </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : !decisionError ? (
              <div className="cv-small-note" style={{ marginTop: 12 }}>No comparison decisions have been recorded for this analysis.</div>
            ) : null}
          </section>

          {report.hierarchy?.has_hierarchy ? (
            <section className="cv-card pad" style={{ marginBottom: 14 }}>
              <div style={{ marginBottom: 12 }}>
                <h3 className="cv-card-title">Assembly risk roll-up</h3>
                <p className="cv-card-subtitle">
                  Parent/child quantities multiplied along the path. Assembly
                  risk is the worst leaf risk under that node — drill into
                  contributors for evidence.
                </p>
              </div>
              {report.hierarchy.top_level ? (
                <div className="cv-kpis" style={{ marginBottom: 12 }}>
                  <KpiCard
                    icon="risk"
                    tone="amber"
                    label="Highest assembly risk"
                    value={String(report.hierarchy.top_level.rolled_risk_level || "Not reported")}
                    detail={String(report.hierarchy.top_level.mpn || "Top assembly")}
                  />
                  <KpiCard
                    icon="box"
                    label="Leaf components"
                    value={String(report.hierarchy.top_level.leaf_count ?? "Not reported")}
                    detail="Components beneath the top assembly"
                  />
                  <KpiCard
                    icon="risk"
                    tone="blue"
                    label="High-risk leaf components"
                    value={String(report.hierarchy.top_level.high_risk_leaves ?? 0)}
                    detail="Need engineering review"
                  />
                </div>
              ) : null}
              <div className="cv-table-wrap">
                <table className="cv-table">
                  <thead>
                    <tr>
                      <th>Assembly</th>
                      <th>Path</th>
                      <th>Eff. qty</th>
                      <th>Rolled risk</th>
                      <th>High / Med leaves</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(report.hierarchy.assemblies || []).map((row, index) => (
                      <tr key={`${String(row.mpn)}-${index}`}>
                        <td>
                          <strong>{String(row.mpn)}</strong>
                          <div className="cv-small-note">
                            {String(row.description || "")}
                          </div>
                        </td>
                        <td>{String(row.bom_path || "")}</td>
                        <td>{String(row.effective_quantity ?? "")}</td>
                        <td>
                          <span
                            className={`cv-badge ${riskBadge(String(row.rolled_risk_level || ""))}`}
                          >
                            {String(row.rolled_risk_level || "—")}
                          </span>
                        </td>
                        <td>
                          {String(row.high_risk_leaves ?? 0)} /{" "}
                          {String(row.medium_risk_leaves ?? 0)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {(report.hierarchy.priority_contributors || []).length ? (
                <>
                  <h3
                    className="cv-card-title"
                    style={{ fontSize: 15, marginTop: 16 }}
                  >
                    Drill-down contributors
                  </h3>
                  <div className="cv-table-wrap" style={{ marginTop: 8 }}>
                    <table className="cv-table">
                      <thead>
                        <tr>
                          <th>Part</th>
                          <th>Path</th>
                          <th>Eff. qty</th>
                          <th>Risk</th>
                          <th>Evidence</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(report.hierarchy.priority_contributors || []).map(
                          (row, index) => (
                            <tr key={`${String(row.mpn)}-c-${index}`}>
                              <td>
                                <strong>{String(row.mpn)}</strong>
                                <div className="cv-small-note">
                                  {cleanUserText(row.why)}
                                </div>
                              </td>
                              <td>{String(row.bom_path || "")}</td>
                              <td>{String(row.effective_quantity ?? "")}</td>
                              <td>
                                <span
                                  className={`cv-badge ${riskBadge(String(row.risk_level || ""))}`}
                                >
                                  {String(row.risk_level || "—")}
                                </span>
                              </td>
                              <td>
                                {String(
                                  evidenceSourceLabel(row.evidence_source),
                                )}
                              </td>
                            </tr>
                          ),
                        )}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : null}
            </section>
          ) : null}

          <section className="cv-card pad" id="report-evidence">
            <div style={{ marginBottom: 12 }}>
              <h3 className="cv-card-title">Component signals</h3>
              <p className="cv-card-subtitle">
                Part-level rows with quantity-per-parent and effective quantity
                when hierarchy is present. Evidence labels appear with each risk signal.
              </p>
              {!review?.evidenceReviewedAt ? (
                <button
                  type="button"
                  className="cv-button"
                  style={{ marginTop: 10 }}
                  onClick={() => {
                    setReview(
                      markReviewProgress(
                        String(params.id),
                        { evidenceReviewedAt: new Date().toISOString() },
                        session,
                      ),
                    );
                  }}
                >
                  Mark evidence reviewed
                </button>
              ) : null}
            </div>
            <div className="cv-table-wrap">
              <table className="cv-table">
                <thead>
                  <tr>
                    <th>MPN</th>
                    <th>Parent</th>
                    <th>Qty / parent</th>
                    <th>Eff. qty</th>
                    <th>Lifecycle</th>
                    <th>Risk</th>
                    <th className="cv-table-action">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {report.parts.map((part, index) => {
                    const risk = String(part["Risk Level"] || "");
                    const mpn = String(part.MPN || "");
                    return (
                      <tr key={`${mpn}-${index}`}>
                        <td>
                          <div className="cv-part-cell">
                            <PartThumbnail part={part} />
                            <span>
                              <strong>{mpn}</strong>
                              {(() => {
                                const lineType = String(part.line_type || part["Line Type"] || "").trim();
                                if (!lineType || lineType.toLowerCase() === "part") return null;
                                return <span className="cv-small-note">{lineType}</span>;
                              })()}
                            </span>
                          </div>
                        </td>
                        <td>
                          {String(
                            part.parent_mpn || part["Parent MPN"] || "—",
                          )}
                        </td>
                        <td>
                          {String(
                            part.quantity_per_parent ?? part.Quantity ?? "",
                          )}
                        </td>
                        <td>
                          {String(
                            part.effective_quantity ?? part.Quantity ?? "",
                          )}
                        </td>
                        <td>{String(part.Lifecycle || "")}</td>
                        <td>
                          <span className={`cv-badge ${riskBadge(risk)}`}>
                            {risk || "—"}
                          </span>
                        </td>
                        <td className="cv-table-action">
                          {mpn ? (
                            <Link
                              className="cv-table-open"
                              href={`/find-replacement?mpn=${encodeURIComponent(mpn)}&analysis_id=${encodeURIComponent(String(report.analysis_id || report.id))}&manufacturer=${encodeURIComponent(String(part.Manufacturer || ""))}`}
                            >
                              Replace
                            </Link>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : !error ? (
        <section className="cv-loading">
          Loading saved report…
          <div className="cv-progress" aria-hidden>
            <i />
          </div>
        </section>
      ) : (
        <button
          type="button"
          className="cv-button"
          onClick={() => router.push("/bom-analyzer")}
        >
          Return to BOM Analyzer
        </button>
      )}
    </Shell>
  );
}


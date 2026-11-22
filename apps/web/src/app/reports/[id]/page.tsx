"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { AskCadivorPanel } from "@/components/AskCadivorPanel";
import { AnalysisStageNavigation } from "@/components/AnalysisStageNavigation";
import { Shell } from "@/components/Shell";
import { KpiCard } from "@/components/KpiCard";
import { Icon } from "@/components/Icons";
import { PartThumbnail } from "@/components/PartThumbnail";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import { getReportRiskCounts, ReportOverview } from "@/components/ReportOverview";
import { StatusPill } from "@/components/StatusPill";
import {
  analyzeBom,
  downloadCompliancePack,
  downloadReportExport,
  fetchCompliancePack,
  fetchReport,
  getDecisionCandidates,
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
import { analysisModeLabel, cleanKiCadFieldText, cleanUserText, evidenceSourceLabel, userFacingLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { rememberAnalysis, useRequireSession } from "@/lib/session";
import { trackMarketingEventOnce } from "@/lib/marketingAnalytics";
import complianceStyles from "./complianceEvidence.module.css";

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
    mpn: cleanKiCadFieldText(part.MPN || part.mpn || ""),
    manufacturer: cleanKiCadFieldText(part.Manufacturer || part.manufacturer || ""),
    description: cleanKiCadFieldText(part.Description || part.description || ""),
    parentMpn: cleanKiCadFieldText(part["Parent MPN"] || part.parent_mpn || ""),
    lineType: cleanKiCadFieldText(part["Line Type"] || part.line_type || ""),
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

const COMPLIANCE_REVIEW_TYPES: Array<{
  type: Exclude<CompliancePackType, "audit">;
  title: string;
  description: string;
}> = [
  {
    type: "rohs",
    title: "RoHS",
    description: "Review reported hazardous-substance declarations for each part.",
  },
  {
    type: "reach",
    title: "REACH",
    description: "Review reported substances of very high concern information.",
  },
  {
    type: "pfas",
    title: "PFAS",
    description: "Review reported PFAS declarations and identify evidence gaps.",
  },
  {
    type: "conflict_minerals",
    title: "Conflict minerals",
    description: "Review reported conflict-minerals information and supporting sources.",
  },
  {
    type: "pcn",
    title: "PCN and lifecycle",
    description: "Review change notices and any reported last-time-buy or end-of-life dates.",
  },
];

function asComplianceRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function complianceStatus(status: unknown): { label: string; tone: string } {
  switch (String(status || "")) {
    case "evidence_linked": return { label: "Source attached", tone: "green" };
    case "partial_evidence": return { label: "Partial · review", tone: "amber" };
    case "reported_unverified": return { label: "Reported · verify", tone: "amber" };
    case "conflicting_evidence": return { label: "Conflicting · review", tone: "red" };
    case "supplier_reports_unknown": return { label: "Supplier reports unknown", tone: "gray" };
    default: return { label: "Unknown · no evidence", tone: "gray" };
  }
}

function complianceLifecycleSummary(value: unknown): string {
  const event = asComplianceRecord(value);
  return [
    event.pcn_number ? `PCN ${String(event.pcn_number)}` : "",
    event.pcn_date ? `dated ${String(event.pcn_date)}` : "",
    event.last_time_buy_date ? `last-time-buy ${String(event.last_time_buy_date)}` : "",
    event.end_of_life_date ? `end of life ${String(event.end_of_life_date)}` : "",
    event.estimated_eol_years != null ? `estimated ${String(event.estimated_eol_years)} years to EOL` : "",
  ].filter(Boolean).join(" · ");
}

type ReportLifecycleDisplay = {
  label: string;
  kind: "lifecycle" | "verification";
  note?: string;
};

function reportLifecycleDisplay(part: Record<string, unknown>): ReportLifecycleDisplay {
  const value = String(part.Lifecycle || part.lifecycle || "").trim();
  const hasValue = Boolean(value) && !/^(unknown|not reported|—|-)$/.test(value.toLowerCase());
  if (!hasValue) return { label: "Not reported", kind: "verification" };

  const rawEvidence = part.evidence;
  const evidence = rawEvidence && typeof rawEvidence === "object" && !Array.isArray(rawEvidence)
    ? rawEvidence as { fields?: Record<string, { evidence_class?: string; current?: boolean } | undefined> }
    : {};
  const lifecycle = evidence.fields?.lifecycle;
  const evidenceClass = String(lifecycle?.evidence_class || "");
  if (evidenceClass === "live-authorized-supplier" && lifecycle?.current === true) {
    return { label: value, kind: "lifecycle" };
  }
  if (evidenceClass === "synthetic-preview") {
    return {
      label: "Preview only",
      kind: "verification",
      note: `Preview estimate: ${value}`,
    };
  }
  return {
    label: "Needs verification",
    kind: "verification",
    note: `Reported: ${value} · unverified`,
  };
}

function ReportPageInner() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const session = useRequireSession();
  const requestedApplyDecisionId = (searchParams.get("apply_decision") || "").trim();
  const [report, setReport] = useState<Report | null>(null);
  const [decisions, setDecisions] = useState<DecisionRecord[]>([]);
  const [decisionHistoryLoaded, setDecisionHistoryLoaded] = useState(false);
  const [decisionError, setDecisionError] = useState("");
  const [error, setError] = useState("");
  const [exportError, setExportError] = useState("");
  const [exporting, setExporting] = useState<ReportExportFormat | null>(null);
  const [complianceExporting, setComplianceExporting] = useState<CompliancePackType | null>(null);
  const [complianceExportError, setComplianceExportError] = useState("");
  const [compliancePreviewType, setCompliancePreviewType] = useState<CompliancePackType | null>(null);
  const [compliancePreview, setCompliancePreview] = useState<Record<string, unknown> | null>(null);
  const [compliancePreviewLoading, setCompliancePreviewLoading] = useState<CompliancePackType | null>(null);
  const [compliancePreviewError, setCompliancePreviewError] = useState("");
  const [review, setReview] = useState<BomReviewProgress | null>(null);
  const [bomEditorOpen, setBomEditorOpen] = useState(false);
  const [bomEditorRows, setBomEditorRows] = useState<EditableBomRow[]>([]);
  const [projectNameDraft, setProjectNameDraft] = useState("");
  const [bomNameDraft, setBomNameDraft] = useState("");
  const [revisionDraft, setRevisionDraft] = useState("");
  const [appliedDecisionIds, setAppliedDecisionIds] = useState<string[]>([]);
  const [usedDecisionIds, setUsedDecisionIds] = useState<string[]>([]);
  const [decisionCandidateSelection, setDecisionCandidateSelection] = useState<Record<string, string>>({});
  const [decisionAppliedCandidates, setDecisionAppliedCandidates] = useState<Record<string, string>>({});
  const [revisionBusy, setRevisionBusy] = useState(false);
  const [revisionError, setRevisionError] = useState("");
  const openedDecisionRequest = useRef("");

  useEffect(() => {
    if (!session) return;
    let active = true;
    const analysisKey = String(params.id || "");
    setReport(null);
    setError("");
    setDecisionHistoryLoaded(false);
    setReview(readReviewProgress(analysisKey, session));
    fetchReport(params.id, session.access_token)
      .then((data) => {
        if (!active) return;
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
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Failed to load report");
      });
    listDecisionRecords(session.access_token, params.id)
      .then(({ records }) => {
        if (active) {
          setDecisions(records || []);
          setDecisionHistoryLoaded(true);
        }
      })
      .catch((err) => {
        if (active) {
          setDecisionError(err instanceof Error ? err.message : "Decision history could not load.");
          setDecisionHistoryLoaded(true);
        }
      });
    return () => { active = false; };
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

  async function onReviewCompliance(packType: Exclude<CompliancePackType, "audit">) {
    if (!session || !report) return;
    setCompliancePreviewType(packType);
    setCompliancePreview(null);
    setCompliancePreviewError("");
    setCompliancePreviewLoading(packType);
    try {
      const pack = await fetchCompliancePack(
        session.access_token,
        packType,
        String(report.analysis_id || report.id),
      );
      setCompliancePreview(pack);
    } catch (err) {
      setCompliancePreviewError(err instanceof Error ? err.message : "Evidence records could not be loaded.");
    } finally {
      setCompliancePreviewLoading(null);
    }
  }

  const openBomEditor = useCallback(async (applyDecisionId?: string) => {
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
      let initialRows = editableRows(report.parts || []);
      const selectedDecision = applyDecisionId
        ? decisions.find((decision) => decision.id === applyDecisionId)
        : undefined;
      let initialAppliedDecisionIds: string[] = [];
      let initialUsedDecisionIds: string[] = [];
      const initialCandidateSelection: Record<string, string> = {};
      const initialAppliedCandidates: Record<string, string> = {};
      if (applyDecisionId) {
        if (!selectedDecision || selectedDecision.decision !== "approve_alternate") {
          throw new Error("This approved replacement is not available in the selected BOM report.");
        }
        const currentMpn = selectedDecision.part_a.trim().toLowerCase();
        const candidates = getDecisionCandidates(selectedDecision);
        if (!candidates.length || candidates.some((candidate) => candidate.mpn.toLowerCase() === currentMpn)) {
          throw new Error("This decision does not contain a distinct replacement part number.");
        }
        if (!initialRows.some((row) => row.mpn.trim().toLowerCase() === currentMpn)) {
          throw new Error(`The current part ${selectedDecision.part_a} is not present in this saved BOM report.`);
        }
        initialCandidateSelection[selectedDecision.id] = candidates.length === 1 ? candidates[0].mpn : "";
        if (candidates.length === 1) {
          const candidate = candidates[0];
          if (initialRows.some((row) => row.mpn.trim().toLowerCase() === candidate.mpn.toLowerCase())) {
            throw new Error(`The candidate ${candidate.mpn} is already in this BOM. Review the existing line before creating a revision.`);
          }
          initialRows = initialRows.map((row) => row.mpn.trim().toLowerCase() !== currentMpn
            ? row
            : {
                ...row,
                mpn: candidate.mpn,
                manufacturer: candidate.manufacturer || "",
              });
          initialAppliedDecisionIds = [selectedDecision.id];
          initialUsedDecisionIds = [selectedDecision.id];
          initialAppliedCandidates[selectedDecision.id] = candidate.mpn;
        }
      }
      setProjectNameDraft(userFacingLabel(projectName || String(report.project_name || "").split(" — ")[0], "General"));
      setBomNameDraft(userFacingLabel(report.bom_name || report.filename, "Saved BOM"));
      setRevisionDraft(revisionCandidate(String(report.revision || "A"), used));
      setBomEditorRows(initialRows);
      setAppliedDecisionIds(initialAppliedDecisionIds);
      setUsedDecisionIds(initialUsedDecisionIds);
      setDecisionCandidateSelection(initialCandidateSelection);
      setDecisionAppliedCandidates(initialAppliedCandidates);
      setBomEditorOpen(true);
    } catch (err) {
      setRevisionError(err instanceof Error ? err.message : "Saved BOM details could not be loaded.");
    }
  }, [decisions, report, session]);

  useEffect(() => {
    const reportMatchesRoute = report
      && String(report.analysis_id || report.id || "") === String(params.id || "");
    if (!requestedApplyDecisionId || !session || !reportMatchesRoute || !decisionHistoryLoaded) return;
    const requestKey = `${String(params.id || "")}:${requestedApplyDecisionId}`;
    if (openedDecisionRequest.current === requestKey) return;
    openedDecisionRequest.current = requestKey;
    void openBomEditor(requestedApplyDecisionId);
  }, [decisionHistoryLoaded, openBomEditor, params.id, report, requestedApplyDecisionId, session]);

  function applyDecisionCandidate(decision: DecisionRecord, candidateMpnValue?: string) {
    const currentMpn = decision.part_a.trim().toLowerCase();
    const candidates = getDecisionCandidates(decision);
    const selectedMpn = String(
      candidateMpnValue
      || decisionCandidateSelection[decision.id]
      || (candidates.length === 1 ? candidates[0].mpn : ""),
    ).trim();
    const candidate = candidates.find((item) => item.mpn.toLowerCase() === selectedMpn.toLowerCase());
    if (!candidate || candidate.mpn.toLowerCase() === currentMpn) {
      setRevisionError("This decision does not contain a distinct replacement part number.");
      return;
    }
    const previouslyAppliedMpn = decisionAppliedCandidates[decision.id] || "";
    const rowToReplace = previouslyAppliedMpn || currentMpn;
    const rowIndex = bomEditorRows.findIndex((row) => row.mpn.trim().toLowerCase() === rowToReplace.toLowerCase());
    if (rowIndex < 0) {
      setRevisionError(`The current part ${decision.part_a} is not present in this saved BOM revision.`);
      return;
    }
    if (bomEditorRows.some((row, index) => index !== rowIndex && row.mpn.trim().toLowerCase() === candidate.mpn.toLowerCase())) {
      setRevisionError(`The candidate ${candidate.mpn} is already present in this BOM revision.`);
      return;
    }
    setBomEditorRows((current) => current.map((row, index) => index !== rowIndex
      ? row
      : {
          ...row,
          mpn: candidate.mpn,
          manufacturer: candidate.manufacturer || "",
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
    setDecisionCandidateSelection((current) => ({ ...current, [decision.id]: candidate.mpn }));
    setDecisionAppliedCandidates((current) => {
      const next = { ...current };
      decisionsForPart.forEach((id) => { delete next[id]; });
      next[decision.id] = candidate.mpn;
      return next;
    });
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
  const compliancePreviewSummary = asComplianceRecord(compliancePreview?.summary);
  const compliancePreviewRecords = Array.isArray(compliancePreview?.records)
    ? compliancePreview.records.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object" && !Array.isArray(row))
    : [];
  const compliancePreviewTitle = COMPLIANCE_REVIEW_TYPES.find((item) => item.type === compliancePreviewType)?.title || "Evidence records";
  const legacyKiCadMetadataCount = (report?.parts || []).filter((part) =>
    [part.MPN, part.mpn, part.Manufacturer, part.manufacturer].some((value) =>
      /BoardText\(value=[\s\S]*?Vector2\(/.test(String(value || "")),
    ),
  ).length;

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
      {revisionError && !bomEditorOpen ? (
        <div className="cv-error" role="alert" style={{ marginBottom: 14 }}>
          The revision draft could not be prepared. {revisionError} You can open “Edit BOM / new revision” to review it manually.
        </div>
      ) : null}

      <AnalysisStageNavigation
        analysisId={String(report?.analysis_id || report?.id || params.id)}
        current="risks"
      />

      {legacyKiCadMetadataCount > 0 ? (
        <section className="cv-card pad" role="alert" data-testid="legacy-kicad-bom-warning" style={{ borderColor: "#f0bb72", background: "#fffaf1", marginBottom: 14 }}>
          <div className="cv-eyebrow">BOM identity needs correction</div>
          <h2 className="cv-card-title" style={{ marginTop: 4 }}>This report contains KiCad text-object metadata</h2>
          <p className="cv-card-subtitle" style={{ marginTop: 6 }}>
            {legacyKiCadMetadataCount} component row(s) contain older KiCad text-object data in the part number or manufacturer. Cadivor recovered the visible field text for review, but the supplier checks in this saved analysis used the malformed value. Open “Edit BOM / new revision” to verify the recovered part numbers and rerun supplier checks before using the results.
          </p>
          <button type="button" className="cv-button primary" style={{ marginTop: 12 }} onClick={() => void openBomEditor()}>
            Review values and rerun checks
          </button>
        </section>
      ) : null}

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
                <p>The current saved report stays unchanged. Cadivor validates and re-analyzes the edited part list as a new revision on this saved BOM{usedDecisionIds.length ? "; the selected approved replacement is already applied in this draft" : ""}.</p>
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
                  <h3 className="cv-card-title">Choose replacement options for this revision</h3>
                  <p className="cv-card-subtitle">A decision can include multiple approved alternatives. Choose one option for each source part in this BOM revision. You can apply replacements for different source parts in the same revision. The source report stays unchanged, and creating a revision does not independently qualify a part.</p>
                  <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                    {decisions
                      .filter((decision) => decision.decision !== "reject_alternate")
                      .map((decision) => {
                        const candidates = getDecisionCandidates(decision);
                        const selectedMpn = decisionCandidateSelection[decision.id]
                          || (candidates.length === 1 ? candidates[0]?.mpn || "" : "");
                        const appliedMpn = decisionAppliedCandidates[decision.id] || "";
                        const rowToReplace = appliedMpn || decision.part_a;
                        const sourcePresent = bomEditorRows.some(
                          (row) => row.mpn.trim().toLowerCase() === rowToReplace.trim().toLowerCase(),
                        );
                        const selectedCandidateInDraft = selectedMpn && bomEditorRows.some(
                          (row) => row.mpn.trim().toLowerCase() === selectedMpn.toLowerCase(),
                        );
                        const alreadyApplied = Boolean(appliedMpn && selectedMpn.toLowerCase() === appliedMpn.toLowerCase());
                        const canApply = Boolean(selectedMpn && sourcePresent && !alreadyApplied && !selectedCandidateInDraft);
                        const alternativeLabel = candidates.map((candidate) => candidate.manufacturer
                          ? `${candidate.mpn} · ${candidate.manufacturer}`
                          : candidate.mpn).join("; ");
                        return (
                          <div key={decision.id} style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
                            <span style={{ flex: "1 1 260px", minWidth: 0 }}>
                              <strong>{decision.part_a}</strong> → {candidates.length > 1 ? `${candidates.length} alternatives` : <strong>{candidates[0]?.mpn || decision.part_b}</strong>}
                              <span className="cv-small-note" style={{ display: "block" }}>{alternativeLabel} · {decision.reviewer} · {decision.decision === "approve_alternate" ? "Approved" : "Not approved"}</span>
                            </span>
                            {candidates.length > 1 ? (
                              <label className="cv-field" style={{ margin: 0, flex: "1 1 220px", minWidth: 0 }}>
                                <span className="cv-small-note">Choose one for this BOM</span>
                                <select
                                  value={selectedMpn}
                                  aria-label={`Choose replacement for ${decision.part_a}`}
                                  onChange={(event) => setDecisionCandidateSelection((current) => ({ ...current, [decision.id]: event.target.value }))}
                                >
                                  <option value="">Choose a replacement</option>
                                  {candidates.map((candidate) => <option key={candidate.mpn} value={candidate.mpn}>{candidate.mpn}{candidate.manufacturer ? ` · ${candidate.manufacturer}` : ""}</option>)}
                                </select>
                              </label>
                            ) : <span className="cv-small-note">One available candidate</span>}
                            <button
                              type="button"
                              className="cv-button small secondary"
                              onClick={() => applyDecisionCandidate(decision, selectedMpn)}
                              disabled={!canApply}
                            >
                              {alreadyApplied ? "Applied · choose another to change" : selectedCandidateInDraft ? "Already in this BOM" : !sourcePresent ? "Source part missing" : !selectedMpn ? "Choose an option" : appliedMpn ? "Change selected option" : decision.decision === "approve_alternate" ? "Use approved option" : "Use candidate for evaluation"}
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

          <section className={`cv-card pad ${complianceStyles.evidenceCard}`} aria-labelledby="compliance-export-title">
            <div className={complianceStyles.evidenceIntro}>
              <div>
                <h2 id="compliance-export-title" className="cv-card-title">Review compliance and lifecycle evidence</h2>
                <p className="cv-card-subtitle">
                  These records summarize evidence already attached to this analysis. Review them here first; export JSON only when you need to hand the working papers to Quality/Compliance or archive them with your controlled records.
                </p>
              </div>
              <p className={complianceStyles.workflowNote}>
                <strong>What to do:</strong> open a source declaration or notice, follow up on missing evidence, then record your disposition in your internal QMS/PLM. Cadivor does not certify compliance, and the export does not sync directly to another system.
              </p>
            </div>

            <div className={complianceStyles.topicActions} role="group" aria-label="Review evidence by topic">
              {COMPLIANCE_REVIEW_TYPES.map((item) => (
                <button
                  key={item.type}
                  type="button"
                  className={`cv-button ${compliancePreviewType === item.type ? "primary" : "secondary"} ${complianceStyles.topicButton}`}
                  aria-pressed={compliancePreviewType === item.type}
                  onClick={() => void onReviewCompliance(item.type)}
                  disabled={compliancePreviewLoading !== null || complianceExporting !== null}
                >
                  {compliancePreviewLoading === item.type ? "Loading records…" : `Review ${item.title}`}
                </button>
              ))}
              <button
                type="button"
                className={`cv-button secondary ${complianceStyles.topicButton}`}
                onClick={() => void onDownloadCompliance("audit")}
                disabled={complianceExporting !== null || compliancePreviewLoading !== null}
              >
                <Icon name="download" />
                {complianceExporting === "audit" ? "Preparing JSON…" : "Export full evidence bundle"}
              </button>
            </div>
            <p className={complianceStyles.exportHint}>
              The full bundle contains all available compliance topic records plus lifecycle fields in one JSON file. Use it for a manual handoff or archive; it is not a compliance certificate.
            </p>

            {complianceExportError ? <div className="cv-error" role="alert">{complianceExportError}</div> : null}
            {compliancePreviewError ? <div className="cv-error" role="alert">{compliancePreviewError}</div> : null}

            {compliancePreviewType ? (
              <div className={complianceStyles.previewPanel} aria-live="polite">
                <div className={complianceStyles.previewHeader}>
                  <div>
                    <h3>{compliancePreviewTitle} records</h3>
                    <p>{COMPLIANCE_REVIEW_TYPES.find((item) => item.type === compliancePreviewType)?.description}</p>
                  </div>
                  <button
                    type="button"
                    className="cv-button secondary"
                    onClick={() => void onDownloadCompliance(compliancePreviewType)}
                    disabled={complianceExporting !== null || compliancePreviewLoading !== null}
                  >
                    <Icon name="download" />
                    {complianceExporting === compliancePreviewType ? "Preparing JSON…" : `Export ${compliancePreviewTitle} JSON`}
                  </button>
                </div>
                {compliancePreviewLoading === compliancePreviewType ? (
                  <p className={complianceStyles.loadingMessage}>Loading component records…</p>
                ) : compliancePreview ? (
                  <>
                    <div className={complianceStyles.summaryBadges}>
                      <span className="cv-badge green">{Number(compliancePreviewSummary.evidence_linked || 0)} source attached</span>
                      <span className="cv-badge amber">{Number(compliancePreviewSummary.partial_evidence || 0)} partial</span>
                      <span className="cv-badge red">{Number(compliancePreviewSummary.conflicting_evidence || 0)} conflicting</span>
                      <span className="cv-badge amber">{Number(compliancePreviewSummary.reported_unverified || 0)} reported, verify</span>
                      <span className="cv-badge gray">{Number(compliancePreviewSummary.unknown ?? (Number(compliancePreviewSummary.missing_evidence || 0) + Number(compliancePreviewSummary.supplier_reports_unknown || 0)))} unknown</span>
                      <span className={complianceStyles.totalCount}>{Number(compliancePreviewSummary.total || 0)} components</span>
                    </div>
                    <p className={complianceStyles.rowDetail}>
                      Counts cover every component once. “Unknown” includes missing records and supplier responses that say unknown; conflicts and partial evidence remain separate.
                    </p>
                    {compliancePreviewRecords.length ? (
                      <div className={`cv-table-wrap ${complianceStyles.previewTableWrap}`}>
                        <table className={`cv-table ${complianceStyles.previewTable}`}>
                          <thead>
                            <tr>
                              <th>Component</th>
                              <th>Evidence status</th>
                              <th>Reported information</th>
                              <th>Source / review note</th>
                            </tr>
                          </thead>
                          <tbody>
                            {compliancePreviewRecords.map((row, index) => {
                              const state = complianceStatus(row.status);
                              const sourceRows = Array.isArray(row.sources)
                                ? row.sources.filter((source): source is Record<string, unknown> => Boolean(source) && typeof source === "object" && !Array.isArray(source))
                                : [];
                              const sourcesToShow = sourceRows.length
                                ? sourceRows
                                : [{ source: row.source, source_url: row.source_url }];
                              const lifecycleSummary = complianceLifecycleSummary(row.lifecycle_events);
                              const reported = row.reported_value == null || String(row.reported_value).trim() === ""
                                ? "No value reported"
                                : String(row.reported_value);
                              const reviewNote = String(row.gap || "Open the source and confirm that it supports the reported value.");
                              return (
                                <tr key={`${String(row.mpn || "part")}-${index}`}>
                                  <td><strong>{String(row.mpn || "Part not identified")}</strong></td>
                                  <td><span className={`cv-badge ${state.tone}`}>{state.label}</span></td>
                                  <td>
                                    <span className={complianceStyles.reportedValue}>{reported}</span>
                                    {lifecycleSummary ? <small className={complianceStyles.rowDetail}>{lifecycleSummary}</small> : null}
                                    {row.retrieved_at ? <small className={complianceStyles.rowDetail}>Recorded {String(row.retrieved_at)}</small> : null}
                                  </td>
                                  <td>
                                    <div style={{ display: "grid", gap: 4 }}>
                                      {sourcesToShow.map((source, sourceIndex) => {
                                        const sourceUrl = String(source.source_url || source.url || "").trim();
                                        const safeSourceUrl = /^https:\/\//i.test(sourceUrl) ? sourceUrl : "";
                                        const sourceName = String(source.source || row.source || "Supplier source");
                                        const sourceValue = String(source.reported_value || source.status || "").trim();
                                        return (
                                          <span key={`${sourceName}-${sourceIndex}`}>
                                            {safeSourceUrl ? <a href={safeSourceUrl} target="_blank" rel="noreferrer">{sourceName}</a> : sourceName}
                                            {sourceValue ? ` · ${sourceValue}` : ""}
                                          </span>
                                        );
                                      })}
                                    </div>
                                    <small className={complianceStyles.rowDetail}>{reviewNote}</small>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className={complianceStyles.loadingMessage}>No component records were returned for this topic.</p>
                    )}
                    <p className={complianceStyles.unknownNote}>
                      “Unknown” means this analysis has no source-backed record for that component. It does not mean compliant, noncompliant, or that no change notice exists.
                    </p>
                  </>
                ) : null}
              </div>
            ) : null}
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
                      <th>Replacement alternatives</th>
                      <th>Decision</th>
                      <th>Reviewer / rationale</th>
                      <th>Approval details</th>
                      <th>Evidence status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {decisions.map((decision) => {
                      const snapshot = (decision.comparison_snapshot || {}) as Record<string, unknown>;
                      const alternatives = getDecisionCandidates(decision);
                      const evidenceStatus = String(
                        snapshot.engineering_evidence_status
                        || (decision.verified_primary_evidence ? "verified" : "unverified")
                      );
                      return (
                      <tr key={decision.id}>
                        <td>{decision.created_at ? new Date(decision.created_at).toLocaleDateString() : "—"}</td>
                        <td><strong>{decision.part_a}</strong></td>
                        <td><strong>{alternatives.map((candidate) => candidate.manufacturer
                          ? `${candidate.mpn} · ${candidate.manufacturer}`
                          : candidate.mpn).join("; ") || decision.part_b}</strong></td>
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
                      <th title="Total quantity after multiplying quantities through parent assemblies.">Effective qty</th>
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
                          <th title="Evidence-based risk classification; incomplete, stale, or conflicting records show Needs verification.">Risk status</th>
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
              <h3 className="cv-card-title">BOM line risk and evidence</h3>
              <p className="cv-card-subtitle">
                One row per BOM line. Parent assembly is the assembly containing the line; “—” means no parent hierarchy was provided. Qty / parent is the line quantity under that assembly, while effective quantity multiplies quantities through the hierarchy. Risk is recalculated from available field-level evidence; insufficient or conflicting verification is shown as Needs verification.
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
                    <th title="The assembly containing this BOM line; — means no parent hierarchy was provided.">Parent assembly</th>
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
                    const mpn = cleanKiCadFieldText(part.MPN || part.mpn || "");
                    const lifecycleDisplay = reportLifecycleDisplay(part);
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
                          {cleanKiCadFieldText(part.parent_mpn || part["Parent MPN"] || "—")}
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
                        <td>
                          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6 }}>
                            <StatusPill kind={lifecycleDisplay.kind} value={lifecycleDisplay.label} />
                            {lifecycleDisplay.note ? (
                              <small className="cv-small-note">{lifecycleDisplay.note}</small>
                            ) : null}
                          </div>
                        </td>
                        <td>
                          <span className={`cv-badge ${riskBadge(risk)}`}>
                            {risk || "—"}
                          </span>
                        </td>
                        <td className="cv-table-action">
                          {mpn ? (
                            <Link
                              className="cv-table-open"
                              href={`/find-replacement?mpn=${encodeURIComponent(mpn)}&analysis_id=${encodeURIComponent(String(report.analysis_id || report.id))}&manufacturer=${encodeURIComponent(cleanKiCadFieldText(part.Manufacturer || part.manufacturer || ""))}`}
                            >
                              Find replacement
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

export default function ReportPage() {
  return (
    <Suspense fallback={<div className="cv-loading">Loading saved report…</div>}>
      <ReportPageInner />
    </Suspense>
  );
}


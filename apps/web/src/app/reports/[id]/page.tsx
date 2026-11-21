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
  fetchCompliancePack,
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
  const compliancePreviewSummary = asComplianceRecord(compliancePreview?.summary);
  const compliancePreviewRecords = Array.isArray(compliancePreview?.records)
    ? compliancePreview.records.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object" && !Array.isArray(row))
    : [];
  const compliancePreviewTitle = COMPLIANCE_REVIEW_TYPES.find((item) => item.type === compliancePreviewType)?.title || "Evidence records";
  const legacyKiCadMetadataCount = (report?.parts || []).filter((part) =>
    [part.MPN, part.mpn, part.Manufacturer, part.manufacturer].some((value) =>
      /BoardText\(value=[\s\S]*?Vector2\(/.tes